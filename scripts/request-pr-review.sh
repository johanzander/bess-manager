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
#   VERDICT <APPROVED|CHANGES_REQUESTED|COMMENTED> <submittedAt-iso> <author>
#
# The author is reported rather than filtered on: any review newer than the
# trigger is a real signal, including one the maintainer submits by hand while
# the bot is still thinking. The caller decides what to do with it.
#
# THE COMMENTED PROBLEM. `pr-review.yml` gives the bot three final verdicts:
# APPROVE, REQUEST_CHANGES and COMMENT ("questions/observations only"). But the
# bot ALSO posts its inline notes as a separate review before the summary, and
# that one is `COMMENTED` too -- body "Inline notes below; summary review to
# follow.". So `COMMENTED` is ambiguous: either a placeholder that decides
# nothing, or a legitimate final verdict. The state alone cannot tell them apart.
#
# Getting this wrong in either direction has been observed:
#   - Treating COMMENTED as terminal returns the placeholder. Measured on #617
#     (06:57:13Z placeholder, 06:58:03Z APPROVED -- 50s) and #622 (08:48:58Z,
#     08:49:14Z -- 16s). `implement-issue` Step 11 then saw a non-APPROVED
#     verdict and skipped `gh pr ready`: that is how #615 sat approved-but-draft
#     overnight with only the merge left to do.
#   - Treating COMMENTED as never-terminal swallows a real COMMENT verdict. The
#     loop waits out the full timeout and reports "no summary landed", which is
#     false when a summary with findings is sitting on the PR.
#
# So COMMENTED is resolved by TIME, not by parsing its body. Body text is
# bot-generated prose with no contract behind it, and a grace window needs no
# agreement about wording. APPROVED/CHANGES_REQUESTED return immediately; a
# COMMENTED-only state is held for GRACE seconds to let a summary supersede it,
# and returned as the verdict if none does.
#
# `pr-review.yml` step 3 is also changed so inline notes post via `gh api`
# instead of `gh pr review`, which stops the placeholder being submitted as a
# review at all. That removes the ambiguity at its source; the grace window is
# what keeps this correct for reviews already sitting on older PRs, and if the
# bot ever regresses.
#
# Exit codes:
#   0  a verdict landed; verdict on stdout
#   2  timed out waiting (recent PR Review runs dumped for diagnosis)
#   1  usage/precondition error
set -euo pipefail

pr="${1:?usage: request-pr-review.sh <pr-number> [timeout-seconds]}"
timeout="${2:-900}"
interval=60

# How long a COMMENTED-only state is held before it is accepted as the verdict.
# The observed placeholder-to-summary gaps are 16s (#622) and 50s (#617), so 180
# is several times the worst case seen while still leaving a real COMMENT verdict
# usable well inside the default timeout. Clamped below `timeout` so a caller
# passing a short timeout still gets its COMMENTED verdict rather than an exit 2.
grace=180
if [ "$grace" -ge "$timeout" ]; then
    grace=$(( timeout / 2 ))
fi
first_commented_at=""

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

    # A decisive verdict wins immediately, whenever it appears.
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

    # Otherwise: a COMMENTED-only state. Hold it for GRACE seconds so a summary
    # can supersede it, then accept it as the verdict. Holding forever would
    # swallow a real COMMENT verdict; returning at once would take the
    # placeholder. Both have happened.
    commented=$(gh pr view "$pr" --json reviews \
        --jq "[.reviews[]
               | select(.submittedAt > \"${since}\")
               | select(.state == \"COMMENTED\")]
              | last | select(. != null)
              | \"\(.state) \(.submittedAt) \(.author.login)\"")

    if [ -n "$commented" ]; then
        if [ -z "$first_commented_at" ]; then
            first_commented_at=$(date +%s)
            echo "Saw a COMMENTED review; holding ${grace}s in case a summary follows." >&2
        elif [ $(( $(date +%s) - first_commented_at )) -ge "$grace" ]; then
            echo "No summary superseded it within ${grace}s — treating COMMENTED as the verdict." >&2
            echo "VERDICT ${commented}"
            exit 0
        fi
    fi
done

echo "No review landed within ${timeout}s." >&2
echo "No reviews of any state were submitted since the trigger, so the review" >&2
echo "never reached the workflow — this is a trigger fault, not a stalled review." >&2
echo "(A review that posted notes but no summary would have returned COMMENTED" >&2
echo " via the grace path above.) PR #619 failed exactly this way, twice." >&2

echo "Recent PR Review runs:" >&2
gh run list --workflow="PR Review" --limit 3 >&2
exit 2
