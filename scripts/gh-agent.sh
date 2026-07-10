#!/usr/bin/env bash
#
# Run `gh` as the `bess-agent` automation identity instead of the maintainer.
#
# Use for AUTOMATION writes only: status comments, release PRs, CI plumbing,
# lifecycle "please test" asks. For genuine maintainer voice — answering issue
# authors, approving graduation to prod — use plain `gh` (posts as the human).
#
# The token (a `bess-agent` PAT) is read from BESS_AGENT_TOKEN in the main
# checkout's .env (resolved from any linked worktree).
#
# Usage:
#   scripts/gh-agent.sh pr comment 40 --repo johanzander/bess-manager-beta --body "CI green ✅"
#   scripts/gh-agent.sh issue comment 126 --repo johanzander/bess-manager --body "..."
#
set -euo pipefail

# Resolve the main worktree root (where the untracked .env lives) from any worktree.
common_dir=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
if [ -n "$common_dir" ]; then
  repo_root=$(dirname "$(cd "$common_dir" && pwd)")
else
  repo_root=$(pwd)
fi
env_file="$repo_root/.env"

if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

if [ -z "${BESS_AGENT_TOKEN:-}" ]; then
  echo "error: BESS_AGENT_TOKEN is empty. Add the bess-agent PAT to $env_file" >&2
  exit 1
fi

GH_TOKEN="$BESS_AGENT_TOKEN" exec gh "$@"
