"""Environment snapshot: which software and models produced a run, without any credential.

Captures the interpreter, platform, Tyche and openJiuwen versions (with the
agent-core commit pinned in ``pyproject.toml`` and the one actually
installed), the first version line of each TeX/poppler tool, the git state of
the source checkout, and each model role's public description. Nothing here
raises when a tool, the repository, or a distribution is missing; the field is
None instead. Environment variable values never appear: models are described
only by ``ModelSpec.public_dict()`` (which names the key variable, never its
value), and any secret-looking environment value that still reaches the output
(for example inside an endpoint URL) is redacted.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import tyche
from tyche.config import ConfigError, TycheConfig
from tyche.workspace import utcnow

MODEL_ROLES = ("planner", "writer", "reviewer", "experiments", "subject")
TOOL_VERSION_FLAGS = {"pdflatex": "--version", "bibtex": "--version", "latexmk": "-v", "pdftotext": "-v"}
TIMEOUT_SECONDS = 5
REDACTED = "[redacted]"
# Name segments of credential-holding variables: API_KEY, S2_API_KEY, HF_TOKEN, AWS_SECRET_ACCESS_KEY, ...
_SECRET_NAME = re.compile(r"(?:^|_)(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTH|COOKIE)(?:_|$)", re.I)
_PINNED = re.compile(r"openjiuwen\s*@\s*git\+[^\s\"']*?@([0-9a-fA-F]{7,40})")
_PINNED_REV = re.compile(r"^\s*openjiuwen\s*=\s*\{[^}\n]*\brev\s*=\s*\"([^\"]+)\"", re.M)


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            check=False,
            # A read-only git status must not take the index lock of a checkout other processes use.
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _first_line(text: str | None) -> str | None:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def tool_version(tool: str, flag: str) -> str | None:
    """First non-empty line a tool prints for its version flag (poppler prints to stderr)."""
    path = shutil.which(tool)
    if path is None:
        return None
    result = _run([path, flag])
    if result is None:
        return None
    return _first_line(result.stdout) or _first_line(result.stderr)


def _git_state(root: Path) -> dict[str, Any] | None:
    git = shutil.which("git")
    if git is None or not root.is_dir():
        return None
    head = _run([git, "-C", str(root), "rev-parse", "HEAD"])
    commit = _first_line(head.stdout) if head is not None and head.returncode == 0 else None
    if not commit or not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        return None
    branch_run = _run([git, "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"])
    branch = _first_line(branch_run.stdout) if branch_run is not None and branch_run.returncode == 0 else None
    status = _run([git, "-C", str(root), "status", "--porcelain"])
    dirty = bool(status.stdout.strip()) if status is not None and status.returncode == 0 else None
    return {"commit": commit, "branch": None if branch == "HEAD" else branch, "dirty": dirty}


def _openjiuwen(root: Path) -> dict[str, Any]:
    version = installed = None
    try:
        dist = metadata.distribution("openjiuwen")
        version = dist.version
        direct = dist.read_text("direct_url.json")
        if direct:
            installed = (json.loads(direct).get("vcs_info") or {}).get("commit_id")
    except (metadata.PackageNotFoundError, OSError, ValueError, AttributeError):
        pass
    pinned = None
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = _PINNED.search(text) or _PINNED_REV.search(text)
    if match:
        pinned = match.group(1)
    return {"version": version, "installed_commit": installed, "pinned_commit": pinned}


def _models(config: TycheConfig) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for role in MODEL_ROLES:
        try:
            out[role] = config.model(role).public_dict()
        except ConfigError:
            out[role] = None
    return out


def _secrets(config: TycheConfig | None) -> list[str]:
    values = {value for name, value in os.environ.items() if _SECRET_NAME.search(name)}
    if config is not None:
        for role in MODEL_ROLES:
            try:
                values.add(config.model(role).api_key())
            except ConfigError:
                continue
    # Very short values would redact ordinary words; they are not credentials anyway.
    return sorted((v for v in values if len(v) >= 6), key=len, reverse=True)


def _redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value


def capture_environment(*, config: TycheConfig | None = None, repo_root: Path | None = None) -> dict[str, Any]:
    """A JSON-ready description of the environment; ``repo_root`` defaults to Tyche's source checkout."""
    root = Path(repo_root) if repo_root is not None else Path(tyche.__file__).resolve().parents[1]
    snapshot = {
        "captured_at": utcnow(),
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "tyche": {"version": tyche.__version__},
        "openjiuwen": _openjiuwen(root),
        "tools": {tool: tool_version(tool, flag) for tool, flag in TOOL_VERSION_FLAGS.items()},
        "git": _git_state(root),
        "models": _models(config) if config is not None else None,
        "config_digest": config.digest() if config is not None else None,
    }
    return _redact(snapshot, _secrets(config))
