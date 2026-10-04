#!/usr/bin/env bash
#
# Read-only snapshot of one PR's merge-readiness: state, non-passing checks,
# inline review comments and review bodies.
#
# It exists as a script so the permission allowlist can name ONE fixed command
# (`Bash(scripts/pr-status.sh *)`) instead of opening `gh api *`, which stays an
# ask rule because `gh api` can also write (POST/PUT/PATCH/DELETE). Everything
# here is a GET; the only argument is a validated PR number, so nothing the
# caller passes can reach a mutating call.
#
# Usage:
#   scripts/pr-status.sh <pr-number> [since-iso8601]
#
# With since-iso8601 (a prior review's submittedAt), only inline comments created
# after it are listed, so a re-review round doesn't re-litigate addressed findings.
#
set -euo pipefail

pr="${1:-}"
if ! [[ "$pr" =~ ^[0-9]+$ ]]; then
  echo "usage: scripts/pr-status.sh <pr-number> [since-iso8601]" >&2
  exit 2
fi
since="${2:-}"
if [ -n "$since" ] && ! [[ "$since" =~ ^[0-9T:.Z+-]+$ ]]; then
  echo "since must be an ISO-8601 timestamp, got: $since" >&2
  exit 2
fi

echo "== state =="
gh pr view "$pr" --json isDraft,mergeable,mergeStateStatus,reviewDecision

echo "== non-passing checks =="
# grep -v exits 1 when every check passes; that is the good case, not an error.
gh pr checks "$pr" | grep -v pass || true

echo "== inline comments =="
gh api "repos/{owner}/{repo}/pulls/$pr/comments" \
  --jq ".[] | select(.created_at > \"$since\") | \"\(.path):\(.line) \(.body)\""

echo "== review bodies =="
gh pr view "$pr" --json reviews --jq '.reviews[] | .body'
