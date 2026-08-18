#!/usr/bin/env bash
#
# What state is each open PR in, and WHOSE TURN is it?
#
# Answers "is someone working on this, is it stalled, blocked, in progress, or
# waiting on review" in one command, from GitHub facts only.
#
# Usage:
#   scripts/pr-state.sh            # every open PR
#   scripts/pr-state.sh 619        # one PR
#
# WHY THIS EXISTS. The question was previously answered by a fresh session
# running half a dozen ad-hoc shell commands and inferring from local signals --
# `git worktree list`, `claude agents --json`, HEAD age. That is expensive (a
# cold Opus context per question, see CLAUDE.md Cost Discipline) and it is wrong
# in a specific way: those signals are LOCAL. An executor running in a container
# or a GitHub Action leaves no worktree and no local session, so every PR reads
# as unowned.
#
# Asked about #619 it reported "no one is working on it, session idle since
# 10:55". 10:55 was the REVIEWER BOT's review timestamp -- `updatedAt` on the
# PR, bumped by someone else entirely. The last executor action was a review
# request at 10:50; the last code action was four hours earlier. The inference
# conflated "something happened on this PR" with "the agent is alive".
#
# So this derives state from what GitHub durably knows, and reports the one thing
# it cannot know as unknown rather than guessing it from a worktree.
#
# THE ONE THING NOT DERIVABLE is liveness: GitHub knows a PR's content state,
# never whether a process is currently working on it. What it does know is
# strictly more useful for deciding what to do -- whether the ball is with the
# executor, the reviewer, or the maintainer. A PR whose newest verdict is newer
# than its newest push is waiting on a code change no matter who is or is not
# alive, so `needs-fix` is actionable without resolving liveness at all.
#
# `sweep-prs` remains the tool that ACTS (merge main, prune worktrees). This one
# only reads, so it is safe to run anywhere, including against a fleet whose
# worktrees live on another machine.
set -euo pipefail

pr_filter="${1:-}"

# `reviewDecision` is deliberately not used: it does not distinguish a verdict
# that has been acted on from one that has not, which is the distinction that
# decides whose turn it is. Compute it from reviews vs commits instead.
fields='number,title,isDraft,mergeable,mergeStateStatus,headRefName,reviews,commits,statusCheckRollup,updatedAt,comments'

# `commits` is what bounds this, and the bound is GitHub's, not a preference.
# `--json commits` expands each commit's authors connection, so gh's cost
# estimate is limit x commits x authors: at --limit 100 that is 100 x 100 x 100 =
# 1,000,000 possible nodes and the query is REJECTED outright --
#
#   GraphQL: By the time this query traverses to the authors connection, it is
#   requesting up to 1,000,000 possible nodes which exceeds the maximum limit of
#   500,000.
#
# Found by running this against a real fleet; the fixture tests could not see it.
# 30 keeps the worst case at 300,000, inside the ceiling. There is no cheaper
# field for "when did HEAD last move" -- `gh pr list --json` offers no
# last-commit date, and a review's own commit SHA is REST-only (`gh api`, which
# is on CLAUDE.md's ask list).
PR_LIMIT=30

fetch() {
    if [ -n "$pr_filter" ]; then
        gh pr view "$pr_filter" --json "$fields" | jq -c '[.]'
    else
        gh pr list --state open --limit "$PR_LIMIT" --json "$fields"
    fi
}

# `mergeable` is computed LAZILY, and this is the single most dangerous thing
# about reading it. The first query on a cold PR returns UNKNOWN *and* triggers
# the computation, so a one-shot pass reports UNKNOWN for precisely the stale
# PRs worth finding -- and if UNKNOWN is treated as "not conflicted", every
# conflicted PR in a cold fleet reads as fine.
#
# Measured here while building this: a first fleet run classified #167 and #619
# as `needs-fix`/CI-red with no conflict flag; after the queries above had
# warmed them, the identical command returned `needs-refresh` for both. Both
# were CONFLICTING the whole time. `sweep-prs` documents the same trap and
# retries for the same reason.
#
# So: ask again while anything is UNKNOWN, and if it still is, SAY SO rather
# than letting it fall through to the not-conflicted branch.
for _ in 1 2 3; do
    raw=$(fetch)
    [ "$(echo "$raw" | jq '[.[] | select(.mergeable == "UNKNOWN")] | length')" -eq 0 ] && break
    sleep 3
done

if [ -z "$pr_filter" ] && [ "$(echo "$raw" | jq 'length')" -eq "$PR_LIMIT" ]; then
    # No silent caps (sweep-prs): a truncated fleet must not read as a clean one.
    echo "WARNING: hit the ${PR_LIMIT}-PR ceiling — older open PRs were NOT" >&2
    echo "classified. Pass a PR number to inspect one directly." >&2
fi

