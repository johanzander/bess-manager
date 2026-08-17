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
# `bess-agent` alongside the repo owner today; `bess-developer` is added to
# that gate only in the same commit that renames the account.
#
# Usage:
#   scripts/request-pr-review.sh <pr-number> [timeout-seconds]
#
# Output (stdout, last line):
#   VERDICT <APPROVED|CHANGES_REQUESTED> <submittedAt-iso> <author>
#
# The author is reported rather than filtered on: any TERMINAL review newer than
# the trigger is a real signal, including one the maintainer submits by hand
# while the bot is still thinking. The caller decides what to do with it.
#
# `COMMENTED` is NOT terminal, and that distinction is the whole point of this
# loop. The review bot posts its inline notes first as a COMMENTED review whose
# body is literally "Inline notes below; summary review to follow.", then submits
# the real APPROVED/CHANGES_REQUESTED summary seconds later. Measured on PR #617:
# placeholder at 06:57:13Z, APPROVED at 06:58:03Z -- 50 seconds apart. Returning
# on the placeholder makes `implement-issue` Step 11 see a non-APPROVED verdict
# and skip `gh pr ready`, which is how PR #615 sat approved-but-draft overnight
# with nothing left to do but the merge. Wait for a state that decides something.
#
# Exit codes:
#   0  a terminal review landed; verdict on stdout
#   2  timed out waiting (recent PR Review runs dumped for diagnosis, plus any
#      non-terminal reviews seen -- "placeholder only" and "total silence" are
#      different faults and must not look alike)
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

    # Last TERMINAL review submitted after the trigger comment, if any.
    # Filtering on state before taking `last` is load-bearing: the bot's inline
    # notes arrive as a COMMENTED review first, so `last` unfiltered returns the
    # placeholder and the caller acts on a verdict that decides nothing.
    verdict=$(gh pr view "$pr" --json reviews \
        --jq "[.reviews[]
               | select(.submittedAt > \"${since}\")
               | select(.state == \"APPROVED\" or .state == \"CHANGES_REQUESTED\")]
              | last | select(. != null)
              | \"\(.state) \(.submittedAt) \(.author.login)\"")

    if [ -n "$verdict" ]; then
        echo "VERDICT ${verdict}"
        exit 0
    fi
done

echo "No terminal review landed within ${timeout}s." >&2

# Distinguish "the bot posted notes but never a summary" from "nothing ran at
# all". Both used to print the same message, and they need opposite responses:
# the first is a review that stalled mid-flight, the second is a trigger that
# never reached the workflow.
seen=$(gh pr view "$pr" --json reviews \
    --jq "[.reviews[] | select(.submittedAt > \"${since}\")]
          | map(\"\(.state) \(.submittedAt) \(.author.login)\") | join(\"; \")" 2>/dev/null)
if [ -n "$seen" ]; then
    echo "Non-terminal reviews seen since the trigger: ${seen}" >&2
    echo "The review started but never submitted a summary verdict." >&2
else
    echo "No reviews of any state landed since the trigger." >&2
fi

echo "Recent PR Review runs:" >&2
gh run list --workflow="PR Review" --limit 3 >&2
exit 2
