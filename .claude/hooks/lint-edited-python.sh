#!/usr/bin/env bash
# PostToolUse hook for Edit/Write: ruff-check the file that was just written.
#
# This was an inline `python3 -c` one-liner in settings.json calling bare
# `ruff`. Two problems, both of which reached the user as a Python traceback
# printed after every single .py edit:
#
#   1. `ruff` is not on PATH in this project -- it lives in .venv/bin, which
#      is exactly what #562 fixed for scripts/quality-check.sh ("make
#      quality-check find venv tools and fail when it cannot"). The hook was
#      missed. subprocess.run(['ruff', ...]) then raised FileNotFoundError.
#   2. It linted ANY .py path, including scratch scripts under the session
#      scratchpad that are not project code and have no reason to be clean.
#
# Resolution does not depend on the session's cwd: hooks run with whatever
# cwd the session has, which is not reliably the repo root.
set -uo pipefail

input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')

case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
[ -n "$root" ] || exit 0

# Only lint files that belong to this checkout. A scratch script under the
# scratchpad or /tmp is not project code; linting it produced noise on every
# edit and could not be acted on.
case "$file" in
  "$root"/*) ;;
  *) exit 0 ;;
esac

ruff="$root/.venv/bin/ruff"
if [ ! -x "$ruff" ]; then
  # Loud and actionable, not a traceback, and not silent either -- a linter
  # that quietly stops running is the silent degradation rules.md forbids
  # and #562 removed elsewhere.
  echo "ruff not found at $ruff -- run ./scripts/worktree-setup.sh (a fresh worktree has no .venv until it does)" >&2
  exit 2
fi

exec "$ruff" check "$file"
