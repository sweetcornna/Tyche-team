#!/usr/bin/env bash
# Install the openjiuwen (agent-core) reference docs next to the installed package.
#
# openjiuwen's experiment coding agent reads the SDK reference docs from <site-packages>/docs
# (agent-core's docs/ tree), which a pip install does not ship. This fetches exactly the pinned
# commit's docs/ from gitcode, or from the official GitHub mirror of the same commit.
#
# Usage: scripts/tyche/fetch_openjiuwen_docs.sh <python> <agent-core commit>
set -euo pipefail

PYTHON="$1"
PIN="$2"

# GNU timeout is not part of macOS; use coreutils' gtimeout there, or run unbounded.
with_timeout() {
  if command -v timeout >/dev/null; then timeout "$@"
  elif command -v gtimeout >/dev/null; then gtimeout "$@"
  else shift; "$@"
  fi
}

SITE="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
if [[ -d "$SITE/docs/en" ]]; then
  exit 0
fi
DOCS_TMP="$(mktemp -d -t tyche-agentcore-docs.XXXXXX)"
for REMOTE in https://gitcode.com/openJiuwen/agent-core.git https://github.com/openJiuwen-ai/agent-core.git; do
  if git -C "$DOCS_TMP" init -q 2>/dev/null \
    && git -C "$DOCS_TMP" remote add origin "$REMOTE" 2>/dev/null \
    && with_timeout 300 git -C "$DOCS_TMP" fetch -q --depth 1 --filter=blob:none origin "$PIN" \
    && git -C "$DOCS_TMP" sparse-checkout set docs \
    && git -C "$DOCS_TMP" checkout -q FETCH_HEAD; then
    rm -rf "$SITE/docs" && mv "$DOCS_TMP/docs" "$SITE/docs"
    echo "[tyche] installed openjiuwen reference docs ($PIN) from $REMOTE"
    break
  fi
  rm -rf "$DOCS_TMP" && DOCS_TMP="$(mktemp -d -t tyche-agentcore-docs.XXXXXX)"
done
rm -rf "$DOCS_TMP"
[[ -d "$SITE/docs/en" ]] || echo "[tyche] warning: could not fetch openjiuwen reference docs" >&2
