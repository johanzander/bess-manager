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
# THE COMMENTED PROBLEM. `pr-review.yml` now gives the bot exactly two final
# verdicts, APPROVE and REQUEST_CHANGES: findings that do not block merge are an
# APPROVE with the nits in the body, because a COMMENTED review does not clear
# GitHub's `reviewDecision` and so leaves an earlier REQUEST_CHANGES blocking
# the merge (measured on #687: four rounds, the last two explicitly
# non-blocking, still needing a manual dismissal). COMMENT used to be a third
# legal verdict, which is why everything below exists -- and the ambiguity does
# not disappear with it, because the bot may still post inline notes as a
# separate `COMMENTED` review before its summary, body "Inline notes below;
# summary review to follow.". So `COMMENTED` remains ambiguous from state
# alone: either a placeholder that decides nothing, or a run that ended without
# ever giving a legal verdict.
#
# Getting this wrong in either direction has been observed:
#   - Treating COMMENTED as terminal returns the placeholder. Measured on #617
#     (06:57:13Z placeholder, 06:58:03Z APPROVED -- 50s) and #622 (08:48:58Z,
#     08:49:14Z -- 16s). `implement-issue` Step 11 then saw a non-APPROVED
#     verdict and skipped `gh pr ready`: that is how #615 sat approved-but-draft
#     overnight with only the merge left to do.
#   - Treating COMMENTED as never-terminal swallows a run whose last word was
#     COMMENTED. The loop waits out the full timeout and reports "no summary
#     landed", which is false when a summary with findings sits on the PR.
#
# So COMMENTED is resolved by asking whether the REVIEWER IS STILL WORKING, not
# by parsing its body and not by a timer. Body text is bot-generated prose with
# no contract behind it. A timer was tried and was the wrong instrument: sized
# from those 16s/50s gaps, it still pre-empted a summary, because the gap that
# matters is not placeholder-to-summary but placeholder-to-END-OF-RUN — the bot
# posts an early permission check within a couple of minutes and works for five
# to eight more. No fixed number is both short enough to report a finished
# COMMENTED promptly and long enough never to pre-empt.
#
# APPROVED/CHANGES_REQUESTED return immediately. A COMMENTED is held while the
# run is live and returned once the run has finished -- not because it is a
# verdict (it no longer is) but because the reviewer has stopped talking, and
# reporting its last word beats timing out. Callers treat anything that is not
# APPROVED the same way: collect findings, do not flip the PR ready.
#
# `pr-review.yml` step 3 is also changed so inline notes post via `gh api`
# instead of `gh pr review`, which stops the placeholder being submitted as a
# review at all — that removes the ambiguity at its source. The run-state check
# is what keeps this correct for older PRs and if the bot regresses.
#
# Exit codes:
#   0  a verdict landed; verdict on stdout
#   1  usage/precondition error
#   2  timed out waiting (recent PR Review runs dumped for diagnosis)
#
# A timeout used to mean "the bot found nothing and said nothing" as often as
# it meant a real failure, because the reviewer only spoke up when it had
# findings. pr-review.yml now requires a summary review on every run, including
# a clean one, so a timeout is once again a genuine signal worth investigating.
# That matters beyond diagnosis: GitHub blocks a merge on the LAST explicit
# verdict, so a silent clean run could never clear a prior REQUEST_CHANGES —
# the review had to be dismissed by hand.
set -euo pipefail

pr="${1:?usage: request-pr-review.sh <pr-number> [timeout-seconds]}"
timeout="${2:-900}"
# REVIEW_POLL_INTERVAL is a test seam (see BESS_ENV_FILE in gh-agent.sh for the
# same shape): the decision logic is what needs exercising, not the waiting, and
# a 60s poll makes every test cost a minute. Unset in normal use.
interval="${REVIEW_POLL_INTERVAL:-60}"

