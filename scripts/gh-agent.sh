#!/usr/bin/env bash
#
# Run `gh` as a role-scoped automation identity instead of the maintainer.
#
# Use for AUTOMATION writes only: status comments, release PRs, CI plumbing,
# lifecycle "please test" asks. For genuine maintainer voice — answering issue
# authors, approving graduation to prod — use plain `gh` (posts as the human).
#
# Two roles, two identities:
#   --as po   BESS_PO_TOKEN     intake, backlog, board, reporter comments
#   --as dev  BESS_AGENT_TOKEN  analyze, fix, PR authorship, review requests
#
# `dev` still reads BESS_AGENT_TOKEN because the account is still named
# `bess-agent` — the rename to `bess-developer` has not happened. Switch this
# to BESS_DEVELOPER_TOKEN in the SAME commit that renames the account and adds
# that login to pr-review.yml's gate, never before: renaming the variable ahead
# of the account breaks scripts/request-pr-review.sh on every PR.
#
# Default role is `dev` (no `--as` given) so existing callers — currently only
# scripts/request-pr-review.sh — keep posting as the developer identity, which
# is what pr-review.yml's actor gate expects.
#
# Tokens are read from the main checkout's .env (resolved from any linked
# worktree), or from BESS_ENV_FILE when set — a seam tests use to point at a
# fixture .env instead.
#
# Usage:
#   scripts/gh-agent.sh --as po  issue comment 126 --repo johanzander/bess-manager --body "..."
#   scripts/gh-agent.sh --as dev pr comment 40 --repo johanzander/bess-manager-beta --body "CI green ✅"
#
set -euo pipefail

# Resolve the main worktree root (where the untracked .env lives) from any worktree.
common_dir=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
if [ -n "$common_dir" ]; then
  repo_root=$(dirname "$(cd "$common_dir" && pwd)")
else
  repo_root=$(pwd)
fi

# Role selection. Default `dev` keeps existing callers (request-pr-review.sh)
# posting as the developer identity, which is what pr-review.yml's gate expects.
role="dev"
if [ "${1:-}" = "--as" ]; then
  role="${2:?--as requires a role}"
  shift 2
fi

case "$role" in
  po)  token_var="BESS_PO_TOKEN" ;;
  dev) token_var="BESS_AGENT_TOKEN" ;;
  *)   echo "gh-agent.sh: unknown role '$role' (expected po or dev)" >&2; exit 2 ;;
esac

env_file="${BESS_ENV_FILE:-$repo_root/.env}"

if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

token="${!token_var:-}"
if [ -z "$token" ]; then
  echo "gh-agent.sh: ${token_var} is not set in ${env_file}" >&2
  exit 1
fi

GH_TOKEN="$token" exec gh "$@"
