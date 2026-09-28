"""FastAPI application for ``tyche ui``.

``create_app`` builds one app bound to one workspace; ``serve`` runs it with uvicorn. Every
handler here is thin: it resolves paths, applies the small validations the API contract asks for,
and calls into ``tyche.web.runs`` (pure reads), ``tyche.web.processes`` (launch/stop/detect), and
``tyche.web.settings`` (``.env`` read/write). Deterministic code stays the sole owner of what
gets returned; models are never asked anything here.
"""

from __future__ import annotations

import asyncio
import hmac
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from tyche import STAGES, __version__
from tyche.agent.inbox import list_messages, post_message
from tyche.config import DIRECTIONS, TycheConfig, load_direction
from tyche.trace import claim_map_for_run, lineage_graph, revision_history
from tyche.web import runs as web_runs
from tyche.web.processes import Launcher, LauncherProtocol, ProcessRegistry
from tyche.web.settings import SECRET_KEYS, SettingsError, VALUE_KEYS, apply_env_updates, read_key_presence, read_values
from tyche.workspace import RUN_ID_PATTERN, read_json, sha256_file

REASONING_LEVELS = ("low", "medium", "high", "xhigh", "max")
_ENGINES = ("openjiuwen", "imported", "fixture")
_RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
# Model identifiers reach the CLI as ``--set`` values, which are YAML-parsed and ``${VAR}``-expanded;
# anything outside this set could read an environment variable into a logged setting.
_MODEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
_BAD_MODEL_WORDS = ("image", "embedding", "tts", "whisper", "audio", "moderation")
_NOT_BUILT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Tyche</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;">
<h1>Tyche frontend is not built</h1>
<p>Build it once, then reload this page:</p>
<pre>npm --prefix tyche/web/frontend ci &amp;&amp; npm --prefix tyche/web/frontend run build</pre>
</body></html>
"""


class ApiError(StarletteHTTPException):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


# -- app state ----------------------------------------------------------------


@dataclass
class AppState:
    workspace_root: Path
    config_path: str | None
    overrides: list[str]
    env_file: Path | None
    static_dir: Path | None
    launcher: LauncherProtocol
    registry: ProcessRegistry
    server_cwd: Path
    host: str
    port: int
    models_cache: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    _locks: dict[str, threading.Lock] = field(default_factory=dict)
    _locks_guard: threading.Lock = field(default_factory=threading.Lock)

    def run_lock(self, run_id: str) -> threading.Lock:
        """Held while a request checks that a run is idle and then launches or deletes it."""
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())


def _default_static_dir() -> Path:
    return Path(__file__).resolve().parent / "frontend" / "dist"


def _reload_env(env_file: Path | None) -> None:
    if env_file is None or not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv ships with openjiuwen
        return
    # No ${VAR} interpolation: a value is taken literally, never filled from another secret.
    load_dotenv(env_file, override=True, interpolate=False)


def build_config(state: AppState) -> TycheConfig:
    """Reload ``.env`` and rebuild the config fresh, so edits (from the settings endpoint or by
    hand) take effect on the next request without restarting the server."""
    _reload_env(state.env_file)
    overrides: list[str | dict[str, Any]] = [*state.overrides, {"workspace": {"root": str(state.workspace_root)}}]
    return TycheConfig.load(state.config_path, overrides)


def _require_run_dir(state: AppState, run_id: str) -> Path:
    # Run ids from the CLI may use capitals, dots and underscores, but never a path.
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ApiError(404, "run_not_found", f"no run named {run_id!r}")
    run_dir = web_runs.run_dir_of(state.workspace_root, run_id)
    if not (run_dir / "state.json").exists():
        raise ApiError(404, "run_not_found", f"no run named {run_id!r}")
    return run_dir


def _process_lookup(state: AppState):
    def lookup(run_id: str) -> dict[str, Any] | None:
        return state.registry.live_process(run_id)

    return lookup


def _safe_join(root: Path, rel: str) -> Path | None:
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        return None
    return candidate


def _guess_media_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".md": "text/markdown",
        ".bib": "text/plain",
        ".tex": "text/plain",
        ".pdf": "application/pdf",
    }.get(path.suffix.lower(), "application/octet-stream")


def _direction_meta(name: str) -> dict[str, Any]:
    data = load_direction(name)
    return {
        "name": data.get("name", name),
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
        "experiment_families": data.get("experiment_families", []),
        "angle_hints": data.get("angle_hints", []),
    }


# -- pydantic request bodies --------------------------------------------------


class ModelOverrides(BaseModel):
    model_name: str | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    reviewer_model: str | None = None


class SettingsOverrides(BaseModel):
    review_max_rounds: int | None = None
    max_main_pages: int | None = None


class RunCreateBody(BaseModel):
    topic: str
    direction: str
    notes: str = ""
    run_id: str | None = None
    stop_after: str | None = None
    engine: str | None = None
    results_dir: str | None = None
    model: ModelOverrides = ModelOverrides()
    settings: SettingsOverrides = SettingsOverrides()


class ResumeBody(BaseModel):
    stage: str | None = None
    from_stage: str | None = None
    stop_after: str | None = None
    allow_gate_failures: bool = False
    notes: str | None = None


class MessageBody(BaseModel):
    text: str


class PatchRunBody(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


class EnvSettingsBody(BaseModel):
    values: dict[str, str] = {}
    secrets: dict[str, str] = {}


# -- security middleware ---------------------------------------------------


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_TOKEN_COOKIE = "tyche_token"


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8", "replace"), b.encode("utf-8", "replace"))


class HostOriginGuard(BaseHTTPMiddleware):
    """Blocks DNS rebinding: rejects an unrecognized ``Host``, and (for state-changing requests)
    an ``Origin`` that is not this server's own origin.

    With a ``token`` (a server bound beyond loopback), every request must carry it instead: the
    printed ``?token=`` URL is exchanged once for an HttpOnly, SameSite=Strict cookie, which a
    rebinding or cross-site page never receives. Any ``Host`` is then accepted.
    """

    def __init__(self, app, *, allowed_host: str, port: int, token: str | None = None):
        super().__init__(app)
        self.allowed_hosts = {*LOOPBACK_HOSTS, allowed_host.strip("[]")}
        self.port = port
        self.token = token

    def _authorized(self, request: Request) -> bool:
        assert self.token is not None
        header = request.headers.get("authorization", "")
        bearer = header[7:] if header.lower().startswith("bearer ") else ""
        return _same(request.cookies.get(_TOKEN_COOKIE, ""), self.token) or _same(bearer, self.token)

    async def dispatch(self, request: Request, call_next):
        host_header = request.headers.get("host", "")
        hostname = host_header.rsplit(":", 1)[0].strip("[]") if host_header else ""
        allowed = set(self.allowed_hosts)
        if self.token is not None:
            supplied = request.query_params.get("token")
            if supplied is not None and _same(supplied, self.token):
                response = RedirectResponse(url=str(request.url.remove_query_params("token")), status_code=303)
                response.set_cookie(_TOKEN_COOKIE, self.token, httponly=True, samesite="strict")
                return response
            if not self._authorized(request):
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "unauthorized", "message": "open the ?token= URL printed by tyche ui"}},
                )
            allowed.add(hostname)
        elif hostname not in allowed:
            return JSONResponse(status_code=403, content={"error": {"code": "forbidden_host", "message": "host not allowed"}})
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin:
                parsed = urlparse(origin)
                origin_host = (parsed.hostname or "").strip("[]")
                if origin_host not in allowed or parsed.port != self.port:
                    return JSONResponse(
                        status_code=403, content={"error": {"code": "forbidden_origin", "message": "origin not allowed"}}
                    )
        return await call_next(request)


# -- app factory ---------------------------------------------------------


def create_app(
    workspace_root: Path,
    *,
    config_path: str | None = None,
    overrides: list[str] | None = None,
    env_file: Path | None = None,
    static_dir: Path | None = None,
    launcher: LauncherProtocol | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
) -> FastAPI:
    workspace_root = Path(workspace_root).expanduser().resolve()
    registry = ProcessRegistry(workspace_root)
    resolved_static = Path(static_dir).expanduser().resolve() if static_dir is not None else _default_static_dir()
    state = AppState(
        workspace_root=workspace_root,
        config_path=config_path,
        overrides=list(overrides or []),
        env_file=Path(env_file).expanduser().resolve() if env_file is not None else None,
        static_dir=resolved_static,
        launcher=launcher or Launcher(registry),
        registry=registry,
        server_cwd=Path.cwd(),
        host=host,
        port=port,
    )
    app = FastAPI(title="Tyche", version=__version__)
    app.state.tyche = state
    if token is None and host.strip("[]") not in LOOPBACK_HOSTS:
        raise ValueError("a server bound beyond loopback needs an access token")
    app.add_middleware(HostOriginGuard, allowed_host=host, port=port, token=token)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            body = {"error": detail}
        else:
            body = {"error": {"code": "http_error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(exc)}})

    _register_routes(app, state)
    return app


def serve(
    workspace_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    config_path: str | None = None,
    overrides: list[str] | None = None,
    env_file: Path | None = None,
    static_dir: Path | None = None,
    open_browser: bool = True,
    token: str | None = None,
) -> None:
    app = create_app(
        workspace_root,
        config_path=config_path,
        overrides=overrides,
        env_file=env_file,
        static_dir=static_dir,
        host=host,
        port=port,
        token=token,
    )
    if open_browser:
        import webbrowser

        local = host if host.strip("[]") in LOOPBACK_HOSTS else "127.0.0.1"
        webbrowser.open(f"http://{local}:{port}/" + (f"?token={token}" if token else ""))
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


# -- routes ---------------------------------------------------------------


def _register_routes(app: FastAPI, state: AppState) -> None:
    # -- meta / models --------------------------------------------------
    @app.get("/api/meta")
    def get_meta() -> dict[str, Any]:
        cfg = build_config(state)
        writer = cfg.model("writer")
        roles = {role: cfg.model(role).public_dict() for role in ("planner", "writer", "reviewer", "experiments", "subject")}
        return {
            "version": __version__,
            "workspace": str(state.workspace_root),
            "env_file": str(state.env_file) if state.env_file is not None else None,
            "stages": list(STAGES),
            "directions": [_direction_meta(name) for name in DIRECTIONS],
            "defaults": {
                "engine": cfg.get("experiments.engine"),
                "review_max_rounds": cfg.get("review.max_rounds"),
                "max_main_pages": cfg.get("paper.max_main_pages"),
            },
            "roles": roles,
            "model": {
                "model_name": writer.model_name,
                "provider": writer.provider,
                "api_base": writer.api_base,
                "context_window": writer.context_window,
                "max_tokens": writer.max_tokens,
                "timeout": writer.timeout,
                "reasoning_effort": (writer.extra_body or {}).get("reasoning_effort"),
            },
            "keys": read_key_presence(os.environ),
            "env": read_values(os.environ),
            "reasoning_levels": list(REASONING_LEVELS),
        }

    @app.get("/api/models")
    async def get_models() -> dict[str, Any]:
        cfg = build_config(state)
        writer = cfg.model("writer")
        cache_key = writer.api_base
        now = time.monotonic()
        cached = state.models_cache.get(cache_key)
        # A model list is kept five minutes; a failed lookup only briefly, so a fixed key shows up soon.
        if cached is not None and now - cached[0] < (30 if "error" in cached[1] else 300):
            return cached[1]
        api_key = writer.api_key()
        fallback = {
            "models": [
                {
                    "id": writer.model_name,
                    "context_length": writer.context_window,
                    "max_completion_tokens": writer.max_tokens,
                    "owned_by": writer.provider,
                }
            ],
            "source": "config",
            "error": None,
        }
        result = fallback
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    writer.api_base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"}
                )
                resp.raise_for_status()
                data = resp.json()
            models = []
            for item in data.get("data") or data.get("models") or []:
                model_id = item.get("id") or item.get("name")
                if not model_id or any(bad in model_id.lower() for bad in _BAD_MODEL_WORDS):
                    continue
                models.append(
                    {
                        "id": model_id,
                        "context_length": item.get("context_length"),
                        "max_completion_tokens": item.get("max_completion_tokens"),
                        "owned_by": item.get("owned_by"),
                    }
                )
            models.sort(key=lambda m: m["id"])
            result = {"models": models, "source": "endpoint", "error": None}
        except Exception as exc:  # noqa: BLE001 - report any failure, never the key
            message = str(exc)
            if api_key:
                message = message.replace(api_key, "***")
            result = {**fallback, "error": f"{type(exc).__name__}: {message}"[:300]}
        state.models_cache[cache_key] = (now, result)
        return result

    # -- runs: list/detail ----------------------------------------------
    @app.get("/api/runs")
    def list_runs(archived: bool = False) -> dict[str, Any]:
        return {"runs": web_runs.list_runs(state.workspace_root, archived=archived, process_lookup=_process_lookup(state))}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        ui_meta = web_runs.load_ui_meta(state.workspace_root).get(run_id, {})
        process = state.registry.live_process(run_id)
        return web_runs.run_detail(run_id, run_dir, ui_meta=ui_meta, process=process)

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: str, since: int = 0, limit: int = 500) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        return web_runs.events_page(run_dir, since=since, limit=limit)

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str, request: Request, since: int | None = None):
        run_dir = _require_run_dir(state, run_id)
        return StreamingResponse(
            sse_lines(_run_event_stream(state, request, run_id, run_dir, since)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/references")
    def get_references(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        result = web_runs.references_detail(run_dir)
        if result is None:
            raise ApiError(404, "no_references", "no source manifest yet")
        return result

    @app.get("/api/runs/{run_id}/experiments")
    def get_experiments(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        run_state = read_json(run_dir / "state.json", {})
        return web_runs.experiments_detail(run_dir, run_state)

    @app.get("/api/runs/{run_id}/experiments/file")
    def get_experiment_file(run_id: str, path: str) -> PlainTextResponse:
        run_dir = _require_run_dir(state, run_id)
        root = web_runs.experiment_files_root(run_dir)
        if root is None:
            raise ApiError(404, "no_files", "no generated code for this run")
        target = _safe_join(root, path)
        if target is None:
            raise ApiError(400, "invalid_path", "path escapes the file root")
        if not target.is_file():
            raise ApiError(404, "not_found", "file not found")
        if target.stat().st_size > 1024 * 1024:
            raise ApiError(413, "too_large", "file exceeds 1 MB")
        return PlainTextResponse(target.read_text(encoding="utf-8", errors="replace"), media_type="text/plain; charset=utf-8")

    @app.get("/api/runs/{run_id}/analysis")
    def get_analysis(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        result = web_runs.analysis_detail(run_id, run_dir)
        if result is None:
            raise ApiError(404, "no_analysis", "no analysis yet")
        return result

    @app.get("/api/runs/{run_id}/ledger")
    def get_ledger(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        result = web_runs.ledger_detail(run_dir)
        if result is None:
            raise ApiError(404, "no_ledger", "no ledger yet")
        return result

    @app.get("/api/runs/{run_id}/report")
    def get_report(run_id: str) -> PlainTextResponse:
        run_dir = _require_run_dir(state, run_id)
        text = web_runs.report_text(run_dir)
        if text is None:
            raise ApiError(404, "no_report", "run has not been packaged")
        return PlainTextResponse(text, media_type="text/markdown")

    # -- traceability (tyche.trace): computed from the run directory on request --------
    @app.get("/api/runs/{run_id}/claims")
    def get_claims(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        result = claim_map_for_run(run_dir)
        if result is None:
            raise ApiError(404, "no_paper", "the run has no paper text yet")
        return result

    @app.get("/api/runs/{run_id}/revisions")
    def get_revisions(run_id: str) -> dict[str, Any]:
        return revision_history(_require_run_dir(state, run_id))

    @app.get("/api/runs/{run_id}/lineage")
    def get_lineage(run_id: str) -> dict[str, Any]:
        return lineage_graph(_require_run_dir(state, run_id))

    @app.get("/api/runs/{run_id}/environment")
    def get_environment(run_id: str) -> dict[str, Any]:
        path = _require_run_dir(state, run_id) / "package" / "environment.json"
        if not path.is_file():
            raise ApiError(404, "no_environment", "the environment is recorded when the paper is packaged")
        return read_json(path)

    @app.get("/api/runs/{run_id}/agents")
    def get_agents(run_id: str) -> dict[str, Any]:
        return web_runs.agent_sessions(_require_run_dir(state, run_id))

    @app.get("/api/runs/{run_id}/agents/{stage}/{name}")
    def get_agent_transcript(run_id: str, stage: str, name: str) -> dict[str, Any]:
        transcript = web_runs.agent_transcript(_require_run_dir(state, run_id), stage, name)
        if transcript is None:
            raise ApiError(404, "no_transcript", f"no agent transcript {stage}/{name}")
        return transcript

    @app.get("/api/runs/{run_id}/messages")
    def get_messages(run_id: str) -> dict[str, Any]:
        return {"messages": list_messages(_require_run_dir(state, run_id))}

    @app.post("/api/runs/{run_id}/messages", status_code=201)
    def post_run_message(run_id: str, body: MessageBody) -> dict[str, Any]:
        # Only the inbox file is written, which the pipeline only reads, so no run lock is needed.
        try:
            record = post_message(_require_run_dir(state, run_id), body.text)
        except ValueError as exc:
            raise ApiError(422, "invalid_message", str(exc)) from exc
        return {"message": {**record, "status": "queued", "delivered": None}}

    @app.get("/api/runs/{run_id}/log")
    def get_log(run_id: str, tail: int = 400) -> dict[str, Any]:
        _require_run_dir(state, run_id)
        return web_runs.log_tail(state.workspace_root, run_id, tail=tail)

    @app.get("/api/runs/{run_id}/artifacts")
    def get_artifacts(run_id: str) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        return web_runs.artifacts_listing(run_dir)

    @app.get("/api/runs/{run_id}/artifacts/{name}/{version}")
    def get_artifact(run_id: str, name: str, version: int, path: str | None = None):
        run_dir = _require_run_dir(state, run_id)
        rec = web_runs.artifact_record(run_dir, name, version)
        if rec is None:
            raise ApiError(404, "artifact_not_found", "no such artifact version")
        target = run_dir / rec["path"]
        if target.is_dir():
            if path is not None:
                file_path = _safe_join(target, path)
                if file_path is None:
                    raise ApiError(400, "invalid_path", "path escapes the artifact directory")
                if not file_path.is_file():
                    raise ApiError(404, "not_found", "file not found")
                return FileResponse(file_path, media_type=_guess_media_type(file_path))
            files = [
                {"path": str(p.relative_to(target)), "size": p.stat().st_size} for p in sorted(target.rglob("*")) if p.is_file()
            ]
            return {"files": files}
        if not target.exists():
            raise ApiError(404, "artifact_not_found", "artifact file missing on disk")
        return FileResponse(target, media_type=_guess_media_type(target))

    # -- files ------------------------------------------------------------
    @app.get("/api/runs/{run_id}/files/paper.pdf")
    def get_paper_pdf(run_id: str):
        run_dir = _require_run_dir(state, run_id)
        pdf_path = _resolve_paper_pdf(run_dir)
        if pdf_path is None:
            raise ApiError(404, "paper_not_found", "no paper pdf for this run")
        return FileResponse(
            pdf_path, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{run_id}.pdf"'}
        )

    @app.get("/api/runs/{run_id}/files/paper-thumb.png")
    def get_paper_thumb(run_id: str):
        run_dir = _require_run_dir(state, run_id)
        pdf_path = _resolve_paper_pdf(run_dir)
        if pdf_path is None:
            raise ApiError(404, "paper_not_found", "no paper pdf for this run")
        return _render_pdf_page(state.workspace_root, pdf_path, scale=480)

    @app.get("/api/runs/{run_id}/files/figure.png")
    def get_figure(run_id: str):
        run_dir = _require_run_dir(state, run_id)
        fig_path = web_runs.latest_artifact_path(run_dir, "fig_results")
        if fig_path is None:
            raise ApiError(404, "figure_not_found", "no results figure for this run")
        return _render_pdf_page(state.workspace_root, fig_path, scale=1200)

    @app.get("/api/runs/{run_id}/files/bundle.zip")
    def get_bundle(run_id: str):
        run_dir = _require_run_dir(state, run_id)
        package_dir = run_dir / "package"
        if not package_dir.is_dir():
            raise ApiError(404, "not_packaged", "run has not been packaged")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(package_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(package_dir)))
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}-package.zip"'},
        )

    # -- run lifecycle ------------------------------------------------------
    @app.post("/api/runs", status_code=202)
    def create_run(body: RunCreateBody) -> JSONResponse:
        return _create_run(state, body)

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str, body: ResumeBody) -> JSONResponse:
        _require_run_dir(state, run_id)
        with state.run_lock(run_id):
            return _resume_run(state, run_id, body)

    def _resume_run(state: AppState, run_id: str, body: ResumeBody) -> JSONResponse:
        if state.registry.live_process(run_id) is not None:
            raise ApiError(409, "already_running", f"run {run_id!r} is already running")
        for name in ("stage", "from_stage", "stop_after"):
            value = getattr(body, name)
            if value is not None and value not in STAGES:
                raise ApiError(422, "invalid_stage", f"{name} must be a known stage")
        if body.stage and body.from_stage:
            raise ApiError(422, "invalid_stage", "use either stage or from_stage, not both")
        if body.notes is not None and body.notes.strip() and "plan" not in (body.stage, body.from_stage):
            raise ApiError(422, "notes_need_replan", "notes only take effect when the plan is redone (from_stage=plan)")
        # A resumed run keeps the configuration it was started with; the server's own
        # --config/--set would silently replace it, so they are not passed here.
        argv = [sys.executable, "-m", "tyche", "run", "--resume", "--run-id", run_id, "--workspace", str(state.workspace_root)]
        if body.stage:
            argv += ["--stage", body.stage]
        if body.from_stage:
            argv += ["--from-stage", body.from_stage]
        if body.notes is not None and body.notes.strip():
            if len(body.notes) > 20000:
                raise ApiError(422, "invalid_notes", "notes must be at most 20000 characters")
            notes_path = state.workspace_root / ".tyche-web" / "notes" / f"{run_id}.md"
            notes_path.parent.mkdir(parents=True, exist_ok=True)
            notes_path.write_text(body.notes, encoding="utf-8")
            argv += ["--notes", str(notes_path)]
        if body.stop_after:
            argv += ["--stop-after", body.stop_after]
        if body.allow_gate_failures:
            argv += ["--allow-gate-failures"]
        process = state.launcher.spawn(argv, cwd=state.server_cwd, log_path=_log_path(state, run_id), run_id=run_id)
        return JSONResponse(status_code=202, content={"run_id": run_id, "process": process})

    @app.post("/api/runs/{run_id}/stop", status_code=202)
    def stop_run(run_id: str) -> JSONResponse:
        _require_run_dir(state, run_id)
        process = state.registry.live_process(run_id)
        if process is None:
            raise ApiError(409, "not_running", f"run {run_id!r} is not running")
        state.launcher.stop(run_id, process)
        return JSONResponse(status_code=202, content={"stopping": True})

    @app.patch("/api/runs/{run_id}")
    def patch_run(run_id: str, body: PatchRunBody) -> dict[str, Any]:
        run_dir = _require_run_dir(state, run_id)
        if body.title is not None and len(body.title) > 200:
            raise ApiError(422, "title_too_long", "title must be at most 200 characters")
        values: dict[str, Any] = {}
        if body.title is not None:
            values["title"] = body.title if body.title.strip() else None
        if body.pinned is not None:
            values["pinned"] = body.pinned
        if body.archived is not None:
            values["archived"] = body.archived
        web_runs.update_ui_meta(state.workspace_root, run_id, **values)
        ui_meta = web_runs.load_ui_meta(state.workspace_root).get(run_id, {})
        process = state.registry.live_process(run_id)
        return web_runs.run_summary(run_id, run_dir, ui_meta=ui_meta, process=process)

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict[str, Any]:
        _require_run_dir(state, run_id)
        with state.run_lock(run_id):
            if state.registry.live_process(run_id) is not None:
                raise ApiError(409, "running", f"run {run_id!r} is running; stop it first")
            trashed = web_runs.trash_run(state.workspace_root, run_id)
        return {"trashed": trashed}

    # -- library / lessons / doctor / settings -------------------------------
    @app.get("/api/library")
    def get_library() -> dict[str, Any]:
        return {"papers": web_runs.library_papers(state.workspace_root)}

    @app.get("/api/lessons")
    def get_lessons() -> dict[str, Any]:
        return {"lessons": web_runs.lessons_list(state.workspace_root)}

    @app.get("/api/doctor")
    async def get_doctor() -> dict[str, Any]:
        return await _doctor(state)

    @app.put("/api/settings/env")
    def put_settings(body: EnvSettingsBody) -> dict[str, Any]:
        unknown_values = set(body.values) - set(VALUE_KEYS)
        unknown_secrets = set(body.secrets) - set(SECRET_KEYS)
        if unknown_values or unknown_secrets:
            raise ApiError(422, "unknown_setting", f"unknown key(s): {sorted(unknown_values | unknown_secrets)}")
        env_path = state.env_file if state.env_file is not None else state.server_cwd / ".env"
        try:
            updates = apply_env_updates(env_path, values=body.values, secrets=body.secrets)
        except SettingsError as exc:
            raise ApiError(422, "invalid_setting", str(exc)) from exc
        os.environ.update(updates)
        return get_meta()

    # -- static frontend + SPA fallback --------------------------------------
    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> Any:
        if full_path.startswith("api/") or full_path == "api":
            raise ApiError(404, "not_found", "unknown API route")
        return _serve_static(state, full_path)


# -- run creation -------------------------------------------------------


def _log_path(state: AppState, run_id: str) -> Path:
    return state.workspace_root / ".tyche-web" / "logs" / f"{run_id}.log"


def _server_config_flags(state: AppState) -> list[str]:
    flags: list[str] = []
    if state.config_path:
        flags += ["--config", state.config_path]
    for expr in state.overrides:
        flags += ["--set", expr]
    return flags


def _create_run(state: AppState, body: RunCreateBody) -> JSONResponse:
    if body.run_id is not None and _RUN_ID_RE.fullmatch(body.run_id):
        with state.run_lock(body.run_id):
            return _create_run_locked(state, body)
    return _create_run_locked(state, body)


def _create_run_locked(state: AppState, body: RunCreateBody) -> JSONResponse:
    from tyche.textutil import slugify

    cfg = build_config(state)
    topic = body.topic.strip()
    if not (3 <= len(topic) <= 2000):
        raise ApiError(422, "invalid_topic", "topic must be 3..2000 characters after stripping")
    if body.direction not in DIRECTIONS:
        raise ApiError(422, "invalid_direction", f"direction must be one of {', '.join(DIRECTIONS)}")
    if body.run_id is not None:
        if not _RUN_ID_RE.fullmatch(body.run_id):
            raise ApiError(422, "invalid_run_id", "run_id must match ^[a-z0-9][a-z0-9-]{2,63}$")
        run_id = body.run_id
    else:
        run_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{slugify(topic, 32)}"
    run_dir = web_runs.run_dir_of(state.workspace_root, run_id)
    if (run_dir / "state.json").exists() or state.registry.live_process(run_id) is not None:
        raise ApiError(409, "run_exists", f"run {run_id!r} already exists")
    if body.stop_after is not None and body.stop_after not in STAGES:
        raise ApiError(422, "invalid_stage", "stop_after must be a known stage")
    if body.engine is not None and body.engine not in _ENGINES:
        raise ApiError(422, "invalid_engine", f"engine must be one of {', '.join(_ENGINES)}")
    if body.engine == "imported" and not body.results_dir:
        raise ApiError(422, "results_dir_required", "results_dir is required when engine=imported")
    results_dir: Path | None = None
    if body.results_dir is not None:
        results_dir = Path(body.results_dir).expanduser().resolve()
        if not results_dir.is_dir():
            raise ApiError(422, "invalid_results_dir", "results_dir must be an existing directory")
    for label, name in (("model_name", body.model.model_name), ("reviewer_model", body.model.reviewer_model)):
        if name and not _MODEL_NAME_RE.fullmatch(name):
            raise ApiError(422, f"invalid_{label}", f"{label} may use letters, digits and . _ : / @ + - only")
    if body.model.reasoning_effort is not None and body.model.reasoning_effort not in REASONING_LEVELS:
        raise ApiError(422, "invalid_reasoning_effort", f"reasoning_effort must be one of {', '.join(REASONING_LEVELS)}")
    max_main_pages = body.settings.max_main_pages
    if max_main_pages is not None and not (1 <= max_main_pages <= 9):
        raise ApiError(422, "invalid_max_main_pages", "max_main_pages must be between 1 and 9")
    review_max_rounds = body.settings.review_max_rounds
    if review_max_rounds is not None and not (0 <= review_max_rounds <= 10):
        raise ApiError(422, "invalid_review_max_rounds", "review_max_rounds must be between 0 and 10")

    argv = [
        sys.executable,
        "-m",
        "tyche",
        "run",
        "--workspace",
        str(state.workspace_root),
        "--run-id",
        run_id,
        f"--topic={topic}",
        "--direction",
        body.direction,
    ]
    argv += _server_config_flags(state)
    if body.notes.strip():
        notes_path = state.workspace_root / ".tyche-web" / "notes" / f"{run_id}.md"
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text(body.notes, encoding="utf-8")
        argv += ["--notes", str(notes_path)]
    if body.stop_after:
        argv += ["--stop-after", body.stop_after]
    if body.engine:
        argv += ["--engine", body.engine]
    if results_dir is not None:
        argv += ["--results-dir", str(results_dir)]
    if body.model.model_name:
        argv += ["--set", f"models.default.model_name={json.dumps(body.model.model_name)}"]
    if body.model.reasoning_effort is not None:
        extra_body = dict(cfg.get("models.default.extra_body") or {})
        extra_body["reasoning_effort"] = body.model.reasoning_effort
        argv += ["--set", f"models.default.extra_body={json.dumps(extra_body)}"]
    if body.model.max_tokens is not None:
        argv += ["--set", f"models.default.max_tokens={body.model.max_tokens}"]
    if body.model.timeout is not None:
        argv += ["--set", f"models.default.timeout={body.model.timeout}"]
    if body.model.reviewer_model:
        argv += ["--set", f"models.reviewer.model_name={json.dumps(body.model.reviewer_model)}"]
    if review_max_rounds is not None:
        argv += ["--set", f"review.max_rounds={review_max_rounds}"]
    if max_main_pages is not None:
        argv += ["--set", f"paper.max_main_pages={max_main_pages}"]

    process = state.launcher.spawn(argv, cwd=state.server_cwd, log_path=_log_path(state, run_id), run_id=run_id)
    return JSONResponse(status_code=202, content={"run_id": run_id, "process": process})


# -- pdf/figure rendering -------------------------------------------------


def _resolve_paper_pdf(run_dir: Path) -> Path | None:
    package = run_dir / "package"
    for name in ("paper.pdf", "paper_UNVERIFIED.pdf"):
        candidate = package / name
        if candidate.exists():
            return candidate
    return web_runs.latest_artifact_path(run_dir, "paper_pdf")


def _render_pdf_page(workspace_root: Path, pdf_path: Path, *, scale: int):
    if shutil.which("pdftoppm") is None:
        raise ApiError(503, "pdftoppm_missing", "pdftoppm is not installed")
    digest = sha256_file(pdf_path)
    cache_dir = workspace_root / ".tyche-web" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_png = cache_dir / f"{digest}.png"
    if not out_png.exists():
        prefix = cache_dir / digest
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-f", "1", "-l", "1", "-scale-to", str(scale), str(pdf_path), str(prefix)],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ApiError(500, "thumb_failed", f"pdftoppm failed: {exc}") from exc
        produced = sorted(cache_dir.glob(f"{digest}-*.png"))
        if produced:
            produced[0].rename(out_png)
    if not out_png.exists():
        raise ApiError(500, "thumb_failed", "pdftoppm produced no output")
    return FileResponse(out_png, media_type="image/png")


# -- doctor ---------------------------------------------------------------


async def _doctor(state: AppState) -> dict[str, Any]:
    from tyche.cli import _probe
    from tyche.paper.latex import latex_available

    cfg = build_config(state)
    tools = latex_available()
    tools["pdftoppm"] = shutil.which("pdftoppm")
    try:
        import openjiuwen  # noqa: F401

        openjiuwen_ok = True
    except Exception:  # noqa: BLE001
        openjiuwen_ok = False
    reference_docs = False
    try:
        from openjiuwen.rsi.artifact_rsi.paper_opt.auto_research.extensions.rails import (
            openjiuwen_reference_rail as ref,
        )

        reference_docs = ref._DEFAULT_ASSETS_ROOT.is_dir()
    except Exception:  # noqa: BLE001 - diagnostic only
        reference_docs = False
    writer = cfg.model("writer")
    profile = writer.cache_profile()
    probes = {
        "arXiv": "https://export.arxiv.org/api/query?search_query=all:agent&max_results=1",
        "Semantic Scholar": "https://api.semanticscholar.org/graph/v1/paper/search?query=agent&limit=1",
        "OpenAlex": "https://api.openalex.org/works?search=agent&per-page=1",
        "Crossref": "https://api.crossref.org/works?rows=1",
        "model endpoint": writer.api_base,
    }

    async def _one(name: str, url: str) -> tuple[str, str]:
        return name, await _probe(url)

    try:
        results = await asyncio.wait_for(asyncio.gather(*(_one(n, u) for n, u in probes.items())), timeout=20)
        sources = dict(results)
    except asyncio.TimeoutError:
        sources = {name: "UNREACHABLE (Timeout)" for name in probes}
    return {
        "tools": tools,
        "openjiuwen": openjiuwen_ok,
        "reference_docs": reference_docs,
        "keys": read_key_presence(os.environ),
        "roles": {
            "writer": {
                "model_name": writer.model_name,
                "api_base": writer.api_base,
                "cache_profile": profile.name,
                "cache_note": profile.note,
            }
        },
        "sources": sources,
    }


# -- static frontend --------------------------------------------------------


def _serve_static(state: AppState, full_path: str):
    static_dir = state.static_dir
    if static_dir is None or not static_dir.is_dir():
        return HTMLResponse(_NOT_BUILT_HTML)
    static_dir = static_dir.resolve()
    if full_path:
        candidate = (static_dir / full_path).resolve()
        try:
            candidate.relative_to(static_dir)
        except ValueError:
            candidate = None
        if candidate is not None and candidate.is_file():
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if full_path.startswith("assets/") else {}
            return FileResponse(candidate, headers=headers)
    index = static_dir / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(_NOT_BUILT_HTML)


# -- SSE stream -------------------------------------------------------------


async def sse_lines(stream: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """Serialize ``{"event", "data"}`` items as Server-Sent Events frames.

    SSE ends a line only at CR, LF or CRLF; ``str.splitlines`` would also split at U+2028 and
    other separators that JSON leaves unescaped, corrupting the payload.
    """
    async for item in stream:
        lines = str(item["data"]).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        data = "\n".join(f"data: {line}" for line in lines)
        yield f"event: {item['event']}\n{data}\n\n"


async def _run_event_stream(
    state: AppState, request: Request, run_id: str, run_dir: Path, since: int | None
) -> AsyncIterator[dict[str, Any]]:
    last_summary_key: tuple[Any, ...] | None = None
    last_seq = since if since is not None else web_runs.event_line_count(run_dir)
    exp_positions: dict[str, int] = {p.name: len(web_runs.manager_events(p)) for p in web_runs.attempt_dirs(run_dir)}
    last_ping = time.monotonic()
    while True:
        if await request.is_disconnected():
            return
        state_path = run_dir / "state.json"
        state_mtime = state_path.stat().st_mtime if state_path.exists() else None
        usage_path = run_dir / "usage.jsonl"
        usage_mtime = usage_path.stat().st_mtime if usage_path.exists() else None
        process = state.registry.live_process(run_id)
        key = (state_mtime, usage_mtime, json.dumps(process, sort_keys=True))
        if key != last_summary_key:
            ui_meta = web_runs.load_ui_meta(state.workspace_root).get(run_id, {})
            summary = web_runs.summary_with_stages(run_id, run_dir, ui_meta=ui_meta, process=process)
            yield {"event": "summary", "data": json.dumps(summary, ensure_ascii=False)}
            last_summary_key = key
        page = web_runs.events_page(run_dir, since=last_seq, limit=2000)
        for ev in page["events"]:
            yield {"event": "event", "data": json.dumps(ev, ensure_ascii=False)}
        last_seq = page["next"]
        for attempt_dir in web_runs.attempt_dirs(run_dir):
            events = web_runs.manager_events(attempt_dir)
            start = exp_positions.get(attempt_dir.name, 0)
            for ev in events[start:]:
                yield {
                    "event": "experiment",
                    "data": json.dumps(
                        {
                            "attempt": attempt_dir.name,
                            "ts": ev.get("ts"),
                            "event": ev.get("event"),
                            "module": ev.get("module"),
                            "round": ev.get("round"),
                            "outcome": ev.get("outcome"),
                        },
                        ensure_ascii=False,
                    ),
                }
            exp_positions[attempt_dir.name] = len(events)
        now = time.monotonic()
        if now - last_ping >= 15:
            yield {"event": "ping", "data": "{}"}
            last_ping = now
        await asyncio.sleep(1)