# Is a PR Review workflow run still working on this PR?
#
# This replaces a fixed grace window, which was the wrong instrument. The window
# was sized from the observed placeholder-to-summary gaps (16s on #622, 50s on
# #617) and then failed anyway, because those gaps were not the thing to measure:
# the bot posts an early permission-check comment ("test permission check -
# ignore") within a couple of minutes and finishes five to eight minutes later.
# No fixed number is both short enough to return a real COMMENT verdict promptly
# and long enough to never pre-empt a summary.
#
# Asking the run instead answers the actual question -- is the reviewer still
# thinking? -- and needs no guess. It also fixes the opposite failure: a run that
# DIED is indistinguishable from one that is thinking when you only poll for
# reviews, so a crashed review burned the full timeout. On #623 that cost 16
# minutes of waiting on a run that had already failed with "Reached maximum
# number of turns (60)".
#
# THE RUN MUST BE THIS PR'S. Selecting the newest run by time alone was wrong,
# and wrong in the direction that costs a review round: `pr-review.yml` triggers
# on `issue_comment`, which fires for comments on ISSUES too, not only PRs.
# Those runs are gated out and complete as `skipped` within about ten seconds.
#
# So any comment posted anywhere in the repo while a review is running produces
# a newer `PR Review` run that is `completed` and not `success` -- which this
# function read as `failed`. Measured on #636: a routine PO comment on issue
# #441 at 21:13:07 made the script abandon a review that went on to APPROVE at
# 21:15:45. The caller was told the run was broken while it was still thinking.
#
# `displayTitle` carries the PR title for a run triggered on that PR, so it is
# the discriminator. The title is fetched once, before the loop, and matched
# through `--arg` rather than string-interpolated -- a title containing a quote
# would otherwise break the filter.
# $1 optionally overrides the createdAt cutoff; defaults to the global
# $since. Parameterised (not a second query) so the pre-post in-flight check
# below can reuse this exact detector with a wide-open cutoff, instead of
# inventing a second way to decide whether the reviewer is working.
review_run_state() {
    local cutoff="${1:-$since}"
    gh run list --workflow "PR Review" --limit 20 \
        --json status,conclusion,createdAt,displayTitle 2>/dev/null \
      | jq -r --arg since "$cutoff" --arg title "$pr_title" '
            [ .[]
              | select(.createdAt >= $since)
              | select(.displayTitle == $title) ] | first
            | if . == null then "none"
              elif .status != "completed" then "running"
              elif .conclusion == "success" then "finished"
              else "failed" end' 2>/dev/null || echo "unknown"
}

# The createdAt of the run review_run_state just reported "running", used
# only to back-date $since so the rest of this script keeps recognising that
# run as live instead of as older-than-the-window. This reads the exact same
# `gh run list` shape as review_run_state -- it answers "since when", not a
# second opinion on "is it running".
running_run_created_at() {
    gh run list --workflow "PR Review" --limit 20 \
        --json status,conclusion,createdAt,displayTitle 2>/dev/null \
      | jq -r --arg title "$pr_title" '
            [ .[] | select(.displayTitle == $title) | select(.status != "completed") ]
            | sort_by(.createdAt) | last | .createdAt // empty' 2>/dev/null || echo ""
}

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# The PR title, used to tell THIS PR's review run from any other `PR Review`
# run that happens to be newer. Fetched before `since` so a slow call cannot
# push the window past a review that lands immediately.
pr_title=$(gh pr view "$pr" --json title --jq .title)
if [ -z "$pr_title" ]; then
    echo "Could not read PR #${pr} title; refusing to poll without a way to" >&2
    echo "tell its review run from anyone elses." >&2
    exit 2
fi

# GATE ON THE EXISTING DETECTOR, BEFORE POSTING. Three callers can trigger a
# review now (implement-issue Step 11, advance-pr, backlog-rhythm.sh's
# handoff), sharing no state between them. Without this check, a caller whose
# 15-minute timeout (exit 2) landed while the bot was still thinking got a
# NEXT tick that re-posted "@claude-bot review" on a run already in flight --
# a second paid review round (~$0.5-1) on a diff the first review had not
# finished looking at. This happened once already; see the exit-2 diagnostic
# below.
#
# `since` becomes the in-flight run's own createdAt rather than "now", so the
# rest of this script (which all reads relative to $since) still recognises
# that run as live instead of as older-than-the-window. Posting is skipped
# entirely in that case -- this invocation waits on the review already
# running rather than triggering a second one. A cutoff of the epoch means
# "any not-completed run for this title, whenever it started"; review_run_state
# treating the query failing as "unknown" (not "running") means a broken `gh
# run list` here fails OPEN to the pre-existing behaviour -- it posts, same
# as before this gate existed, rather than silently refusing to request a
# review it cannot prove is unnecessary.
if [ "$(review_run_state "1970-01-01T00:00:00Z")" = "running" ]; then
    since=$(running_run_created_at)
    [ -n "$since" ] || since="1970-01-01T00:00:00Z"
    echo "A PR Review run is already in flight for PR #${pr} (started ${since}) -- not re-triggering, waiting for its verdict instead." >&2
