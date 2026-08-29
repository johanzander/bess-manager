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

# FLOW POLICY: the WIP limit. 3 is deliberately aggressive -- with 7 in flight
# it keeps dispatch shut until the fleet drains to 2, which is the point. A
# variable so the tests can drive the boundary.
WIP_LIMIT="${RHYTHM_WIP_LIMIT:-3}"

# FLOW POLICY: the Analysis WIP limit. The same "empty the board from the right"
# rule one column further left -- analysis is only useful once its output
# reaches Ready for Dev, so an Analysis column carrying 18 items is 18 pieces of
# half-finished work, not progress. At or above this, the pass stops pulling new
# items in: `autonomous_analyze` is suppressed (still counted and listed, like a
# deferred PR) and the pass reports `ANALYSIS n/limit` on every path. It does
# NOT gate `refire_analyze` -- re-poking a Stage 2 run that never completed
# finishes an item already in Analysis rather than adding one.
ANALYSIS_WIP_LIMIT="${RHYTHM_ANALYSIS_WIP_LIMIT:-8}"

# How long a `@claude-bot analyze` trigger may sit with the item still
# `ready-for-analysis` and unstamped before the pass treats the run as failed
# and re-fires it. Stage 2 normally completes in minutes; the common cause of a
# no-op run is the workflow being out of API credit, which a later re-fire
# clears on its own -- so this is a loop retry, not a maintainer escalation.
ANALYZE_STALE_HOURS="${RHYTHM_ANALYZE_STALE_HOURS:-6}"

# TOOLING FRESHNESS. The board data this pass reads is always live (gh API),
# but the pass ITSELF -- this script, backlog-digest.sh and the backlog
# SKILL.md -- runs from whatever checkout the loop was started in, and that is
# never refreshed mid-loop. The local `main` checkout is routinely stale, so a
# long-running `/loop /backlog` can be executing week-old logic without a hint
# of it. A read-only fetch plus a behind-count against origin/main for the
# tooling paths makes it visible on every path, the same way `WIP n/3` does --
# it never pulls (wrong in a worktree, and swapping the skill under a live tick
# is worse than running one tick stale). `RHYTHM_SKIP_FETCH=1` skips only the
# network call and compares against whatever origin/main is already local;
# `RHYTHM_TOOLING_REF` overrides the ref. Skipped entirely under the test seam.
TOOLING_REF="${RHYTHM_TOOLING_REF:-origin/main}"
tooling_behind=null
if [ -z "${RHYTHM_DIGEST_FILE:-}" ] \
   && root=$(git -C "$here" rev-parse --show-toplevel 2>/dev/null); then
    if [ -z "${RHYTHM_SKIP_FETCH:-}" ]; then
        git -C "$root" fetch --quiet "${TOOLING_REF%%/*}" 2>/dev/null || true
    fi
    if git -C "$root" rev-parse --verify --quiet "$TOOLING_REF" >/dev/null 2>&1; then
        tooling_behind=$(git -C "$root" rev-list --count \
            "HEAD..$TOOLING_REF" -- \
            scripts/backlog-digest.sh scripts/backlog-rhythm.sh \
            .claude/skills/backlog/ 2>/dev/null || echo null)
    fi
fi

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
# The repo owner is the maintainer for the tier-1 carve-out: an issue opened
# by anyone else is an external report, and external bug reports with a debug
# log are exactly what the autonomous Stage 2 spend is for.
owner="${repo%%/*}"
if [ -n "${RHYTHM_PRS_FILE:-}" ]; then
    prs=$(cat "$RHYTHM_PRS_FILE")
else
    prs=$(gh pr list --repo "$repo" --state open --limit 100 \
        --json number,title,isDraft,mergeable,reviewDecision,reviews,author,statusCheckRollup)
fi