# A quoted heredoc, not a single-quoted argument: the program below contains
# apostrophes, and `jq -r '...'` cannot hold them.
read -r -d '' classify <<'JQ' || true
  def verdict:
    [.reviews[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")]
    | sort_by(.submittedAt) | last;
  def pushed: [.commits[].committedDate] | sort | last;
  # The Stage 4 bot only ever acts when triggered by this comment, so its
  # absence is the difference between "waiting on the reviewer" and "nobody
  # has asked the reviewer".
  def requested:
    [.comments[]? | select(.body | test("@claude-bot review")) | .createdAt]
    | sort | last;
  def failing:
    [.statusCheckRollup[]? | select(.conclusion == "FAILURE") | .name];
  def pending:
    [.statusCheckRollup[]? | select(.status == "IN_PROGRESS" or .status == "QUEUED")]
    | length;

  .[]
  | . as $p
  | (verdict) as $v
  | (pushed) as $push
  | (.mergeable == "CONFLICTING" or .mergeStateStatus == "DIRTY") as $conflicted
  # UNKNOWN survived the retries above. It is NOT "not conflicted" -- it is "we
  # never found out", and it must never render as a clean PR.
  | (.mergeable == "UNKNOWN") as $mergeUnknown
  | (requested) as $req
  | ($v != null and $v.submittedAt > $push) as $unconsumed

  # Order matters, and it is ordered by WHAT THE DIFF STILL OWES rather than by
  # what happened most recently.
  #
  # An unconsumed CHANGES_REQUESTED outranks a conflict. Both belong to the
  # executor, but the findings are about the code while the conflict is
  # mechanical, and a PR that reported only its conflict would hide two blocking
  # reviews. #619 is exactly that shape -- conflicted AND carrying two
  # unaddressed verdicts -- so the conflict is reported alongside, never instead.
  #
  # Conflict then outranks CI, because a CONFLICTING PR gets no workflow run at
  # all (see sweep-prs): testing CI first reports "no checks" and calls a
  # conflicted PR green.
  | (if $unconsumed and $v.state == "CHANGES_REQUESTED"
       then ["needs-fix", "executor",
             "UNCONSUMED changes-requested (\($v.submittedAt)); no push since \($push)"]
     elif $conflicted
       then ["needs-refresh", "sweep", "conflicts with main; no CI runs until merged"]
     elif (failing | length) > 0
       then ["needs-fix", "executor", "CI red: " + (failing | join(", "))]
     elif pending > 0
       then ["in-flight", "-", "CI running (\(pending) checks)"]
     elif $unconsumed
       then ["awaiting-ready", "maintainer",
             "approved (\($v.submittedAt)) and still a draft"]
     elif ($req == null or $req < $push)
       then ["needs-review-request", "dispatcher",
             (if $req == null
                then "green, but a review has NEVER been requested"
                else "pushed \($push) after the last request (\($req)); round owed"
              end)]
     else ["awaiting-review", "reviewer",
           "requested \($req); the bot has not returned a verdict yet"] end)
    as [$state, $owner, $why]

  | "#\($p.number) \(if $p.isDraft then "draft" else "ready" end)  \($state)  [\($owner)]"
  + (if $conflicted and $state != "needs-refresh" then "  (+conflicted)" else "" end)
  + (if $mergeUnknown then "  (+mergeability UNKNOWN — re-run)" else "" end)
  + "\n    \($p.title[0:72])\n    \($why)\n"
JQ

echo "$raw" | jq -r "$classify"

# --- Local join: is more than one writer on this branch? --------------------
#
# GitHub cannot answer this. A branch with two writers looks entirely normal
# through the API -- the divergence exists only between a local checkout and the
# remote, and it collapses into an ordinary merge the moment someone reconciles.
#
# #619 is the worked example. One writer took the branch at 08:09 and worked
# from that base all day; another pushed 23031e78 at 09:34. The reviewer
# reviewed 23031e78 three times, twice with blocking findings, while the first
# line never held that commit at all. Fifteen hours later it landed as
# `Merge remote-tracking branch 'origin/fix/...' into fix/...` -- a branch merged
# into itself, which is the fingerprint of exactly this.
#
# `git rev-list --left-right` would have caught it at 09:34.
#
# Skipped LOUDLY when there is no checkout to compare: this script is also meant
# to run against a container fleet, where no worktree exists and a silent skip
# would read as "no divergence found".
echo ""
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Local writer check SKIPPED — not inside a git checkout, so no worktree"
    echo "could be compared against its remote. This says nothing about writers."
else
    git fetch origin --quiet 2>/dev/null || true
    echo "Local writers (worktrees whose branch has an open PR):"
    git worktree list --porcelain |
        awk '/^worktree /{w=$2} /^branch /{sub("refs/heads/","",$2); print w"\t"$2}' |
        while IFS="$(printf '\t')" read -r wt branch; do
            pr=$(echo "$raw" | jq -r --arg b "$branch" \
                '.[] | select(.headRefName == $b) | .number')
            [ -z "$pr" ] && continue
            counts=$(git rev-list --left-right --count \
                "refs/remotes/origin/${branch}...${branch}" 2>/dev/null || true)
            if [ -z "$counts" ]; then
                echo "  #${pr} ${branch} — never pushed (no remote-tracking ref)"
                continue
            fi
            behind=$(echo "$counts" | cut -f1)
            ahead=$(echo "$counts" | cut -f2)
            if [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then
                echo "  #${pr} ${branch}"
                echo "      *** DIVERGED: ${ahead} local / ${behind} remote — TWO WRITERS ***"
                echo "      ${wt}"
            elif [ "$ahead" -gt 0 ]; then
                echo "  #${pr} ${branch} — ${ahead} unpushed commit(s)"
            elif [ "$behind" -gt 0 ]; then
                echo "  #${pr} ${branch} — ${behind} behind its own remote"
            else
                echo "  #${pr} ${branch} — in sync"
            fi
        done
fi

cat <<'EOF'
Liveness (is an agent working RIGHT NOW) is not a GitHub fact and is not
guessed here. `needs-fix`, `needs-refresh` and `needs-review-request` are
actionable regardless: each names an action the pipeline still owes, which no
amount of waiting produces.
EOF