else
    # Reviews strictly newer than this are the ones this run triggered.
    since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    echo "Requesting review on PR #${pr} (since ${since})"
    scripts/gh-agent.sh pr comment "$pr" --body "@claude-bot review" >/dev/null
fi

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
    #
    # A FAILED READ IS NOT A RESULT, and `set -e` used to turn one into a fatal
    # error: a single transient 503 on this call killed the script with exit 1
    # AFTER the trigger comment had already posted, so re-running it spent a
    # second paid review round on a review already in flight. GitHub returned
    # 503s for roughly ninety minutes on 2026-08-17 and this fired twice.
    # Swallowing the failure costs one wasted poll; the next iteration retries.
    verdict=$(gh pr view "$pr" --json reviews \
        --jq "[.reviews[]
               | select(.submittedAt > \"${since}\")
               | select(.state == \"APPROVED\" or .state == \"CHANGES_REQUESTED\")]
              | last | select(. != null)
              | \"\(.state) \(.submittedAt) \(.author.login)\"" 2>/dev/null) || verdict=""

    if [ -n "$verdict" ]; then
        echo "VERDICT ${verdict}"
        exit 0
    fi

    # No decisive verdict yet. What that means depends entirely on whether the
    # reviewer is still working, so ask.
    state=$(review_run_state)

    if [ "$state" = "failed" ]; then
        echo "The PR Review run FAILED without submitting a verdict." >&2
        echo "This is a broken run, not a slow one — do not keep waiting." >&2
        echo "Check its log; 'Reached maximum number of turns' is the usual cause." >&2
        gh run list --workflow "PR Review" --limit 3 >&2
        exit 2
    fi

    # Same transient-failure tolerance as the verdict read above.
    commented=$(gh pr view "$pr" --json reviews \
        --jq "[.reviews[]
               | select(.submittedAt > \"${since}\")
               | select(.state == \"COMMENTED\")]
              | last | select(. != null)
              | \"\(.state) \(.submittedAt) \(.author.login)\"" 2>/dev/null) || commented=""

    if [ -n "$commented" ]; then
        if [ "$state" = "running" ] || [ "$state" = "unknown" ]; then
            # The bot posts an early permission-check comment and keeps going,
            # so a COMMENTED while the run is live decides nothing.
            #
            # `unknown` waits for the same reason. It means `gh run list` itself
            # failed -- a network blip, a rate limit, a transient auth error --
            # so whether the reviewer is still working was never determined.
            # Treating "I could not tell" as "it finished" re-opens the exact
            # race this script exists to close, gated on API flakiness instead
            # of timing. Not knowing must never promote a placeholder to a
            # verdict; waiting costs one more poll, and a run that ends on
            # COMMENTED still returns as soon as the state resolves.
            echo "COMMENTED seen but the review is ${state} — waiting." >&2
        else
            # The run has finished and its last word was COMMENTED. Under the
            # current two-verdict contract that is a protocol violation, not a
            # verdict -- but it is still the reviewer's last word, and the
            # caller must be told rather than left to time out. Returned as-is;
            # every caller treats a non-APPROVED as "do not flip ready".
            echo "Review finished with COMMENTED as its last word — no legal verdict; returning it." >&2
            echo "VERDICT ${commented}"
            exit 0
        fi
    fi
done

echo "No verdict within ${timeout}s. Run state: $(review_run_state)" >&2
case "$(review_run_state)" in
    none)
        echo "No PR Review run started at all — the trigger never reached the" >&2
        echo "workflow. Check pr-review.yml's actor gate: it accepts the repo" >&2
        echo "owner and 'bess-agent' only. PR #619 failed this way twice." >&2
        ;;
    running)
        echo "The run is STILL going and simply outlasted this timeout. Re-run" >&2
        echo "with a longer one; do not re-trigger, that starts a second review." >&2
        ;;
    *)
        echo "The run ended without a verdict this script recognised." >&2
        ;;
esac

echo "Recent PR Review runs:" >&2
# `|| true` because this is diagnostics, not a check: if `gh` is what is broken
# (the `unknown` state above), `set -e` would abort here and the caller would
# get exit 1 instead of the exit 2 that means "no verdict".
gh run list --workflow="PR Review" --limit 3 >&2 || true
exit 2
