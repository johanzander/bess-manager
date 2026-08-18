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
# So COMMENTED is resolved by asking whether the REVIEWER IS STILL WORKING, not
# by parsing its body and not by a timer. Body text is bot-generated prose with
# no contract behind it. A timer was tried and was the wrong instrument: sized
# from those 16s/50s gaps, it still pre-empted a summary, because the gap that
# matters is not placeholder-to-summary but placeholder-to-END-OF-RUN — the bot
# posts an early permission check within a couple of minutes and works for five
# to eight more. No fixed number is both short enough to return a real COMMENT
# promptly and long enough never to pre-empt.
#
# APPROVED/CHANGES_REQUESTED return immediately. A COMMENTED is held while the
# run is live and accepted as the verdict once the run has finished, which is
# exactly what COMMENT means in pr-review.yml's own three-verdict contract.
#
# `pr-review.yml` step 3 is also changed so inline notes post via `gh api`
# instead of `gh pr review`, which stops the placeholder being submitted as a
# review at all — that removes the ambiguity at its source. The run-state check
# is what keeps this correct for older PRs and if the bot regresses.
#
# THE UNCONSUMED-VERDICT PROBLEM. Everything above concerns waiting for a
# verdict. This block concerns whether asking for one is legal at all.
#
# Step 11's contract is a cycle: request -> verdict -> fix -> push -> request.
# The round count and "have I acted on the last verdict yet" lived only in the
# agent's head, so a session that died, timed out, or simply lost the thread
# re-entered the loop by doing the one thing it could always do -- ask again.
#
# Observed on PR #619, verbatim:
#   06:55  @claude-bot review          (no run -- actor gate, see `none` below)
#   07:12  @claude-bot review          (no run)
#   09:33  @claude-bot review
#   09:40  CHANGES_REQUESTED           two blocking findings
#   10:50  @claude-bot review          <-- HEAD unchanged since 07:35
#   10:55  CHANGES_REQUESTED           a different blocking finding
# Four requests, zero verdicts consumed, one byte-identical diff, and two paid
# review rounds spent re-reviewing code nobody had touched. Step 11's prose
# already forbids this ("Fix the blockers ... Then start the next round") and
# already caps rounds at 3. Prose was not the enforcement mechanism, because the
# state it reasons about did not survive the session.
#
# It does not need to. Both facts are already on the PR and are read here
# instead of remembered:
#   rounds so far  = decisive reviews (APPROVED/CHANGES_REQUESTED) on the PR
#   consumed?      = is the newest commit newer than the newest verdict?
# A verdict newer than the last push is a verdict about the current diff, so the
# only legal next move is to change the diff. Asking again cannot help.
#
# `--allow-unconsumed` is the escape hatch for the one case Step 11 does
# sanction: the reviewer was wrong, you replied on the PR saying why, and no
# push was warranted. It is a flag rather than the default so that "the reviewer
# is mistaken" has to be a decision someone makes, not the path of least
# resistance a stalled loop falls into.
#
# committedDate is the authored date, not the push date. Those diverge under
# rebase and cherry-pick; this repo merges the target branch instead of rebasing
# (CLAUDE.md, Release Workflow), so on any branch this script is pointed at they
# agree to within seconds of the push.
#
# Exit codes:
#   0  a verdict landed; verdict on stdout
#   2  timed out waiting (recent PR Review runs dumped for diagnosis)
#   1  usage/precondition error, INCLUDING an illegal round (see above)
set -euo pipefail

allow_unconsumed=0
if [ "${1:-}" = "--allow-unconsumed" ]; then
    allow_unconsumed=1
    shift
fi

