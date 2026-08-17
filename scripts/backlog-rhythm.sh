#!/usr/bin/env bash
#
# The Product Owner's Rhythm pass: decide what grooming is DUE right now.
#
# This exists because none of the follow-up rules in .claude/skills/backlog
# had ever fired. The 14-day reporter chase, the 28-day park, the
# reporter-replied re-check and the stale-worktree handoff were all written
# down and none of them ran, because nothing scheduled them and every rule
# needed a model to notice it.
#
# So the NOTICING is deterministic and lives here. Every rule below is a
# comparison over `backlog-digest.sh` output — no judgement, no tokens. The
# PO agent is only needed to ACT (write a nudge, summarise a thread, decide a
# priority), and only when this script says something is due. A quiet backlog
# therefore costs one cheap process instead of a model pass.
#
# Usage:
#   scripts/backlog-rhythm.sh            # human-readable actions, or "nothing due"
#   scripts/backlog-rhythm.sh --json     # machine-readable, for a scheduled loop
#
# Exit codes:
#   0  ran successfully (whether or not anything is due — check the output)
#   1  the digest failed; its stderr is passed through
#
# It never writes to GitHub. Deciding is cheap and safe to run on a timer;
# acting is the PO's, and needs the identity and the judgement.
set -euo pipefail

as_json=false
if [ "${1:-}" = "--json" ]; then
    as_json=true
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Thresholds. NUDGE_DAYS/PARK_DAYS mirror the skill's board table (nudge once
# at 14 days, park at 28); they are variables so the tests can drive the
# boundaries without waiting a fortnight.
NUDGE_DAYS="${RHYTHM_NUDGE_DAYS:-14}"
PARK_DAYS="${RHYTHM_PARK_DAYS:-28}"

# `RHYTHM_DIGEST_FILE` and `RHYTHM_PRS_FILE` are test seams, the same shape as
# `BESS_ENV_FILE` in gh-agent.sh: they let the rules be exercised against
# fixtures without a network round-trip or a live board. Unset in normal use.
if [ -n "${RHYTHM_DIGEST_FILE:-}" ]; then
    digest=$(cat "$RHYTHM_DIGEST_FILE")
else
    digest=$("$here/backlog-digest.sh")
fi

# The PR side of the loop. The goal is a READY PR for the maintainer to
# approve, and a draft PR only becomes ready by earning an APPROVED review —
# so the two states that actually move work to the finish line are "draft with
# no review requested" and "draft that has been approved". Neither is visible
# in the issue digest, and both were invisible in practice: three PRs sat green
# and reviewed with nobody flipping them, and #619 was never reviewed at all.
repo="${REPO:-johanzander/bess-manager}"
if [ -n "${RHYTHM_PRS_FILE:-}" ]; then
    prs=$(cat "$RHYTHM_PRS_FILE")
else
    prs=$(gh pr list --repo "$repo" --state open --limit 100 \
        --json number,title,isDraft,mergeable,reviewDecision,reviews,author)
fi

