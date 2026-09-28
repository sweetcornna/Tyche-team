"""Model discovery for the local workbench; credentials never enter responses or cache keys."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

MODEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
_NON_CHAT = ("embedding", "tts", "whisper", "moderation", "dall-e", "image", "audio")


def models_endpoint(api_base: str, provider: str) -> str:
    url = urlsplit(api_base.strip())
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("API base must be an HTTP(S) URL without embedded credentials")
    if url.query or url.fragment:
        raise ValueError("API base must not contain a query or fragment")
    path = url.path.rstrip("/")
    if provider.lower() == "anthropic" and not path:
        path = "/v1"
    if not path.endswith("/models"):
        path += "/models"
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def cache_key(endpoint: str, provider: str, api_key: str) -> str:
    return hashlib.sha256(f"{endpoint}\0{provider}\0{api_key}".encode()).hexdigest()


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def normalize_models(data: Any) -> list[dict[str, Any]]:
    rows = data if isinstance(data, list) else data.get("data", data.get("models")) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("The upstream response does not contain a model list")
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, str):
            row = {"id": row}
        if not isinstance(row, dict):
            continue
        name = row.get("id") or row.get("name")
        if not isinstance(name, str) or not MODEL_NAME_RE.fullmatch(name):
            continue
        if any(word in name.lower() for word in _NON_CHAT):
            continue
        top = row.get("top_provider") or {}
        if not isinstance(top, dict):
            top = {}
        models.setdefault(name, {
            "id": name,
            "context_length": _positive_int(row.get("context_length") or row.get("context_window")),
            "max_completion_tokens": _positive_int(row.get("max_completion_tokens") or top.get("max_completion_tokens")),
            "owned_by": row.get("owned_by") if isinstance(row.get("owned_by"), str) else None,
        })
    return sorted(models.values(), key=lambda item: item["id"].lower())


async def fetch_models(endpoint: str, provider: str, api_key: str) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if provider.lower() == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if api_key:
            headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    models: dict[str, dict[str, Any]] = {}
    params: dict[str, str] = {}
    cursors: set[str] = set()
    # Keep pagination on the configured URL: never forward credentials to a returned next URL.
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
        for _ in range(10):
            response = await client.get(endpoint, headers=headers, params=params)
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("The upstream model list is too large")
            data = response.json()
            models.update((model["id"], model) for model in normalize_models(data))
            if not isinstance(data, dict) or not data.get("has_more"):
                break
            cursor = data.get("last_id")
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("The upstream model list has invalid pagination")
            cursors.add(cursor)
            params = {"after_id" if provider.lower() == "anthropic" else "after": cursor}
        else:
            raise ValueError("The upstream model list has too many pages")
    if not models:
        raise ValueError("The upstream returned no usable text models")
    return sorted(models.values(), key=lambda item: item["id"].lower())


def discovery_error(exc: Exception) -> str:
    # HTTP bodies, URLs and transport exception strings can contain credentials. Do not echo them.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Upstream model lookup failed (HTTP {exc.response.status_code})"
    if isinstance(exc, httpx.TimeoutException):
        return "Upstream model lookup timed out"
    if isinstance(exc, httpx.RequestError):
        return "Cannot connect to the upstream model endpoint"
    return "Upstream returned an invalid or empty model list"
