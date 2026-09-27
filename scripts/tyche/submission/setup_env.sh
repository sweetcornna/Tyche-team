#!/usr/bin/env bash
# Create the Python environment for this code snapshot from the locked requirements.
#
# requirements.txt pins every package, including openjiuwen (agent-core) and intelli-router
# (agent-protocol) at exact commits on gitcode.com. When gitcode is not reachable, the identical
# commits are installed from the official GitHub mirrors under github.com/openJiuwen-ai instead.
#
# Usage: ./setup_env.sh [--python 3.11] [--venv .venv]
set -euo pipefail

PYTHON_VERSION="3.11"
VENV_DIR=".venv"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON_VERSION="$2"; shift 2 ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }

with_timeout() {
  if command -v timeout >/dev/null; then timeout "$@"
  elif command -v gtimeout >/dev/null; then gtimeout "$@"
  else shift; "$@"
  fi
}

REQS="$(mktemp -t tyche-reqs.XXXXXX)"
trap 'rm -f "$REQS"' EXIT
cp requirements.txt "$REQS"
if with_timeout 20 git ls-remote https://gitcode.com/openJiuwen/agent-core.git HEAD >/dev/null 2>&1; then
  echo "[tyche] gitcode.com reachable; using the pins as-is"
else
  echo "[tyche] gitcode.com unreachable; using GitHub mirrors of the same commits"
  sed -i.bak \
    -e 's#git+https://gitcode.com/openJiuwen/agent-core.git@#git+https://github.com/openJiuwen-ai/agent-core.git@#' \
    -e 's#git+https://gitcode.com/openJiuwen/agent-protocol.git@#git+https://github.com/openJiuwen-ai/agent-protocol.git@#' \
    "$REQS"
  rm -f "$REQS.bak"
fi

[[ -d "$VENV_DIR" ]] || uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
export VIRTUAL_ENV="$HERE/$VENV_DIR"
export GIT_LFS_SKIP_SMUDGE=1
# The pins already list every transitive dependency; install them without re-resolving.
uv pip install --no-deps -r "$REQS"

PIN="$(grep -o 'agent-core.git@[0-9a-f]\{40\}' requirements.txt | head -1 | cut -d@ -f2)"
scripts/tyche/fetch_openjiuwen_docs.sh "$VENV_DIR/bin/python" "$PIN"
echo "[tyche] environment ready: source $VENV_DIR/bin/activate && python main.py selftest"
