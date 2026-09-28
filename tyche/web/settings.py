"""``.env`` read (non-secret values plus presence booleans) and write, for the settings endpoint.

Secrets are never read back: the write path updates the file and ``os.environ`` but the read
path (used by ``/api/meta``) only ever reports whether a secret variable is set, never its value.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping

VALUE_KEYS = (
    "API_BASE",
    "MODEL_NAME",
    "MODEL_PROVIDER",
    "MODEL_CONTEXT_WINDOW",
    "TYCHE_PLANNER_MODEL_NAME",
    "TYCHE_WRITER_MODEL_NAME",
    "TYCHE_REVIEW_MODEL_NAME",
    "TYCHE_EXPERIMENT_MODEL_NAME",
    "TYCHE_SUBJECT_MODEL_NAME",
    "TYCHE_CONTACT_EMAIL",
)
SECRET_KEYS = ("API_KEY", "S2_API_KEY", "OPENALEX_API_KEY")


class SettingsError(ValueError):
    """A settings write was rejected: an unknown key, or a value that cannot be written literally."""


def read_values(env: Mapping[str, str]) -> dict[str, str]:
    return {key: str(env.get(key, "") or "") for key in VALUE_KEYS}


def read_key_presence(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in SECRET_KEYS}


def _check_single_line(key: str, value: str) -> None:
    if any(ch in value for ch in ("\n", "\r", "\0")):
        raise SettingsError(f"{key} must be a single line")
    # Values are written single-quoted, which dotenv and shells read literally; these cannot be.
    if any(ch in value for ch in ("'", "\\", "$", "`")):
        raise SettingsError(f"{key} may not contain quotes, backslashes, '$' or '`'")


def _quote(value: str) -> str:
    return f"'{value}'" if value else ""


def validate_updates(values: Mapping[str, str] | None, secrets: Mapping[str, str] | None) -> None:
    for key in values or {}:
        if key not in VALUE_KEYS:
            raise SettingsError(f"unknown setting key {key!r}")
    for key in secrets or {}:
        if key not in SECRET_KEYS:
            raise SettingsError(f"unknown secret key {key!r}")
    for key, value in {**(values or {}), **(secrets or {})}.items():
        _check_single_line(key, str(value))


def validate_model_updates(values: Mapping[str, str]) -> None:
    """Validate workbench inputs without changing the literal dotenv writer's contract."""
    for key, value in values.items():
        if value and (key == "MODEL_NAME" or key.endswith("_MODEL_NAME")):
            from tyche.web.models import MODEL_NAME_RE

            if not MODEL_NAME_RE.fullmatch(value):
                raise SettingsError(f"{key} must be a valid model identifier")
        if key == "MODEL_CONTEXT_WINDOW" and value and (not value.isdecimal() or int(value) < 1):
            raise SettingsError("MODEL_CONTEXT_WINDOW must be a positive integer")
        if key == "API_BASE" and value:
            from tyche.web.models import models_endpoint

            try:
                models_endpoint(value, "OpenAI")
            except ValueError as exc:
                raise SettingsError(str(exc)) from exc


def _parse_env_lines(text: str) -> list[tuple[str | None, str]]:
    """Each line as ``(key, raw_line)``; ``key`` is None for comments/blank/unparseable lines."""
    out: list[tuple[str | None, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append((None, line))
            continue
        key = stripped.split("=", 1)[0].strip()
        out.append((key, line))
    return out


def apply_env_updates(
    env_path: Path, *, values: Mapping[str, str] | None = None, secrets: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Write ``env_path`` in place: replace existing ``KEY=...`` lines, append missing keys,
    preserve comments and unrelated lines, write atomically, and chmod it 600.

    Returns the merged ``{key: value}`` of everything just written, so the caller can also apply
    it to ``os.environ``. A key omitted from ``values``/``secrets`` is left unchanged.
    """
    validate_updates(values, secrets)
    updates = {**(values or {}), **(secrets or {})}
    existing_text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = _parse_env_lines(existing_text)
    remaining = dict(updates)
    out_lines: list[str] = []
    for key, raw in lines:
        if key is not None and key in remaining:
            out_lines.append(f"{key}={_quote(remaining.pop(key))}")
        elif key is not None and key in updates:
            continue  # a later duplicate would win over the value just written
        else:
            out_lines.append(raw)
    for key, value in remaining.items():
        out_lines.append(f"{key}={_quote(value)}")
    text = "\n".join(out_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=env_path.parent, prefix=f".{env_path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, env_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return updates
