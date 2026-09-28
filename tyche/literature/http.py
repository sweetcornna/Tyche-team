"""Polite, cached HTTP access for public scholarly APIs.

* One minimum interval per host (arXiv asks for about 3 seconds).
* Retries with exponential backoff on 429 and 5xx responses, waiting at least as long as the
  service asks (``Retry-After``, or OpenAlex's ``retryAfter`` field), up to ``max_wait``.
* An SQLite response cache keyed by URL, so reruns and resumes do not hammer
  the APIs and a completed survey can be replayed offline.
* An injectable ``httpx`` transport, which tests use to serve fixtures.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

import httpx

from tyche import __version__


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int | None, detail: str):
        super().__init__(f"{url}: {status or 'no response'} {detail}")
        self.url = url
        self.status = status


class ResponseCache:
    def __init__(self, path: Path | None, ttl_days: float):
        self.ttl = ttl_days * 86400
        self._conn = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path))
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, url TEXT, body TEXT, fetched REAL)"
            )
            self._conn.commit()

    @staticmethod
    def key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, url: str) -> str | None:
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT body, fetched FROM responses WHERE key=?", (self.key(url),)
        ).fetchone()
        if row and (time.time() - row[1]) <= self.ttl:
            return row[0]
        return None

    def delete(self, url: str) -> None:
        if self._conn is None:
            return
        with self._conn:
            self._conn.execute("DELETE FROM responses WHERE key=?", (self.key(url),))

    def put(self, url: str, body: str) -> None:
        if self._conn is None:
            return
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses (key, url, body, fetched) VALUES (?,?,?,?)",
                (self.key(url), url, body, time.time()),
            )


class HttpClient:
    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        cache_ttl_days: float = 30,
        timeout: float = 30,
        min_interval: dict[str, float] | None = None,
        contact_email: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
        max_wait: float = 90.0,
    ):
        agent = f"Tyche/{__version__} (research agent; +https://github.com/sweetcornna/Tyche"
        agent += f"; mailto:{contact_email})" if contact_email else ")"
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": agent},
            follow_redirects=True,
            transport=transport,
        )
        self.cache = ResponseCache(cache_path, cache_ttl_days)
        self.min_interval = dict(min_interval or {})
        self.max_retries = max_retries
        self.max_wait = max_wait
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.requests_made = 0
        self.cache_hits = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self.min_interval.get(host, 0.0) - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        validate: Callable[[str], None] | None = None,
        secret_params: dict[str, str] | None = None,
    ) -> str:
        """GET a URL. ``validate`` must raise ValueError for an unusable body; such bodies are never cached.

        ``secret_params`` (API keys a service only accepts in the query string) are sent with
        the request but never enter the cache key, error messages, or anything that is logged.
        """
        public = url + ("?" + urlencode(params, doseq=True) if params else "")
        secrets = {k: v for k, v in (secret_params or {}).items() if v}
        full = url + "?" + urlencode({**(params or {}), **secrets}, doseq=True) if secrets else public
        cached = self.cache.get(public)
        if cached is not None:
            try:
                if validate is not None:
                    validate(cached)
                self.cache_hits += 1
                return cached
            except ValueError:
                self.cache.delete(public)
        host = urlsplit(full).hostname or ""
        delay = 1.5
        last_detail = ""
        for attempt in range(self.max_retries + 1):
            await self._throttle(host)
            asked = 0.0
            try:
                response = await self._client.get(full, headers=headers)
            except httpx.HTTPError as exc:
                last_detail = _redact(f"{type(exc).__name__}: {exc}", secrets)
                status = None
            else:
                self.requests_made += 1
                status = response.status_code
                if status == 200:
                    body = response.text
                    if validate is not None:
                        validate(body)  # ValueError propagates: a malformed 200 is not retried or cached
                    self.cache.put(public, body)
                    return body
                if status == 404:
                    raise HttpError(public, status, "not found")
                last_detail = _redact(response.text[:200], secrets)
                if status == 406 and not last_detail.strip():
                    # export.arxiv.org answers every uncached query this way while it throttles a host.
                    last_detail = "refused with an empty body; the service may be throttling this host, retry later"
                if status not in (429, 500, 502, 503, 504):
                    raise HttpError(public, status, last_detail)
                asked = _retry_after(response)
            if attempt < self.max_retries:
                await asyncio.sleep(min(max(delay, asked), self.max_wait))
                delay *= 2
        raise HttpError(public, None, f"gave up after retries: {last_detail}")


def _retry_after(response: httpx.Response) -> float:
    """Seconds the service asked us to wait: a Retry-After header (seconds or HTTP date) or the
    ``retryAfter`` field OpenAlex puts in its JSON error body; 0 when it asked for nothing."""
    header = response.headers.get("retry-after", "").strip()
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(header).timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    try:
        value = json.loads(response.text).get("retryAfter")
    except (ValueError, AttributeError):
        return 0.0
    return max(0.0, float(value)) if isinstance(value, (int, float)) else 0.0


def _redact(text: str, secrets: dict[str, str]) -> str:
    for value in secrets.values():
        text = text.replace(value, "***")
    return text
