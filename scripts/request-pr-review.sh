#!/usr/bin/env bash
#
# Trigger the Stage 4 `@claude-bot` PR review and block until its verdict lands.
#
# Used by the `implement-issue` review loop (Step 11). It exists as a script,
# not inline in the skill, so the whole wait costs zero tokens: run it with
# run_in_background and you are notified once when it exits, instead of an
# agent re-reading the session context every poll.
#
# The trigger comment is posted as the developer automation identity (the
# default role in scripts/gh-agent.sh, currently the `bess-agent` GitHub
# account, being renamed to `bess-developer`). pr-review.yml's gate accepts
# both logins alongside the repo owner during the migration window.
#
# Usage:
#   scripts/request-pr-review.sh <pr-number> [timeout-seconds]
#
# Output (stdout, last line):
#   VERDICT <APPROVED|CHANGES_REQUESTED|COMMENTED> <submittedAt-iso> <author>
#
# The author is reported rather than filtered on: any review newer than the
# trigger is a real signal, including one the maintainer submits by hand while
# the bot is still thinking. The caller decides what to do with it.
#
# Exit codes:
#   0  a new review landed; verdict on stdout
#   2  timed out waiting (recent PR Review runs dumped for diagnosis)
#   1  usage/precondition error
set -euo pipefail

pr="${1:?usage: request-pr-review.sh <pr-number> [timeout-seconds]}"
timeout="${2:-900}"
interval=60

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# Reviews strictly newer than this are the ones this run triggered.
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "Requesting review on PR #${pr} (since ${since})"
scripts/gh-agent.sh pr comment "$pr" --body "@claude-bot review" >/dev/null

deadline=$(( $(date +%s) + timeout ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    # Never sleep past the deadline: a caller passing a timeout shorter than
    # the poll interval must still get its exit 2 on time.
    remaining=$(( deadline - $(date +%s) ))
    if [ "$remaining" -lt "$interval" ]; then
        sleep "$remaining"
    else
        sleep "$interval"
    fi

    # Last review submitted after the trigger comment, if any.
    verdict=$(gh pr view "$pr" --json reviews \
        --jq "[.reviews[] | select(.submittedAt > \"${since}\")] | last | select(. != null) | \"\(.state) \(.submittedAt) \(.author.login)\"")

    if [ -n "$verdict" ]; then
        echo "VERDICT ${verdict}"
        exit 0
    fi
done

echo "No review landed within ${timeout}s. Recent PR Review runs:" >&2
gh run list --workflow="PR Review" --limit 3 >&2
exit 2