actions=$(printf '%s' "$digest" | jq \
    --argjson nudge "$NUDGE_DAYS" \
    --argjson park "$PARK_DAYS" \
    --argjson prs "$prs" '

  # Quiet time is measured from the LAST COMMENT, not from updatedAt. A label
  # change, a board move or a bot touch all bump updatedAt, so an issue nobody
  # has spoken on for a month can look active and never age into a chase.
  def quiet_days: if .last_comment == null then .age_days else .last_comment.days end;

  (.items) as $items
  | [ $items[]

    # The reporter answered us. This is the transition that matters most and
    # the one the digest could not previously see: a wait on the reporter may
    # now be satisfied, so the Definition of Ready needs re-checking. It is
    # listed before the chases on purpose — chasing someone who has already
    # replied is the worst output this pass could produce.
    | (if .awaiting == "reporter" and (.last_comment.is_reporter // false)
       then {issue: .number, action: "recheck_ready",
             why: "reporter replied \(.last_comment.days)d ago while awaiting them",
             detail: "re-check Definition of Ready; clear Awaiting if satisfied"}
       else empty end),

    # Chase once, then park. `is_reporter` false means the last word was ours,
    # so the ball is still with them.
    (if .awaiting == "reporter"
        and ((.last_comment.is_reporter // false) | not)
        and quiet_days >= $park
     then {issue: .number, action: "park",
           why: "awaiting reporter, quiet \(quiet_days)d (>= \($park))",
           detail: "move to Backlog; the chase has gone unanswered"}
     elif .awaiting == "reporter"
        and ((.last_comment.is_reporter // false) | not)
        and quiet_days >= $nudge
     then {issue: .number, action: "nudge_reporter",
           why: "awaiting reporter, quiet \(quiet_days)d (>= \($nudge))",
           detail: "nudge once, as the PO identity"}
     else empty end),

    # A discussion nobody has advanced is a question for the maintainer, not a
    # reason to keep waiting. Never auto-parked: an open conversation is not
    # the same as an unanswered chase.
    (if .awaiting == "discussion" and quiet_days >= $nudge
     then {issue: .number, action: "surface_discussion",
           why: "discussion stalled \(quiet_days)d",
           detail: "summarise the thread and put the open question to the maintainer"}
     else empty end),

    # Grooming debt: the board field is unset while a label implies a wait, so
    # the authoritative value is missing and only the label is holding it.
    (if .awaiting != null and .awaiting_source == "label"
     then {issue: .number, action: "set_awaiting",
           why: "labels imply awaiting=\(.awaiting_suggested) but the board field is empty",
           detail: "set Awaiting on the card"}
     else empty end),

    # No priority means the item cannot be ranked, so it can never be "next".
    (if .priority == null
     then {issue: .number, action: "set_priority",
           why: "no Priority on the board",
           detail: "set P1-P4; without it the item is unrankable and never Ready"}
     else empty end),

    # Un-pruned worktrees are what made four issues read as In Progress.
    (if .stale_worktree
     then {issue: .number, action: "prune_worktree",
           why: "worktree \(.worktree_branch) already merged",
           detail: "hand to sweep-prs"}
     else empty end),

    # An open issue with no labels at all is unfiled. Real and common.
    (if (.labels | length) == 0
     then {issue: .number, action: "triage_labels",
           why: "no labels",
           detail: "classify it"}
     else empty end),

    # STALLED WORK. A live worktree with no session behind it is an
    # implementation that stopped mid-flight: the machine restarted, the
    # session was killed, or the agent exited between steps. Nothing used to
    # pick these up, and a fleet audit found 34 such worktrees -- 8 of them
    # holding real unpushed commits, one with 32.
    #
    # `pr == null` guards against double-reporting: once a PR exists the PR
    # branch below owns the handoff, and both firing would list the same work
    # twice.
    #
    # The branch survives, so this is a resume and never a restart -- Step 0
    # re-enters at the earliest incomplete step. Restarting would run Step 4,
    # which branches fresh from origin/main and would delete those commits.
    (if .worktree != null and (.stale_worktree | not) and .session == null and .pr == null
     then {issue: .number, action: "resume_implementation",
           why: "worktree \(.worktree_branch) on disk, no live session",
           detail: "/implement-issue \(.number) — Step 0 resumes it; never restart, the branch commits are the only copy"}
     else empty end),

    # The positive case: actually dispatchable.
    (if .column == "Ready for Dev"
     then {issue: .number, action: "dispatchable",
           why: "Ready for Dev, priority \(.priority)",
           detail: "meets Definition of Ready; propose for dispatch"}
     else empty end)
  ]

  # --- the PR half -------------------------------------------------------
  #
  # This pass does NOT drive the review loop. `implement-issue` owns a PR from
  # its first commit to `gh pr ready`, and Step 11 already requests the review,
  # acts on the verdict and flips the PR when it is approved. Re-implementing
  # any of that here would be a second copy of one loop, which is how one of
  # them goes stale -- the same argument that put resume in Step 0 rather than
  # in a separate skill.
  #
  # So an unfinished PR resolves to ONE action: hand it back to the skill that
  # owns it. Step 0 detects the prior work and re-enters at the right step,
  # whether the PR needs a first review, a rework, or just the ready flag it
  # never got. #615 and #617 sat APPROVED-but-draft not because nothing was
  # watching for that state, but because the sessions that owned them exited
  # before Step 11 completed.
  #
  # Two exceptions stay here, because they are fleet-level and
  # `implement-issue` deliberately does not widen to them (its Step 10 owns
  # exactly one PR).
  + [ $prs[]
      | . as $p
      # The issue this PR belongs to, so the handoff can name it.
      | ([ $items[] | select(.pr == $p.number) | .number ] | first) as $issue_no
      | (if .mergeable == "CONFLICTING"
         then {pr: .number, action: "resolve_conflict",
               why: "CONFLICTING — note a conflicted PR produces no CI run at all",
               detail: "hand to sweep-prs, or resolve if the diff is ours"}
         elif (.isDraft | not)
         then {pr: .number, action: "awaiting_maintainer",
               why: "out of draft",
               detail: "nothing left but your merge"}
         else {pr: .number, issue: $issue_no, action: "resume_implementation",
               why: "draft PR, review loop unfinished",
               detail: (if $issue_no != null
                        then "/implement-issue \($issue_no) — Step 0 re-enters at the review loop and drives it to gh pr ready"
                        else "no issue references this PR; finish it by hand or link it" end)}
         end)
    ]

  | {
      due: length,
      by_action: (group_by(.action) | map({key: .[0].action, value: length}) | from_entries),
      actions: sort_by(.action, (.issue // .pr))
    }
')

if [ "$as_json" = true ]; then
    printf '%s\n' "$actions"
    exit 0
fi

due=$(printf '%s' "$actions" | jq -r '.due')
if [ "$due" -eq 0 ]; then
    echo "RHYTHM: nothing due."
    exit 0
fi

echo "RHYTHM: $due action(s) due"
printf '%s' "$actions" | jq -r '
  "",
  (.by_action | to_entries | map("  \(.key): \(.value)") | join("\n")),
  "",
  (.actions[] | "  \(if .pr then "PR #\(.pr)" else "##\(.issue)" end) \(.action)\n      why: \(.why)\n      do : \(.detail)")
'
