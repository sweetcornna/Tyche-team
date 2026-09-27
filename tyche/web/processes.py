"""Process registry and launcher for ``tyche run`` processes started by the web server.

Two sources tell whether a run has a live process: the registry this module keeps at
``<workspace>/.tyche-web/processes.json`` (pid, start time, source ``"web"`` for processes the
server itself spawned), and a `psutil` scan for any process whose command line looks like a
``tyche run --run-id <id> ...`` invocation (also matches processes started straight from the
CLI, source ``"cli"``). The scan is cached for a couple of seconds so listing many runs does not
rescan the whole process table once per run.

``Launcher`` is injectable (see ``create_app(..., launcher=...)``), so tests never spawn a real
``tyche run`` process.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any, Protocol

import psutil

from tyche.workspace import utcnow, write_json_atomic

_REGISTRY_REL = Path(".tyche-web") / "processes.json"
_SCAN_TTL_S = 2.0
_STOP_WAIT_S = 8.0


def _registry_path(workspace_root: Path) -> Path:
    return workspace_root / _REGISTRY_REL


def _load_registry(workspace_root: Path) -> dict[str, dict[str, Any]]:
    path = _registry_path(workspace_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_registry(workspace_root: Path, data: dict[str, dict[str, Any]]) -> None:
    write_json_atomic(_registry_path(workspace_root), data)


def _pid_alive(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    try:
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _cmdline(pid: int) -> list[str]:
    try:
        return psutil.Process(pid).cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def _matches_run(cmdline: list[str], run_id: str) -> bool:
    if not cmdline or "run" not in cmdline or not any("tyche" in part for part in cmdline):
        return False
    for i, part in enumerate(cmdline):
        if part == "--run-id" and i + 1 < len(cmdline) and cmdline[i + 1] == run_id:
            return True
    return False


def _is_session_leader(pid: int) -> bool:
    try:
        return os.getsid(pid) == pid
    except (ProcessLookupError, PermissionError, OSError):
        return False


_scan_cache: dict[Path, tuple[float, dict[str, dict[str, Any]]]] = {}


def scan_cli_processes(workspace_root: Path) -> dict[str, dict[str, Any]]:
    """``run_id -> {"pid", "started_at", "source": "cli"}`` from a live psutil scan."""
    now = time.monotonic()
    cached = _scan_cache.get(workspace_root)
    if cached is not None and now - cached[0] < _SCAN_TTL_S:
        return cached[1]
    found: dict[str, dict[str, Any]] = {}
    for proc in psutil.process_iter(["pid", "cmdline", "status", "create_time"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if info.get("status") == psutil.STATUS_ZOMBIE:
            continue
        cmdline = info.get("cmdline") or []
        if not cmdline or "run" not in cmdline or not any("tyche" in part for part in cmdline):
            continue
        for i, part in enumerate(cmdline):
            if part == "--run-id" and i + 1 < len(cmdline):
                run_id = cmdline[i + 1]
                started_at = None
                create_time = info.get("create_time")
                if create_time:
                    from datetime import datetime

                    started_at = datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat(timespec="seconds")
                found.setdefault(run_id, {"pid": info["pid"], "started_at": started_at, "source": "cli"})
    _scan_cache[workspace_root] = (now, found)
    return found


def clear_scan_cache() -> None:
    """Test hook: forget the cached psutil scan so the next lookup rescans immediately."""
    _scan_cache.clear()


class ProcessRegistry:
    """Processes the web server itself spawned, plus fallback detection of CLI-launched ones."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def register(self, run_id: str, pid: int, *, source: str = "web") -> dict[str, Any]:
        data = _load_registry(self.workspace_root)
        row = {"pid": pid, "started_at": utcnow(), "source": source}
        data[run_id] = row
        _save_registry(self.workspace_root, data)
        return row

    def forget(self, run_id: str) -> None:
        data = _load_registry(self.workspace_root)
        if data.pop(run_id, None) is not None:
            _save_registry(self.workspace_root, data)

    def live_process(self, run_id: str) -> dict[str, Any] | None:
        data = _load_registry(self.workspace_root)
        row = data.get(run_id)
        if row is not None:
            pid = row.get("pid")
            if isinstance(pid, int) and _pid_alive(pid) and _matches_run(_cmdline(pid), run_id):
                return {"pid": pid, "started_at": row.get("started_at"), "source": row.get("source", "web")}
            self.forget(run_id)
        cli = scan_cli_processes(self.workspace_root).get(run_id)
        if cli is not None and _pid_alive(cli["pid"]):
            return cli
        return None


class LauncherProtocol(Protocol):
    def spawn(self, argv: list[str], *, cwd: Path, log_path: Path, run_id: str) -> dict[str, Any]: ...

    def stop(self, run_id: str, process: dict[str, Any]) -> None: ...


@dataclass
class Launcher:
    """Spawns and stops ``tyche run`` (or ``python -m tyche run``) subprocesses."""

    registry: ProcessRegistry
    _threads: list[threading.Thread] = field(default_factory=list, repr=False)

    def spawn(self, argv: list[str], *, cwd: Path, log_path: Path, run_id: str) -> dict[str, Any]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"=== {utcnow()} launch: {' '.join(argv)} ===\n")
        log = log_path.open("a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=os.environ.copy(),
            )
        finally:
            log.close()
        return self.registry.register(run_id, proc.pid, source="web")

    def stop(self, run_id: str, process: dict[str, Any]) -> None:
        pid = int(process["pid"])
        source = process.get("source", "web")
        use_group = source == "web" or _is_session_leader(pid)

        def _signal(sig: int) -> None:
            try:
                if use_group:
                    os.killpg(os.getpgid(pid), sig)
                else:
                    os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

        def _run() -> None:
            _signal(signal.SIGTERM)
            deadline = time.monotonic() + _STOP_WAIT_S
            while time.monotonic() < deadline:
                if not _pid_alive(pid):
                    self.registry.forget(run_id)
                    return
                time.sleep(0.2)
            _signal(signal.SIGKILL)
            self.registry.forget(run_id)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        self._threads.append(thread)
