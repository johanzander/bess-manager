#!/usr/bin/env bash
#
# Fail unless a PR body links its issue (#828).
#
# The backlog board (`In Verification`), `advance-pr` and the release skill's
# issue-closing step all find a PR's issue through its body, so a PR that
# merges with no link leaves its issue open and unannounced (#765 fixed #763
# and said so nowhere). This gate accepts exactly what the board associates --
# it `include`s the board's own rule, scripts/lib/pr-linkage.jq -- plus an
# explicit `No issue: <reason>` line for chores, docs and CI changes.
#
# Usage: printf '%s' "$PR_BODY" | scripts/check-pr-linkage.sh
set -euo pipefail

jq_lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"

# The `No issue:` escape ignores HTML comments as well as code spans: the PR
# template lists the accepted spellings in a comment, and an invisible hint
# must not let an unfilled template pass. Work-verb refs are left exactly as the
# board's rule reads them, so the check can never disagree with the board.
linked=$(jq -R -s -L "$jq_lib" 'include "pr-linkage";
  ((linkage_refs | length) > 0)
  or (strip_code_spans
      | gsub("<!--(?:(?!-->)[\\s\\S])*-->"; "")
      | test("(?m)^[ \\t]*No issue:[ \\t]*\\S"))')

if [ "$linked" = "true" ]; then
  exit 0
fi

cat >&2 <<'EOF'
This PR body does not link an issue.

Add one of:
  Refs #<issue>             (or Part of / Tracks / tracking #<issue>)
  Closes #<issue>           (graduation PRs only: it closes the issue on merge)
  No issue: <reason>        (chores, docs and CI changes with no issue)

A `#N` inside backticks, or after "Related to" / "Blocked by" / "see", does
not count: the backlog board would not associate it either.
EOF
exit 1
