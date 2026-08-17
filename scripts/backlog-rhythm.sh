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
        --json number,title,isDraft,mergeable,reviewDecision,reviews,author,statusCheckRollup)
fi

actions=$(printf '%s' "$digest" | jq \
    --argjson nudge "$NUDGE_DAYS" \
    --argjson park "$PARK_DAYS" \
    --argjson prs "$prs" '
  # Board cards for PRs, keyed by number. Absent on an older digest, so this
  # defaults to empty rather than failing -- a rhythm run against a stale
  # digest then simply defers nothing, which is the pre-existing behaviour.
  (.pr_board // []) as $pr_board
  |

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
    #
    # The two causes need different actions, and conflating them sent the PO
    # to set a field on a card that does not exist. `board_status: null` is
    # the stronger one: no card at all, so there is nothing to set a Priority
    # on until one is added. #621 and #624 were both in that state while
    # reporting the milder "no Priority on the board".
    (if .board_status == null
     then {issue: .number, action: "add_card",
           why: "open issue with no card on the board",
           detail: "add it to Project #1, then set Priority — until then it is unrankable and invisible to every board pass"}
     elif .priority == null
     then {issue: .number, action: "set_priority",
           why: "no Priority on the board",
           detail: "set P1-P4; without it the item is unrankable and never Ready"}
     else empty end),

    # The card sits somewhere the evidence does not support. The digest wins;
    # this is always a card move, never a re-derivation.
    (if .board_status != null and .board_status != .column
     then {issue: .number, action: "move_card",
           why: "card is \(.board_status) but the evidence says \(.column)",
           detail: "move the card to \(.column)"}
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
    #
    # A LOCKED worktree means a session is holding it right now, and that check
    # is what stops this rule from firing on live work. `session` alone could
    # not: `claude agents` sees background agents only, so a foreground
    # `/implement-issue` started from the terminal was invisible and its
    # worktree read as abandoned. #624 was reported "no live session" while
    # actively being worked, with the advice to re-enter it -- a second session
    # on the same branch, against work the detail line itself calls the only
    # copy.
    (if .worktree != null and (.stale_worktree | not) and (.worktree_locked | not) and .session == null and .pr == null
     then {issue: .number, action: "resume_implementation",
           why: "worktree \(.worktree_branch) on disk, unlocked, no live session",
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
      # The board card belonging to this PR, if it has one. This is what lets a
      # decision about a PR be recorded once instead of re-argued every tick.
      #
      # NOTE: no apostrophes anywhere in this jq program. It is a single-quoted
      # shell string, so one apostrophe in a comment ends it early and bash
      # fails with "unexpected EOF while looking for matching )" pointing at the
      # top of the block rather than at the comment.
      | ([ $pr_board[] | select(.number == $p.number) ] | first) as $card
      # DEFERRED: a decision the maintainer already made, so stop asking.
      # An `Awaiting` means it is parked on someone (#167/#354 blocked, #620
      # parked pending a direction call); P4 means "later, not never" (#437,
      # #490). Both suppress the ACTION and survive as a count, so the item
      # stays findable without occupying the list of things to do.
      #
      # This is the whole point of putting PRs on the board: before it, there
      # was nowhere to write those three judgements down, so every pass
      # reported them as due and the same conversation happened every 30
      # minutes.
      | (($card.awaiting // null) != null or ($card.priority // null) == "P4") as $deferred
      # The APPROVED-but-still-draft state, computed here because it must
      # OUTRANK the deferral below. #629 sat approved, green and draft while
      # every pass reported it as ordinary unfinished work, because the session
      # that owned it went idle one command short of `gh pr ready`. That is a
      # pipeline failure, not a priority: it is one command from done, so it can
      # never be something the board quietens.
      | ([ .reviews[]? | select(.state != "COMMENTED") ] | last | .state?) as $verdict
      | (.reviewDecision == "APPROVED"
         or ($verdict == "APPROVED" and .reviewDecision != "CHANGES_REQUESTED")) as $is_approved
      # CI MUST BE GREEN, not merely unconflicted. `mergeable` reports only
      # whether the branch merges cleanly, so it reads MERGEABLE while checks
      # are still running or have failed -- #633 was APPROVED and MERGEABLE
      # with Algorithm tests and E2E still in progress, and an earlier version
      # of this rule duly said to flip it. Flipping a red or pending PR ready
      # is worse than leaving it draft: `ready` is supposed to mean the
      # maintainer can merge without checking anything.
      #
      # SKIPPED counts as fine (a path-filtered job that correctly did not
      # run); anything still QUEUED or IN_PROGRESS is not a verdict yet.
      | ([ .statusCheckRollup[]?
           | select((.conclusion // "") != "SUCCESS" and (.conclusion // "") != "SKIPPED"
                    and (.conclusion // "") != "NEUTRAL") ] | length == 0) as $checks_green
      | (.isDraft and $is_approved and $checks_green
         and .mergeable != "CONFLICTING") as $approved_draft
      | (if $approved_draft
         then {pr: .number, action: "mark_ready",
               why: "APPROVED and green, still a draft — Step 11 never ran gh pr ready",
               detail: "gh pr ready \(.number) — then it is the maintainers to merge"}
         # `mark_ready` above is the ONLY thing deferral cannot suppress, and
         # the distinction is deliberate. It is a pipeline failure -- the loop
         # stopped one command short of finishing -- so no priority the
         # maintainer sets makes it not worth fixing.
         #
         # `awaiting_maintainer` IS suppressible, by contrast: an approved PR
         # waiting on a merge is not broken, it is the maintainers call when to
         # take it, and P4 is exactly how they say "later". #490 sat approved
         # for a day and was reported every tick as though that were news.
         elif $deferred then empty
         elif .mergeable == "CONFLICTING"
         then {pr: .number, action: "resolve_conflict",
               why: "CONFLICTING — note a conflicted PR produces no CI run at all",
               detail: "hand to sweep-prs, or resolve if the diff is ours"}
         # OUT OF DRAFT IS NOT THE SAME AS REVIEWED, and treating it as such
         # told the maintainer to merge an unreviewed PR. The old rule was
         # `isDraft == false -> nothing left but your merge`, resting on the
         # assumption that only Step 11 clears the draft flag, and only after
         # an APPROVED verdict. Two things break that: a maintainer can flip
         # the flag by hand (#626 was flipped because it LOOKED stuck, and had
         # zero reviews at the time), and a Stage 3 CI-mode PR never runs Step
         # 11 at all. Stage 4 is the gate the whole pipeline is built around;
         # a surface that routes around it is worse than no surface.
         #
         # NEITHER SIGNAL ALONE IS CORRECT, and each fails in the merge-happy
         # direction, so the ORDER below is the whole content of this rule.
         #
         # `reviews[]` is history, not state: GitHub never rewrites an old
         # review when a later round requests changes, so an
         # approved-then-reworked PR keeps its stale APPROVED entry forever.
         # Asking "is there an APPROVED anywhere" first therefore reported
         # "nothing left but your merge" for a PR with changes outstanding --
         # exactly the failure this rule exists to prevent, reintroduced by the
         # first attempt at fixing it.
         #
         # `reviewDecision` is the current state, but it is only populated when
         # the repo REQUIRES reviews, and this one does not: it reads
         # CHANGES_REQUESTED for #619/#620/#614 and "" for #490, which carries
         # two real APPROVED reviews. So keying on it alone would report a
         # genuinely approved PR as never reviewed.
         #
         # Hence: trust `reviewDecision` whenever it is set, and only then fall
         # back to the LAST non-COMMENTED review. Last, not any -- same staleness
         # trap. COMMENTED is skipped because the bot posts its inline notes as
         # a COMMENTED review before its real verdict (see request-pr-review.sh).
         elif (.isDraft | not)
         then ([ .reviews[]? | select(.state != "COMMENTED") ] | last | .state?) as $last_verdict
              | (if .reviewDecision == "CHANGES_REQUESTED" or
                    (.reviewDecision == "" and $last_verdict == "CHANGES_REQUESTED") or
                    (.reviewDecision == null and $last_verdict == "CHANGES_REQUESTED")
                 then {pr: .number, issue: $issue_no, action: "rework_review",
                       why: "out of draft but the current review asks for changes",
                       detail: "address the review, then request a fresh one"}
                 elif .reviewDecision == "APPROVED" or $last_verdict == "APPROVED"
                 then {pr: .number, action: "awaiting_maintainer",
                       why: "out of draft and approved",
                       detail: "nothing left but your merge"}
                 else {pr: .number, issue: $issue_no, action: "request_review",
                       why: "out of draft but never reviewed — Stage 4 has not run",
                       detail: "scripts/request-pr-review.sh \(.number) — do NOT merge on the draft flag alone"}
                 end)
         else {pr: .number, issue: $issue_no, action: "resume_implementation",
               why: "draft PR, review loop unfinished",
               # `implement-issue` is used for TODO.md items and refactors too,
               # not only for issues, so a PR with no linked issue is normal
               # rather than a defect -- reporting "no issue, finish it by hand"
               # left every self-directed PR with no owner in the loop.
               #
               # No flag distinguishes the two: GitHub numbers issues and PRs
               # from ONE sequence per repo, so a bare number is already
               # unambiguous and Step 0 resolves whichever it is. Where an issue
               # is linked it is named, because it carries the diagnosis; where
               # none is, the PR number is the handle, and it is a strong one --
               # it holds the branch, the diff, the scope assessment and the
               # review verdict, which is everything Step 0 reads.
               detail: (if $issue_no != null
                        then "/implement-issue \($issue_no) — Step 0 re-enters at the review loop and drives it to gh pr ready"
                        else "/implement-issue \(.number) — the PR number; no linked issue (TODO item or refactor)" end)}
         end)
    ]

  | {
      due: length,
      by_action: (group_by(.action) | map({key: .[0].action, value: length}) | from_entries),
      actions: sort_by(.action, (.issue // .pr)),
      # The PRs suppressed by a board decision, reported as a COUNT AND A LIST
      # rather than dropped. Silently vanishing would trade one failure for
      # another: the point is to stop re-asking about a settled decision, not
      # to lose the item. The reason travels with it so a later reader can see
      # WHICH decision is doing the suppressing without opening the board.
      deferred: [
        $prs[]
        | . as $p
        | ([ $pr_board[] | select(.number == $p.number) ] | first) as $c
        | select(($c.awaiting // null) != null or ($c.priority // null) == "P4")
        # Mirrors the mark_ready carve-out above: a deferred PR that is APPROVED
        # and still a draft is NOT deferred, it is reported, so it must not be
        # counted here as well.
        | select((.isDraft
                  and .mergeable != "CONFLICTING"
                  and ([ .statusCheckRollup[]?
                         | select((.conclusion // "") != "SUCCESS"
                                  and (.conclusion // "") != "SKIPPED"
                                  and (.conclusion // "") != "NEUTRAL") ] | length == 0)
                  and (.reviewDecision == "APPROVED"
                       or (([ .reviews[]? | select(.state != "COMMENTED") ] | last | .state?) == "APPROVED"
                           and .reviewDecision != "CHANGES_REQUESTED"))) | not)
        | {pr: .number,
           why: (if ($c.awaiting // null) != null
                 then "awaiting \($c.awaiting)"
                 else "priority P4" end)}
      ]
    }
')

if [ "$as_json" = true ]; then
    printf '%s\n' "$actions"
    exit 0
fi

# Built with explicit concatenation rather than jq string interpolation: a
# `\(...)` inside a `$(...)` command substitution confuses bash's paren
# matching and fails to parse the script at all.
deferred_line=$(printf '%s' "$actions" | jq -r '.deferred
  | if length == 0 then ""
    else "  deferred: " + (length | tostring) + " ("
         + (map("#" + (.pr | tostring) + " " + .why) | join("; ")) + ")"
    end')

due=$(printf '%s' "$actions" | jq -r '.due')
if [ "$due" -eq 0 ]; then
    echo "RHYTHM: nothing due."
    [ -n "$deferred_line" ] && printf '%s\n' "$deferred_line"
    exit 0
fi

echo "RHYTHM: $due action(s) due"
printf '%s' "$actions" | jq -r '
  "",
  (.by_action | to_entries | map("  \(.key): \(.value)") | join("\n")),
  "",
  (.actions[] | "  \(if .pr then "PR #\(.pr)" else "##\(.issue)" end) \(.action)\n      why: \(.why)\n      do : \(.detail)")
'
[ -n "$deferred_line" ] && printf '\n%s\n' "$deferred_line"
exit 0