pr="${1:?usage: request-pr-review.sh [--allow-unconsumed] <pr-number> [timeout-seconds]}"
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
review_run_state() {
    gh run list --workflow "PR Review" --limit 20 \
        --json status,conclusion,createdAt \
        --jq "[ .[] | select(.createdAt > \"${since}\") ] | first
              | if . == null then \"none\"
                elif .status != \"completed\" then \"running\"
                elif .conclusion == \"success\" then \"finished\"
                else \"failed\" end" 2>/dev/null || echo "unknown"
}

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# --- Is another round legal at all? (see THE UNCONSUMED-VERDICT PROBLEM) ---
#
# One `gh pr view`, deliberately not `gh api`: that is on CLAUDE.md's ask list,
# and this script is run with run_in_background, where a permission prompt is an
# indefinite stall rather than a question anyone sees.
gate=$(gh pr view "$pr" --json reviews,commits --jq '
    ([.reviews[]
      | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")]
     | sort_by(.submittedAt)) as $decisive
    | ($decisive | last) as $latest
    | ([.commits[].committedDate] | sort | last) as $pushed
    | "\($decisive | length) \($latest.state // "none")" +
      " \($latest.submittedAt // "-") \($pushed // "-")"
  ' 2>/dev/null || echo "")

if [ -z "$gate" ] && [ "$allow_unconsumed" -eq 0 ]; then
    echo "Could not read PR #${pr}'s reviews and commits, so whether another" >&2
    echo "round is legal was never determined. Refusing rather than guessing." >&2
    echo "A needless round costs a paid review of an unchanged diff; re-running" >&2
    echo "this command costs nothing. --allow-unconsumed overrides." >&2
    exit 1
fi

if [ -n "$gate" ] && [ "$allow_unconsumed" -eq 0 ]; then
    read -r rounds latest_state latest_at last_push <<<"$gate"

    # A verdict newer than the last push is a verdict about the diff as it
    # stands. Asking again re-reviews the same bytes -- #619 did this twice.
    if [ "$latest_state" != "none" ] && [ "$last_push" != "-" ] &&
        [[ "$latest_at" > "$last_push" ]]; then
        if [ "$latest_state" = "APPROVED" ]; then
            echo "PR #${pr} is already APPROVED (${latest_at}) on the current" >&2
            echo "diff -- nothing has been pushed since. Another round cannot" >&2
            echo "improve on an approval. Step 11's next move is 'gh pr ready'," >&2
            echo "after re-checking mergeability." >&2
        else
            echo "PR #${pr} has an unconsumed CHANGES_REQUESTED (${latest_at})" >&2
            echo "and HEAD has not moved since (last commit ${last_push})." >&2
            echo "The findings are still outstanding, so the only move that can" >&2
            echo "change the answer is to address them and push. Requesting" >&2
            echo "another review here is what burned two paid rounds on #619." >&2
            echo "" >&2
            echo "If the reviewer is wrong, reply on the PR saying why and pass" >&2
            echo "--allow-unconsumed to request the next round deliberately." >&2
        fi
        exit 1
    fi

    # Step 11's cap, enforced here because a resumed session cannot remember it.
    if [ "$rounds" -ge 3 ]; then
        echo "PR #${pr} already has ${rounds} decisive review rounds. Step 11" >&2
        echo "caps this at 3: three rounds of disagreement means the reviewer" >&2
        echo "and the author disagree about the design, not about a bug, and a" >&2
        echo "fourth will not settle it. Hand the outstanding findings to the" >&2
        echo "user verbatim instead." >&2
        exit 1
    fi
fi

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

    commented=$(gh pr view "$pr" --json reviews \
        --jq "[.reviews[]
               | select(.submittedAt > \"${since}\")
               | select(.state == \"COMMENTED\")]
              | last | select(. != null)
              | \"\(.state) \(.submittedAt) \(.author.login)\"")

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
            # verdict; waiting costs one more poll, and a genuine COMMENT
            # verdict still returns as soon as the state resolves.
            echo "COMMENTED seen but the review is ${state} — waiting." >&2
        else
            # The run has finished and its last word was COMMENTED, so that IS
            # the verdict: `pr-review.yml` lists COMMENT as one of three final
            # verdicts ("questions/observations only").
            echo "Review finished with COMMENTED as its last word — that is the verdict." >&2
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