actions=$(printf '%s' "$digest" | jq \
    --argjson nudge "$NUDGE_DAYS" \
    --argjson park "$PARK_DAYS" \
    --argjson wip_limit "$WIP_LIMIT" \
    --argjson analysis_wip_limit "$ANALYSIS_WIP_LIMIT" \
    --argjson analyze_stale_hours "$ANALYZE_STALE_HOURS" \
    --argjson tooling_behind "$tooling_behind" \
    --arg tooling_ref "$TOOLING_REF" \
    --argjson prs "$prs" \
    --arg owner "$owner" '
  # Board cards for PRs, keyed by number. Absent on an older digest, so this
  # defaults to empty rather than failing -- a rhythm run against a stale
  # digest then simply defers nothing, which is the pre-existing behaviour.
  (.pr_board // []) as $pr_board
  |

  # In Progress and In Review are ONE piece of work at two stages -- a branch
  # and its PR. Counting them separately would silently double the limit.
  ([ .items[] | select(.column == "In Progress" or .column == "In Review") ] | length) as $wip
  | ($wip >= $wip_limit) as $over_wip
  |

  # The Analysis column, counted the same way -- one flow-policy step to the
  # left of the dispatch WIP limit. At or above the limit, no new item enters
  # analysis until analysed ones are promoted to Ready for Dev.
  ([ .items[] | select(.column == "Analysis") ] | length) as $analysis_wip
  | ($analysis_wip >= $analysis_wip_limit) as $analysis_over
  |

  # The collision gate. $in_flight is the EXACT half -- every open PRs
  # changed-file set, always an object, {} when there are no open PRs (Task
  # 5). $undiffable is non-empty when gh pr diff failed for at least one open
  # PR (backlog-digest.sh); when it is, the in-flight set is known to be
  # INCOMPLETE, so collision cannot be safely evaluated for anything, and
  # dispatch is held fleet-wide the same way over-WIP holds it.
  (.in_flight_files // {}) as $in_flight
  | (.undiffable_prs // []) as $undiffable
  | (($undiffable | length) > 0) as $collision_unknown
  |

  # Quiet time is measured from the LAST COMMENT, not from updatedAt. A label
  # change, a board move or a bot touch all bump updatedAt, so an issue nobody
  # has spoken on for a month can look active and never age into a chase.
  def quiet_days: if .last_comment == null then .age_days else .last_comment.days end;

  # TIER-1 READY: the evidence basis for the autonomous Stage 2 carve-out
  # below, and (negated) the suppressor of the reporter/discussion chases for
  # the same items. Every condition is EVIDENCE, never the board field: the
  # three label checks are triage and Stage 2 stamps (bug confirmed,
  # ready-for-analysis = the debug log is attached, and no analyzed or
  # needs-human-review label = no Stage 2 history), the author check is the
  # external-reporter bar, and the awaiting check keeps a deliberate
  # `maintainer` hold from being overridden by the carve-out.
  def tier1_ready: (.labels | index("bug")) != null
     and (.labels | index("ready-for-analysis")) != null
     and (.labels | index("analyzed")) == null
     and (.labels | index("needs-human-review")) == null
     and .author != $owner
     and .awaiting != "maintainer";

  (.items) as $items
  | [ $items[]
    | . as $i

    # ESCALATION IS SIGNED AWAITING, POINTED THE OTHER WAY. Every other value
    # means someone else owes us and correctly goes quiet; `maintainer` means
    # the loop cannot advance without a decision, so it must be the loudest
    # thing in the pass. An escalation that ranks by column is an escalation
    # that waits, which defeats the valve.
    | (if .awaiting == "maintainer"
     then {issue: .number, action: "escalated",
           why: "awaiting the maintainer",
           detail: "read the open question on the issue and decide; or send it back to Analysis"}
     else empty end),

    # A session that died twice is telling you something. Nothing counted
    # before, so `resume_implementation` was re-reported forever on work that
    # had already failed twice.
    #
    # Unless the work has since LANDED (#707): #683 was handed back twice, then
    # a third, reframed attempt merged as PR #686. `resume_count` never
    # decrements, so the escalation kept firing on a fix that is already on
    # main. A merged PR for the issue means the handbacks are history, not a
    # live "not implementable" signal.
    (if .resume_count >= 2 and .merged_pr == null
     then {issue: .number, action: "escalated",
           why: "\(.resume_count) implementation sessions have been handed back",
           detail: "the item is not implementable as specified -- decide, or send it back to Analysis"}
     else empty end),

    # The reporter answered us. This is the transition that matters most and
    # the one the digest could not previously see: a wait on the reporter may
    # now be satisfied, so the Definition of Ready needs re-checking. It is
    # listed before the chases on purpose — chasing someone who has already
    # replied is the worst output this pass could produce.
    (if .awaiting == "reporter" and (.last_comment.is_reporter // false)
       then {issue: .number, action: "recheck_ready",
             why: "reporter replied \(.last_comment.days)d ago while awaiting them",
             detail: "re-check Definition of Ready; clear Awaiting if satisfied"}
       else empty end),

    # Chase once, then park. `is_reporter` false means the last word was ours,
    # so the ball is still with them.
    #
    # AN OPEN PR SUPPRESSES BOTH, and that is not a nicety -- parking one
    # OSCILLATES. `park` says move the card to Backlog; the column derivation
    # says an item with an open PR is In Review; so the next pass reports
    # `move_card` to put it back, and the pass after that parks it again,
    # forever. #162 did exactly this: parked at 55 quiet days, immediately
    # reported as a mis-placed card, restored, parked again.
    #
    # The rule is right underneath the loop, too. An issue with a PR in flight
    # is not a reporter chase whatever its `Awaiting` says: the work exists,
    # and the wait that matters is the PR review, which the PR half of this
    # pass already reports. Nudging the reporter of a 46-day-stale conflicted
    # PR asks the wrong person about the wrong thing.
    #
    # A TIER-1 BUG SUPPRESSES THEM TOO, for the opposite reason. When triage
    # has stamped `ready-for-analysis`, the ball is not with the reporter: the
    # debug log is attached and the item is waiting on analysis, not on them.
    # Chasing or parking it would bury the exact bug the autonomous carve-out
    # exists to surface (#681/#680) -- the stale `Awaiting` field and the
    # evidence contradict, and the evidence wins. `tier1_ready` is the same
    # check the carve-out uses, so the carve-out and the chases can never
    # contradict each other in one pass.
    (if (.prs | length) > 0 then empty
     elif .awaiting == "reporter"
        and (tier1_ready | not)
        and ((.last_comment.is_reporter // false) | not)
        and quiet_days >= $park
     then {issue: .number, action: "park",
           why: "awaiting reporter, quiet \(quiet_days)d (>= \($park))",
           detail: "move to Backlog; the chase has gone unanswered"}
     elif .awaiting == "reporter"
        and (tier1_ready | not)
        and ((.last_comment.is_reporter // false) | not)
        and quiet_days >= $nudge
     then {issue: .number, action: "nudge_reporter",
           why: "awaiting reporter, quiet \(quiet_days)d (>= \($nudge))",
           detail: "nudge once, as the PO identity"}
     else empty end),

    # A discussion nobody has advanced is a question for the maintainer, not a
    # reason to keep waiting. Never auto-parked: an open conversation is not
    # the same as an unanswered chase. A tier-1 bug is never this -- putting an
    # open question to the maintainer contradicts spending on analysing it in
    # the same pass, so the carve-out suppresses it.
    (if .awaiting == "discussion" and (tier1_ready | not) and quiet_days >= $nudge
     then {issue: .number, action: "surface_discussion",
           why: "discussion stalled \(quiet_days)d",
           detail: "summarise the thread and put the open question to the maintainer"}
     else empty end),

    # THE ONE UNBUDGETED SPEND THIS PASS MAY FIRE WITHOUT ASKING: the
    # autonomous Stage 2 carve-out, checked against EVIDENCE not the board
    # field. `tier1_ready` above is all evidence: `ready-for-analysis` is the
    # debug-log stamp triage applies, the absent `analyzed` /
    # `needs-human-review` labels mean the item has no Stage 2 history (triage
    # re-stamps `ready-for-analysis` on an edit even after an inconclusive
    # run, so coexisting labels would otherwise re-fire the spend on items
    # analysis has already settled), a non-maintainer author is the
    # external-report bar, and a deliberate `Awaiting: maintainer` hold beats
    # the carve-out -- the loop cannot advance without a decision there, so
    # the spend is not the point.
    #
    # The `Awaiting` field must NOT gate this: it can go stale (a card left at
    # `reporter` after the reporter supplied the log) and hide the item from
    # the pass entirely -- the #681/#680 failure, where the carve-out was only
    # ever evaluated on items the pass surfaced. Stage 2 removes
    # `ready-for-analysis` when it runs, so this fires at most until analysis
    # lands.
    #
    # The no-prior-analyze check is now IN THE SCRIPT (`last_analyze_comment`),
    # not left to the PO to remember: `autonomous_analyze` fires only when the
    # issue has never been analyzed. A prior trigger that is still in flight
    # (younger than the staleness window) means neither this nor `refire_analyze`
    # fires -- the pass simply waits. `$analysis_over` suppresses it too: the
    # Analysis column is full, so nothing new is pulled in until analysed items
    # reach Ready for Dev (the item stays visible in `analysis_wip` below).
    (if tier1_ready and .last_analyze_comment == null and ($analysis_over | not)
     then {issue: .number, action: "autonomous_analyze",
           why: "tier-1 bug: \(.author), debug log attached, no analyzed/needs-human-review label, never analyzed",
           detail: "fire Stage 2 as the PO: scripts/gh-agent.sh --as po issue comment \(.number) --body \"@claude-bot analyze\""}
     elif tier1_ready and .last_analyze_comment == null and $analysis_over
     then {issue: .number, action: "analysis_deferred",
           why: "tier-1 bug ready to analyse, held: Analysis WIP \($analysis_wip)/\($analysis_wip_limit)",
           detail: "do not fire Stage 2 -- promote an analysed item to Ready for Dev first; this re-proposes once Analysis is under the limit"}
     else empty end),

    # A Stage 2 run that never landed. `tier1_ready` still holds (Stage 2 would
    # have removed `ready-for-analysis` and stamped a label), a `@claude-bot
    # analyze` trigger is on the issue, and it has aged past the staleness
    # window -- so the workflow accepted the trigger and produced nothing,
    # almost always because it had no API credit at the time. Under `/loop`
    # this is a plain retry: re-post the trigger as the PO. NOT a maintainer
    # escalation, and not gated by `$analysis_over` -- the item is already in
    # Analysis, this finishes it rather than adding new work.
    (if tier1_ready
        and .last_analyze_comment != null
        and (.last_analyze_comment.hours >= $analyze_stale_hours)
        and ((.prs | length) == 0)
     then {issue: .number, action: "refire_analyze",
           why: "@claude-bot analyze fired \(.last_analyze_comment.hours)h ago, still ready-for-analysis with no analyzed/needs-human-review label -- Stage 2 did not complete",
           detail: "re-fire as the PO (a no-op run is usually an out-of-credit workflow; the loop retries): scripts/gh-agent.sh --as po issue comment \(.number) --body \"@claude-bot analyze\""}
     else empty end),

    # Grooming debt: the board field is unset while a label implies a wait, so
    # the authoritative value is missing and only the label is holding it.
    (if .awaiting != null and .awaiting_source == "label"
     then {issue: .number, action: "set_awaiting",
           why: "labels imply awaiting=\(.awaiting_suggested) but the board field is empty",
           detail: "set Awaiting on the card"}
     else empty end),

    # Grooming debt: the board field still says `analysis` -- the placeholder
    # for "needs Stage 2" -- on an item Stage 2 has demonstrably finished (the
    # `analyzed` or `needs-human-review` label is on). `analysis` is not a real
    # wait; the skill calls it a triage gap. Nothing else contradicts an
    # explicitly-set board value, so a stale one silently pins the item in the
    # Analysis column forever -- #680 and #704 sat here, analysed weeks ago,
    # invisible to every pass because `awaiting_source == "board"`.
    (if .awaiting == "analysis" and .awaiting_source == "board"
        and ((.labels | index("analyzed")) != null
             or (.labels | index("needs-human-review")) != null)
     then {issue: .number, action: "set_awaiting",
           why: "board Awaiting=analysis but Stage 2 is done (analyzed/needs-human-review label present) -- a stale placeholder pinning the item in Analysis",
           detail: "re-point Awaiting at the real wait (reporter/discussion/upstream), or clear it if the item is ready for dev"}
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

    # Un-pruned worktrees are what made four issues read as In Progress. The
    # branch is dead either because it merged or because its PR was closed
    # unmerged -- `stale_worktree_reason` from the digest says which.
    (if .stale_worktree
     then {issue: .number, action: "prune_worktree",
           why: "worktree \(.worktree_branch) \(.stale_worktree_reason // "already landed")",
           detail: "hand to sweep-prs"}
     else empty end),

    # IN VERIFICATION IS BOARD-ONLY (#707). The column says the fix is on main
    # and in a beta build, awaiting a stable release -- but that lives in a
    # Project field the reporter cannot see. #683 sat here for weeks with no
    # label and no status comment on the issue itself; a reporter reading it
    # saw only stale WIP notes. Fire ONCE per issue: post the fix-status
    # comment as the PO and apply `awaiting-release`, which then suppresses
    # this on every later tick. Closing still waits for the graduation PR.
    (if .column == "In Verification"
        and ((.labels | index("awaiting-release")) | not)
     then {issue: .number, action: "announce_verification",
           why: "In Verification (fix in #\(.merged_pr // 0) is on main / in beta) but the issue carries no visible fix-status signal",
           detail: "as the PO, comment the fix status (merged in #\(.merged_pr // 0), shipped in beta, closes on the stable release) and apply the `awaiting-release` label"}
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
    (if .worktree != null and (.stale_worktree | not) and (.worktree_locked | not) and .session == null and (.prs | length) == 0 and .resume_count < 2
     then {issue: .number, action: "resume_implementation",
           why: "worktree \(.worktree_branch) on disk, unlocked, no live session",
           detail: "/implement-issue \(.number) — Step 0 resumes it; never restart, the branch commits are the only copy"}
     else empty end),

    # FLOW POLICY RULE 3: NOTHING STARTS THAT COLLIDES. The in-flight half is
    # exact (every open PR changed-file set); only the candidate half is
    # predicted, and a candidate with no prediction is not dispatchable -- a
    # proposal that cannot be checked is a proposal to find out by colliding.
    # $collision_unknown holds dispatch shut fleet-wide, same as $over_wip --
    # one undiffable PR means the in-flight set may be missing entries, so no
    # candidate can be safely cleared against it.
    (if .column != "Ready for Dev" or $over_wip or $collision_unknown then empty
     elif (.predicted_files | length) == 0
     then {issue: .number, action: "needs_touch_set",
           why: "Ready for Dev but no predicted touch-set",
           detail: "name the files from the Stage 2 analysis; no touch-set, no dispatch"}
     else
       ([ .predicted_files[] | select($in_flight[.] != null) ]) as $clash
       | ([ $items[] | select(.number != $i.number
                              and .column == "Ready for Dev"
                              and ((.predicted_files // []) | any(. as $f | ($i.predicted_files | index($f))))) ]
          | map(.number)) as $peers
       | if ($clash | length) > 0
         then {issue: .number, action: "queued_behind",
               why: "touches \($clash | join(", ")) which is already in flight",
               detail: "wait for the in-flight PR to land, or fold this into it"}
         elif ($peers | length) > 0
         then {issue: .number, action: "cluster",
               why: "overlaps Ready item(s) \($peers | map("#" + (. | tostring)) | join(", "))",
               detail: "dispatch them as ONE unit of work -- one branch, one PR"}
         else {issue: .number, action: "dispatchable",
               why: "Ready for Dev, priority \(.priority), no file collision",
               detail: "meets Definition of Ready; propose for dispatch"}
         end
     end)
  ]

  # $undiffable turns into one fleet-level action per PR, mirroring how the
  # WIP limit is reported as a count rather than folded silently into the
  # per-item rules. Named alongside the PR-side actions below so it ranks
  # with work in flight (rank 2), not the unranked catch-all.
  + [ $undiffable[]
      | {pr: ., action: "undiffable_pr",
         why: "gh pr diff failed for this PR; the in-flight file set is incomplete",
         detail: "dispatch is held for every Ready for Dev item until this PR diffs cleanly -- rerun the digest"}
    ]

  # A CARD whose issue or PR is no longer open (#707 / #638). The digest
  # surfaces these in `orphans` because `items` iterates only the open-issue
  # list and `pr_board` is joined only against the OPEN-PR list, so a stale
  # card is reconciled by nothing otherwise -- it just sits in whatever column
  # it was last in (#638 sat in In Review after its draft closed). Ranked with
  # the grooming/board actions.
  + [ (.orphans // [])[]
      | select(.kind == "stale_pr_card")
      | {pr: (.ref | tonumber), action: "archive_pr_card",
         why: .detail,
         detail: "move the card to Done (merged) or delete it (closed unmerged) -- a PR card only carries a deferral while its PR is open"}
    ]
  + [ (.orphans // [])[]
      | select(.kind == "stale_issue_card")
      | {issue: (.ref | tonumber), action: "move_card",
         why: .detail,
         detail: "move the card to Done -- the issue is closed"}
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
      | ([ $items[] | select(.prs | map(.number) | index($p.number)) | .number ] | first) as $issue_no
      # The board card belonging to this PR, if it has one. This is what lets a
      # decision about a PR be recorded once instead of re-argued every tick.
      #
      # NOTE: no apostrophes anywhere in this jq program. It is a single-quoted
      # shell string, so one apostrophe in a comment ends it early and bash
      # fails with "unexpected EOF while looking for matching )" pointing at the
      # top of the block rather than at the comment.
      | ([ $pr_board[] | select(.number == $p.number) ] | first) as $card
      # The issue card belonging to this PR, if the PR resolves to one. This
      # is the current, documented home for a deferral decision (backlog
      # SKILL.md "One card per unit of work, on the issue -- PR cards go
      # away"): `Awaiting`/`Priority` live on the issue, not on a separate PR
      # card, so a PO following that doc records a deferral where $card above
      # never looks. Support BOTH -- an issue-side deferral and a pr_board
      # one -- rather than picking one, so a later removal of PR cards is a
      # safe no-op instead of an ordering trap: with only $card suppression,
      # deleting PR cards would silently un-park every deferred PR.
      | ([ $items[] | select(.number == $issue_no) ] | first) as $issue_item
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
      | (($card.awaiting // null) != null or ($card.priority // null) == "P4"
         or ($issue_item.awaiting // null) != null
         or ($issue_item.priority // null) == "P4") as $deferred
      # Three CHANGES_REQUESTED rounds without an intervening approval is a
      # design disagreement, not something a fourth round will settle -- the
      # same cap `implement-issue` already enforces. Computed here, ahead of
      # $approved_draft, so it can chain as an elif and never also report
      # resume_implementation for the same PR.
      | ([ .reviews[]? | select(.state == "CHANGES_REQUESTED") ] | length) as $rounds
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
      | (if $rounds >= 3
         then {pr: .number, action: "escalated",
               why: "\($rounds) CHANGES_REQUESTED rounds without an approval",
               detail: "the reviewer and the implementer disagree about the design; another round will not settle it"}
         elif $approved_draft
         then {pr: .number, action: "mark_ready",
               why: "APPROVED and green, still a draft — Step 11 never ran gh pr ready",
               # Route through advance-pr, not a bare `gh pr ready`: this is
               # the one call site an unattended pass actually reads, and a
               # raw command here skips advance-prs mandatory mergeability
               # re-check and the push-after-approval rule -- the #609
               # failure, re-opened right here if this string ever names the
               # command instead of the skill.
               detail: "/advance-pr \(.number) — then it is the maintainers to merge"}
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
               # A CONFLICTING draft is advance-prs own row 1/2 (textual ->
               # merge+resolve, semantic -> abort+escalate) and only
               # advance-pr performs the board write that records a semantic
               # conflict escalation -- sweep-prs reports into a chat
               # transcript and writes nothing, so handing a draft to
               # sweep-prs re-emitted this same action forever. A conflicted
               # NON-draft PR is not advance-prs concern (it already left the
               # review loop), so that one still routes to sweep-prs.
               detail: (if .isDraft
                        then "/advance-pr \(.number)"
                        else "hand to sweep-prs, or resolve if the diff is ours" end)}
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
         # EVERY REMAINING DRAFT SHAPE ROUTES BY VERDICT, not to one blanket
         # handoff. That blanket handoff used to be the whole content of this
         # branch, and it was the gap between this design and its own headline
         # promise: advancing a PR costs a step, not a session. Splitting it
         # is what closes that gap.
         #
         # The verdict check reuses the EXACT seam the out-of-draft branch
         # above already uses, never a second way of reading one: trust
         # `reviewDecision` when set, else fall back to the LAST non-COMMENTED
         # review, never to any review, because GitHub never rewrites a stale
         # `APPROVED`.
         else ([ .reviews[]? | select(.state != "COMMENTED") ] | last | .state?) as $draft_verdict
              | ((.reviewDecision == "CHANGES_REQUESTED")
                 or (.reviewDecision == "" and $draft_verdict == "CHANGES_REQUESTED")
                 or (.reviewDecision == null and $draft_verdict == "CHANGES_REQUESTED")) as $draft_changes_requested
              | (if $draft_changes_requested
                 then {pr: .number, issue: $issue_no, action: "resume_implementation",
                       why: "draft PR carrying CHANGES_REQUESTED",
                       # DRAFT, CHANGES_REQUESTED STAYS ON implement-issue. Only that
                       # session holds the Step 2 diagnosis and the Step 3 scope
                       # assessment -- the one thing that tells a real review finding
                       # apart from a decision Step 3 already made and rejected on
                       # purpose (see advance-pr, "this skill never touches the diff").
                       # advance-pr itself now always hands a CHANGES_REQUESTED draft
                       # back to implement-issue too, whatever caller invoked it --
                       # dispatching straight to implement-issue here from the rhythm
                       # pass just skips the redundant round trip through advance-pr.
                       #
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
                                then "/implement-issue \($issue_no) — Step 0 re-enters at Step 11, which holds the Step 2/3 context, reworks it in this session, then calls advance-pr for the next transition"
                                else "/implement-issue \(.number) — the PR number; no linked issue (TODO item or refactor)" end)}
                 # EVERY OTHER DRAFT SHAPE IS MECHANICAL: no review yet, a review
                 # still in flight, or an approved draft whose checks are not green
                 # yet. None of that needs the Step 2/3 context CHANGES_REQUESTED
                 # does, so it goes straight to the one-copy loop instead of a whole
                 # session: request the review, resolve a conflict, or flip it ready,
                 # then exit.
                 else {pr: .number, action: "resume_implementation",
                       why: "draft PR, next step is mechanical",
                       detail: "/advance-pr \(.number) — requests the review, resolves a conflict, or flips it ready in one cheap step"}
                 end)
         end)
    ]

  # FLOW POLICY RULE 1: EMPTY THE BOARD FROM THE RIGHT. Finish started work
  # before starting new work, so actions rank by the column of the item they
  # serve, rightmost first. Escalations sit above all of it -- see Task 6.
  #
  # This replaces a plain alphabetical sort, which ranked dispatchable above
  # resume_implementation for no reason beyond d < m < r, and so led every
  # pass with start new work.
  | map(. + {rank:
      (if .action == "escalated" then 0
       # In Verification sits right after escalations in the flow-policy
       # ladder ("graduate: cut the release, close the issue") -- landed work,
       # above the PRs still in flight at rank 2.
       elif .action == "announce_verification" then 1
       elif .action == "mark_ready" or .action == "awaiting_maintainer"
            or .action == "request_review" or .action == "rework_review"
            or .action == "resolve_conflict" or .action == "undiffable_pr" then 2
       elif .action == "resume_implementation" or .action == "prune_worktree" then 3
       elif .action == "dispatchable" or .action == "queued_behind"
            or .action == "cluster" or .action == "needs_touch_set" then 4
       # refire_analyze finishes an Analysis item that stalled; it ranks with
       # the other Analysis-column actions. (A given item is either this or
       # autonomous_analyze, never both -- a prior analyze comment decides.)
       elif .action == "recheck_ready" or .action == "surface_discussion"
            or .action == "nudge_reporter" or .action == "park"
            or .action == "refire_analyze"
            or .action == "autonomous_analyze" then 5
       elif .action == "set_awaiting" or .action == "add_card"
            or .action == "set_priority" or .action == "move_card"
            or .action == "archive_pr_card" or .action == "analysis_deferred"
            or .action == "triage_labels" then 6
       # Rank 9 is not a column. It is the catch-all for an action name
       # this function does not know about -- its rank branch is missing,
       # most likely because a later task added an action and forgot to
       # name it here. It sorts after every named rank, including the
       # rank 6 grooming actions, so a gap like that is conspicuous in the
       # output instead of quietly blending into last place.
       else 9 end)})

  | {
      due: length,
      wip: {count: $wip, limit: $wip_limit, over: $over_wip},
      # The Analysis column against its own WIP limit, reported the same way and
      # for the same reason as `wip`: when the pass pulls nothing new into
      # analysis, the operator needs to see it is because the column is full.
      analysis: {count: $analysis_wip, limit: $analysis_wip_limit, over: $analysis_over},
      # Commits on `$tooling_ref` not in HEAD that touch the backlog scripts or
      # SKILL.md -- i.e. how far behind the logic running right now is. null
      # when the check was skipped (test seam, not a git repo, ref not present,
      # or the fetch/rev-list failed). Reported on every path like `wip`.
      tooling: {behind: $tooling_behind, ref: $tooling_ref},
      # PRs whose diff could not be read this pass -- see $collision_unknown
      # above. Reported the same way $wip is: a count and the list, on every
      # path, because a suppressed dispatch queue that does not say why is
      # the failure this exists to prevent.
      undiffable: $undiffable,
      by_action: (group_by(.action) | map({key: .[0].action, value: length}) | from_entries),
      actions: sort_by(.rank, .action, (.issue // .pr)),
      # The PRs suppressed by a board decision, reported as a COUNT AND A LIST
      # rather than dropped. Silently vanishing would trade one failure for
      # another: the point is to stop re-asking about a settled decision, not
      # to lose the item. The reason travels with it so a later reader can see
      # WHICH decision is doing the suppressing without opening the board.
      deferred: [
        $prs[]
        | . as $p
        | ([ $pr_board[] | select(.number == $p.number) ] | first) as $c
        # Same issue-side lookup as the actions block above: a deferral
        # recorded on the issue card (per backlog SKILL.md, the documented
        # home) must show up here too, not only a pr_board deferral.
        | ([ $items[] | select(.prs | map(.number) | index($p.number)) ] | first) as $issue_item
        | select(($c.awaiting // null) != null or ($c.priority // null) == "P4"
                 or ($issue_item.awaiting // null) != null
                 or ($issue_item.priority // null) == "P4")
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
                 elif ($c.priority // null) == "P4"
                 then "priority P4"
                 elif ($issue_item.awaiting // null) != null
                 then "issue awaiting \($issue_item.awaiting)"
                 else "issue priority P4" end)}
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

# Reported on every path, including "nothing due" -- a suppressed dispatch
# queue is exactly the moment the operator needs to know why the pass looks
# empty.
wip_line=$(printf '%s' "$actions" | jq -r '.wip
  | if .over then "  WIP " + (.count|tostring) + "/" + (.limit|tostring)
                  + " -- finish before starting; dispatch suppressed"
    else "  WIP " + (.count|tostring) + "/" + (.limit|tostring) end')

# Same contract as $wip_line: printed on every path, including "nothing due", so
# a pass that pulls nothing new into analysis says why.
analysis_line=$(printf '%s' "$actions" | jq -r '.analysis
  | if .over then "  ANALYSIS " + (.count|tostring) + "/" + (.limit|tostring)
                  + " -- promote analysed items to Ready for Dev before analysing more"
    else "  ANALYSIS " + (.count|tostring) + "/" + (.limit|tostring) end')

# Also every-path: the logic running this tick is behind origin/main. Empty
# unless the check ran AND found the backlog tooling stale -- a fresh or
# skipped check says nothing.
tooling_line=$(printf '%s' "$actions" | jq -r '.tooling
  | if (.behind // 0) > 0
    then "  TOOLING " + (.behind|tostring) + " commit(s) behind " + .ref
         + " -- restart the loop from an updated checkout"
    else "" end')

# Also reported on every path, same reasoning as $wip_line: a non-empty
# undiffable set silently holds every dispatchable action shut, and that is
# exactly the moment the operator needs to be told why.
undiffable_line=$(printf '%s' "$actions" | jq -r '.undiffable
  | if length == 0 then ""
    else "  undiffable PRs: " + (map("#" + (. | tostring)) | join(", "))
         + " -- collision cannot be evaluated; dispatch suppressed"
    end')

due=$(printf '%s' "$actions" | jq -r '.due')
if [ "$due" -eq 0 ]; then
    echo "RHYTHM: nothing due."
    printf '%s\n' "$wip_line"
    printf '%s\n' "$analysis_line"
    [ -n "$tooling_line" ] && printf '%s\n' "$tooling_line"
    [ -n "$undiffable_line" ] && printf '%s\n' "$undiffable_line"
    [ -n "$deferred_line" ] && printf '%s\n' "$deferred_line"
    exit 0
fi

echo "RHYTHM: $due action(s) due"
printf '%s\n' "$wip_line"
printf '%s\n' "$analysis_line"
[ -n "$tooling_line" ] && printf '%s\n' "$tooling_line"
[ -n "$undiffable_line" ] && printf '%s\n' "$undiffable_line"
printf '%s' "$actions" | jq -r '
  "",
  (.by_action | to_entries | map("  \(.key): \(.value)") | join("\n")),
  "",
  (.actions[] | "  \(if .pr then "PR #\(.pr)" else "##\(.issue)" end) \(.action)\n      why: \(.why)\n      do : \(.detail)")
'
[ -n "$deferred_line" ] && printf '\n%s\n' "$deferred_line"
exit 0
