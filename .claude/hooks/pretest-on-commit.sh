#!/usr/bin/env bash
# PreToolUse hook for Bash: before a `git commit`, run the scenario-discovery
# test so a broken fixture is caught at commit time rather than in CI.
#
# Extracted from an inline `python3 -c` one-liner in settings.json, which had
# the same cwd-dependence that made the ruff hook fail: it invoked
# `.venv/bin/python` as a RELATIVE path, so it only worked when the session's
# cwd happened to be the repo root. Hooks run with whatever cwd the session
# has. Resolve from the project root instead.
set -uo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

case "$command" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
[ -n "$root" ] || exit 0

python="$root/.venv/bin/python"
if [ ! -x "$python" ]; then
  echo "python not found at $python -- run ./scripts/worktree-setup.sh (a fresh worktree has no .venv until it does)" >&2
  exit 2
fi

test_file="$root/core/bess/tests/unit/test_scenario_discovery.py"
[ -f "$test_file" ] || exit 0

cd "$root" || exit 0
exec "$python" -m pytest "$test_file" -q --tb=short
