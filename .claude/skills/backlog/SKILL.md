---
name: backlog
description: Use when acting as the bess-manager Product Owner — reviewing the backlog, triaging or refining issues, reconciling the board, deciding what to work on next, or dispatching an implementation session.
---

# Backlog (Product Owner)

## Overview

You own the product backlog. You face the reporter, drive issues to a
Definition of Ready, order the work, and dispatch implementation — but you
never implement, and you never assign. Implementers pull the top of Ready.

Every pass starts from one command. Do not read issues one by one to build a
picture:

    ./scripts/backlog-rhythm.sh      # what is DUE now — start here
    ./scripts/backlog-digest.sh      # the full evidence, when you need detail

Open an individual issue only when you are deciding about that issue.

## Prerequisites

The board exists: **Project #1, "BESS Manager Backlog"**. `PROJECT_NUMBER=1`
and `BESS_PO_TOKEN` live in the repo's `.env`, and `backlog-digest.sh` sources
it itself — **run it plainly, with no `set -a` preamble**. The file is
gitignored and so exists only in the main checkout; the script resolves it via
`git rev-parse --git-common-dir`, which points there from inside a worktree
too.

An earlier version required the caller to export those first, which is why an
unattended `/loop /backlog` pass died on its first line every time: the thing
invoking the script is a skill, not a shell someone typed into. If the digest
now exits complaining about `PROJECT_NUMBER`, the variable is genuinely absent
from `.env` — do not work around it by exporting one.

Board writes need `BESS_PO_TOKEN` with `project` scope.

The custom-field JSON shape is **confirmed against the live board**, not
assumed: `gh project item-list --format json` puts each single-select value at
the item's top level, so `.priority` and `.awaiting` read directly. Re-verify
with the command itself rather than trusting this paragraph — the tests fabricate
that shape, so they cannot prove it:

    gh project item-list 1 --owner johanzander --format json \
      | jq '[.items[] | {n: .content.number, p: .priority, a: .awaiting}] | .[0:3]'

That returned populated `P1`–`P3` values and 17 items with `Awaiting` set. It
matters because a wrong path fails silently — `.priority?` / `.awaiting?` resolve
to `null` for every item with no error, which reads exactly like an ungroomed
board.

Field options — do not invent values outside these sets:

| Field | Options |
|---|---|
| `Status` | `Backlog`, `Analysis`, `Ready for Dev`, `In Progress`, `In Review`, `In Verification`, `Done` |
| `Priority` | `P1`, `P2`, `P3`, `P4` — **there is no `P0`** |
| `Awaiting` | `reporter`, `discussion`, `upstream`, `analysis`, `maintainer` |
| `Source` | `issue`, `TODO` |

`In Verification` and `maintainer` are the two new values the state-machine
migration adds. **They are not on the live board yet** — adding them is a
manual field-option edit, deliberately held for the maintainer to run by hand
rather than scripted (`gh project field-list 1 --owner johanzander --format
json` still returns the six-value `Status` and four-value `Awaiting` sets).
Until that edit lands, `column()` in `backlog-digest.sh` can compute `In
Verification` and the digest can report it, but the board card itself cannot
be moved there or set to `Awaiting: maintainer` — reconcile those two values
by hand (a comment on the issue) until the field option exists.

The digest's `column` values match `Status` exactly, so reconciling a card is a
string comparison, not a translation.

## States and transitions

`Status` is the phase; `Awaiting` is the wait; the two are *mostly* orthogonal.
One column used to do both jobs — the digest derived it as "if a PR exists, `In
Review`", first and outranking everything else, so a never-reviewed draft, a
conflicted draft, an approved-and-waiting PR and a merged-but-unreleased fix
all reported the same state. Splitting them is what makes each state carry
exactly one next action.

A wait *does* rewrite the phase (#707): a recorded `Awaiting` (or a `blocked`
label / open `Blocked by #N`) pulls the item back to `Analysis` over a bare
worktree, a still-draft PR, **or a merged-but-unreleased fix** — unsettled
scope must not read as progress. The one artifact it does **not** override is
`In Review`: a PR that is out of draft is genuinely in the loop, and the
rhythm pass ranks the wait separately there.

"Back" is literal — the wait is a **floor-lower, never a promotion**. It only
moves an item *left*, toward `Analysis`; it never moves one *right*. A
`discussion` / `blocked` tag on a raw `Backlog` musing (no worktree, no PR, no
`analyzed` label — #703) stays in `Backlog`. Promoting it manufactured a
`board_status` ≠ `column` mismatch every pass, so `move_card` yanked the card
back to `Analysis` minutes after a human moved it to `Backlog`, forever.

And a **draft PR is not `In Review`** (#707): an open PR only means `In Review`
once it is out of draft. A draft PR with no review is `In Progress` — the
branch and PR exist, nothing is reviewing them yet.

Full order, highest first: **non-draft PR** (`In Review`) → **wait/block**
(`Analysis`) → **draft PR or live worktree** (`In Progress`) → **merged fix**
(`In Verification`) → analysed+prioritised (`Ready for Dev`) → analysed
(`Analysis`) → `Backlog`. Active work outranks landed work, so a merged
intermediate PR plus an active follow-up branch reads as `In Progress`.

| Status | Means | Exit |
|---|---|---|
| `Backlog` | captured, not analysed | analysis lands |
| `Analysis` | scope or approach unsettled, **or a recorded wait pulling an item back from a column right of Analysis** (not from Backlog) | Definition of Ready met and priority set |
| `Ready for Dev` | analysed, prioritised, unblocked | dispatch |
| `In Progress` | branch exists — no open PR, or a draft PR with no review | the PR goes out of draft |
| `In Review` | one or more **non-draft** open PRs, loop running | all its PRs merge |
| `In Verification` | on main, not yet in a stable release | graduation PR closes the issue |
| `Done` | shipped stable | — |

`In Verification` sits after merge to main and before release — the
fast-forward rule makes `beta/main` strictly downstream of `origin/main`, so a
fix is on main first, reaches a beta build, is run for real, and only then
graduates. Live work still outranks landed work: an issue whose graduation PR
is still open is `In Review`, not `In Verification`, however many of its other
PRs merged already — see `column()` in `backlog-digest.sh`.

### `Awaiting` is signed

Escalation and deferral are the same axis pointed in opposite directions.
Four of the five values mean someone else owes us, and correctly go quiet; the
fifth means the loop cannot advance without *you*, and it is inverted —
loud, not quiet.

| Value | Direction | Effect |
|---|---|---|
| `reporter`, `upstream`, `discussion` | they owe us | quiet — suppressed from actions, still counted and listed |
| `maintainer` | we owe them nothing; you owe us a decision | **loud — ranked above every other action (rank 0), with the open question attached** |

The one carve-out: `autonomous_analyze` fires from evidence (`bug` +
`ready-for-analysis` + non-maintainer author, and no `analyzed` /
`needs-human-review` label) and overrides the stale wait values — `reporter`,
`upstream`, `discussion` — so one of those cannot hide an item that is
actually waiting on analysis. The `maintainer` hold is NOT overridden: that
row means you owe a decision, so the carve-out stands down and the escalation
stays loudest — see Autonomous spend.

`analysis` is the fifth value and is not in the signed table above because it
means the same thing the digest's `awaiting_source: label` marks — a triage
gap, not a completed wait: set the field to what the item is actually waiting
on. There is no `Escalated` column: an escalated item stays wherever its
`Status` already put it, it just cannot move without you.

## When to Use

- Reviewing or refining the backlog, triaging a report, chasing a reporter
- Reconciling the board, deciding what is next, dispatching work
- Under `/loop /backlog` as the unattended Rhythm surface

**Not** for implementing anything. That is `implement-issue`, in its own
session.

## State lives on GitHub, nowhere else

Never write a local file that mirrors board or issue state. Priority is a
board field, rationale is an issue comment, dedupe is close-as-duplicate,
blocked-by is a `Blocked by #N` line in the issue body.

Post as the PO identity: `scripts/gh-agent.sh --as po issue comment ...`.
If a board write fails for missing scope, stop and report
`gh auth refresh -s project`. Never fall back to a file.

## What the digest tells you, and why each field exists

Four fields carry the grooming signal. Each was added because its absence
caused a real misclassification:

| Field | Meaning |
|---|---|
| `awaiting` | The blocking wait. **Outranks `analyzed`** — an item whose scope is unsettled is in *Analysis* no matter how far it got. Comes from the board field when set, else from a blocking label. |
| `awaiting_source` | `board` or `label`. A `label` source with no board value is a triage action: set the field. |
| `awaiting_suggested` | What the labels imply, so an unset field can be reconciled without guessing. |
| `last_comment` | `{author, days, is_reporter, is_bot}`. **The reporter-replied signal.** A comment count and a last-activity date cannot tell "the reporter answered us" from "we posted a nudge", which is why the follow-up chase never fired. |
| `stale_worktree` | The worktree's own branch is dead — already merged, **or its PR was closed unmerged** (an abandoned attempt, #428) — so it is rot, not progress. `stale_worktree_reason` says which. Hand it to `sweep-prs`. |
| `blocked` | `blocked` label, or a `Blocked by #N` whose blocker is **still open**. Fails Ready outright. |
| `blocked_by` / `blocked_by_open` | Every parsed reference, and the subset still open. Only the latter blocks — a `Blocked by #N` line is never edited out once N lands, so treating the raw scan as unresolved pins an item out of Ready forever. |

**A wait outranks a live worktree, a draft PR, and a merged-but-unreleased fix
— deliberately (#707).** An item with a recorded wait reports *Analysis* even
when a worktree is checked out, a draft PR is open, or a fix has merged to
main, because unsettled scope must not read as progress. It does *not* outrank
a non-draft PR (*In Review*) — that work is genuinely in the review loop — and
it does *not* promote a bare *Backlog* item (nothing to pull back from; #703).
The worktree / PR is still reported on the item (`worktree`, `worktree_branch`,
`prs`, `merged_pr`), so active or landed code stays visible — the wait changes
the column, not the evidence. Check those fields before assuming an *Analysis*
item has no code behind it.

**A human comment is not a wait.** `awaiting: discussion` used to be returned
for any human comment, which pushed items to *Analysis* for ordinary traffic —
thanks, a "me too", a follow-up question. Only a recorded wait or a blocking
label does that now; `last_comment` is what you read to judge the rest.

**`Ready for Dev` requires a `Priority`.** An analysed item with no priority is
un-ranked, so it cannot be "next" — it stays in *Analysis* as a triage action.

## Definition of Ready

Nothing is dispatched that has not crossed this line. A bug is Ready when:

1. A debug log or bundle is attached
2. There is a reproduction, or enough real data to replay one
3. Expected versus actual behaviour is stated explicitly, in system terms
4. An approach is agreed (Stage 2 analysis, or the maintainer's say-so)
5. No unresolved blocker

**Criterion 4 is the one that gets skipped, and the `analyzed` label is not
proof of it.** Stage 2 can diagnose a request correctly and still leave its
design open — #96 was labelled `analyzed`, prioritised `P2`, carried no blocking
label, and was still not implementable, because *how* to build it was undecided.
It reported *Ready*, an implementation session was dispatched at it, and that
session deadlocked on three design questions nobody was there to answer. When
an approach is genuinely undecided, record it: set `Awaiting` and post the open
questions on the issue, so a later attempt can rehydrate them rather than
rediscover them.

An enhancement is Ready when 3–5 hold and the user-visible outcome is stated.
An item failing any criterion stays in Backlog or Analysis and becomes your
follow-up, not a developer's problem.

## Verb: triage

For each item the digest puts in Backlog or Analysis:

1. Apply missing labels. An open issue with comment activity and no labels is
   a real and common case — #592 and #593 are examples — and it is yours to
   fix.
2. Set the `Awaiting` field: `reporter`, `discussion`, `upstream`, `analysis`.
3. Flag likely duplicates by comparing titles and symptoms across the digest.
   Close as duplicate only when the overlap is unambiguous; otherwise comment
   and ask.
4. Promote real `TODO.md` items to issues; mark never-issues as such. TODO.md
   is an input to drain, not a store to sync.
5. Set `Priority` per the ranking policy below.

## Verb: board

Reconcile every card against the digest's derived `column`. **The digest
always wins** — never trust a card's current position.

The comparison is in the digest: every item carries `board_status` (where the
card sits now) alongside `column` (where the evidence says it belongs), using
the same `Status` strings, so a mismatch is `board_status != column` and
nothing needs a second `gh project item-list` call. Act on each mismatch:

| Mismatch | Action |
|---|---|
| `board_status: null` | the issue has **no card at all**. It carries no Priority, and *Ready for Dev* requires one — so it can never become dispatchable however well it is analysed, while reading as an ordinary Backlog item. Add the card, then triage it normally. Also listed under `orphans` as `issue_no_card` |
| card *In Progress*, no worktree, no PR | abandoned — move to *Ready for Dev*, report it |
| `stale_worktree: true` | the branch is dead — merged, or its PR closed unmerged (`stale_worktree_reason` says which); the worktree is rot, not work. Hand to `sweep-prs`, and do not read it as progress |
| worktree present, no session, no PR, **not `stale_worktree`** | the session died mid-issue. The branch's commits survive — resuming is `/implement-issue <n>`, whose Step 0 detects the prior work and re-enters at the right step. **Never silently relaunch**: a session that died twice is telling you something, and a background dispatch that reports `working` may have written nothing at all — verify by work product (`git -C <wt> log`, file mtimes), never by session state |
| worktree present but `stale_worktree: true` | its branch is dead (merged, or its PR closed unmerged — `stale_worktree_reason`). Not resumable — `prune_worktree` / hand to `sweep-prs`. #428 sat here: an abandoned branch behind closed PR #437 while a different branch shipped the issue |
| `last_comment.is_reporter` and `awaiting: reporter` | the reporter answered. Re-check the Definition of Ready — this wait may be satisfied, and it is the transition nothing used to notice |
| PR `CONFLICTING`, draft | hand to `/advance-pr <n>` — it owns the board write for a conflict escalation |
| PR `CONFLICTING`, not a draft | hand to `sweep-prs` |
| worktree whose PR merged | prune via `sweep-prs` |
| issue closed, card not *Done* | move the card |
| *Analysis*/`reporter` quiet 14 days | nudge once; park to *Backlog* at 28 |
| *Analysis*/`discussion` quiet 14 days | summarise the thread, put the open question to the maintainer |
| open issue, comment activity, no labels | file into *Analysis*, assign a sub-state, apply labels |

Never auto-park an active conversation, and never chase a reporter for
something an upstream vendor owns.

Also review the digest's `orphans` list — worktrees with no matching open
issue, PRs with no `fixes/closes/resolves` reference, open issues with no
board card (`issue_no_card`), **PullRequest cards whose PR has closed or
merged** (`stale_pr_card`), and **Issue cards whose issue has closed**
(`stale_issue_card`). Hand worktree or PR rot to `sweep-prs`; a missing card
is yours to add; a stale PR card is yours to archive (`archive_pr_card`); a
stale issue card moves to *Done* (`move_card`).

## Verb: rhythm — the unattended pass

The one that carries work from incoming to a **ready PR**. Start here on every
`/loop /backlog` tick:

    scripts/backlog-rhythm.sh

It answers "what is due right now" deterministically — every rule is a
comparison over the digest, so a quiet backlog costs one process instead of a
model pass, and `RHYTHM: nothing due.` is a legitimate noop tick. **Do not
re-derive these by reading issues; act on what it lists.**

**Board data is always live** (the digest reads `gh`), but the pass *logic* —
this script, `backlog-digest.sh`, this skill — runs from the checkout the loop
started in and is never refreshed mid-loop. Each tick does a read-only
`git fetch` and prints

    TOOLING 6 commit(s) behind origin/main -- restart the loop from an updated checkout

when the backlog tooling paths are behind. It never pulls (wrong in a
worktree; swapping the skill under a live tick is worse than one stale tick) —
stop the loop and restart it from an up-to-date checkout. `RHYTHM_SKIP_FETCH=1`
skips just the network call; `RHYTHM_TOOLING_REF` overrides the ref.

Why it exists: every follow-up rule in this skill had been written down and
**none had ever fired.** They each needed a model to notice them and nothing
scheduled one, so the 14-day chase, the 28-day park and the reporter-replied
re-check were decoration.

Actions are ranked (rightmost-column-first — see **Verb: next** below) rather
than sorted alphabetically, and printed in that order. Who does what:

| Action | Do |
|---|---|
| `escalated` | **Read first, always** — rank 0, above every other action. Three sources, each meaning something different: `Awaiting: maintainer` on the board (read the open question, decide, or send it back to *Analysis* by clearing `Awaiting` and re-opening the scope); `resume_count >= 2` **and no merged PR** (two implementation sessions have already been handed back on this issue — it is not implementable as specified, so decide or re-scope it, don't dispatch a third; suppressed once a fix has merged, since `resume_count` never decrements and the handbacks are then history); and, on a PR, 3 `CHANGES_REQUESTED` rounds with no intervening `APPROVED` (the reviewer and the diff disagree about the design, and a fourth round will not settle it) |
| `announce_verification` | rank 1, right after escalations. An issue is *In Verification* — its fix is on `main` and in a beta build — but that state lives only in the Project field, so a reporter reading the issue sees no sign it is fixed (#683 sat here for weeks with only stale WIP notes). Fires **once**: as the PO, comment the fix status (merged in #N, shipped in beta, closes on the stable release) and apply the `awaiting-release` label, which suppresses it thereafter. The issue still closes only on the graduation PR |
| `mark_ready` | Route through `/advance-pr <n>` — its `draft, APPROVED, green` row runs exactly `gh pr ready <n>`, then report it. APPROVED, green, still a draft: the loop stopped one command short. **The one action no board decision can defer**, because it is a pipeline failure, not a priority call |
| `awaiting_maintainer` | nothing; report it. Out of draft **and carrying an APPROVED review** is the finish line — the maintainer's merge is all that is left |
| `request_review` | out of draft but Stage 4 never ran. `scripts/request-pr-review.sh <n>` (what `/advance-pr <n>` would also run). **Never report an unreviewed PR as ready to merge** — the draft flag is not a review, and a maintainer who flips it because a PR looks stuck routes around the one gate the pipeline is built on |
| `rework_review` | out of draft with changes requested: hand back to `/implement-issue <n>` — the issue that PR belongs to, resolved from its linked issue — to address them, then a fresh review |
| `resolve_conflict` | `CONFLICTING`, which also means the PR produced **no CI run at all**. A conflicted **draft** routes to `/advance-pr <n>` — only it performs the board write that records a semantic-conflict escalation, where `sweep-prs` would only report into a chat transcript and write nothing. A conflicted **non-draft** PR has already left the review loop, so it still goes to `sweep-prs`, or resolve directly if the diff is ours |
| `undiffable_pr` | `gh pr diff` failed for this PR, so the in-flight file set is incomplete. Dispatch is held **fleet-wide** until it clears — not just for this PR's own issue. Re-run the digest; if it recurs, the PR itself needs attention (deleted fork head, rate limit) |
| `resume_implementation` | One action name, three shapes, routed to the cheapest tool that is actually safe. A **live worktree with no PR** (a session died mid-issue — and `stale_worktree` is false; a dead branch is `prune_worktree`, not this) is `/implement-issue <n>` — a real session, because the implementation itself is unfinished, and Step 0 resumes the branch from the earliest incomplete step. A **draft PR whose next step is mechanical** — no review yet, a review still in flight, or an approved draft with checks not yet green — is `/advance-pr <n>` directly: request the review, resolve a conflict, or flip it ready, in one cheap step, no session. A **draft PR carrying `CHANGES_REQUESTED`** is `/implement-issue <n>` — the one PR shape that stays there, because only that session holds the Step 2 diagnosis and Step 3 scope assessment needed to tell a real review finding apart from a decision Step 3 already made and rejected on purpose; `advance-pr` itself always hands a `CHANGES_REQUESTED` draft straight back to `/implement-issue <n>` too, whatever caller invoked it, so dispatching there directly from here just skips the redundant round trip through `advance-pr`. Never restart any of the three, the branch commits are the only copy |
| `prune_worktree` | the worktree's own branch is dead — merged, or its PR closed unmerged (the `why` line quotes `stale_worktree_reason`); it is rot, not progress. Hand to `sweep-prs` |
| `refire_analyze` | a `@claude-bot analyze` trigger is on the issue but Stage 2 never completed — still `ready-for-analysis`, no `analyzed` / `needs-human-review` label, and the trigger is older than the staleness window (`RHYTHM_ANALYZE_STALE_HOURS`, default 6h). The usual cause is the workflow being out of API credit at the time. Under `/loop` this is a plain retry: re-post `@claude-bot analyze` as the PO. **Not** a maintainer escalation. A trigger younger than the window is a run that may still be working — the pass fires neither this nor `autonomous_analyze` and just waits |
| `analysis_deferred` | a tier-1 bug is ready to analyse but the Analysis column is at its WIP limit (`RHYTHM_ANALYSIS_WIP_LIMIT`, default 8). Do **not** fire Stage 2 — groom Analysis toward *Ready for Dev* first; the item is still counted and listed, and `autonomous_analyze` re-proposes once Analysis is back under the limit |
| `dispatchable` | propose for dispatch — needs the maintainer's go-ahead, and only fires when `predicted_files` is set (see the touch-set gate under Dispatch) |
| `queued_behind` | do nothing; it is correctly waiting on an in-flight PR that already touches one of its predicted files. Recheck once that PR lands |
| `cluster` | dispatch the named items as **one** unit of work — one branch, one PR. Two Ready items that predict overlapping files cost less merged into one dispatch than as two PRs plus a conflict |
| `needs_touch_set` | *Ready for Dev* but no predicted touch-set. **There is currently no board field or digest computation that carries `predicted_files`** — `backlog-digest.sh` never emits it, so this fires unconditionally for every `Ready for Dev` item today, and `dispatchable`/`queued_behind`/`cluster` cannot fire until that plumbing exists. Name the files from the Stage 2 analysis (or the issue text) in your dispatch proposal by hand rather than trusting this action to clear on its own |
| `recheck_ready` | the reporter answered: re-check Definition of Ready, clear `Awaiting` if satisfied |
| `surface_discussion` | summarise the thread, put the open question to the maintainer. **Never auto-park an open conversation** |
| `nudge_reporter` | one nudge, as the PO identity |
| `park` | move to *Backlog* — the chase went unanswered |
| `autonomous_analyze` | the tier-1 carve-out, computed from evidence not the board field: post `@claude-bot analyze` as the PO (`scripts/gh-agent.sh --as po issue comment <n> --body "@claude-bot analyze"`). The no-prior-analyze check is now **in the script** (`last_analyze_comment`) — this fires only when the issue has *never* been analyzed; a stalled prior run is `refire_analyze` instead. Fires even when a stale `Awaiting` would otherwise quiet the item, because `ready-for-analysis` already proves the log is in; stands down when the item has Stage 2 history (`analyzed` / `needs-human-review`), the card holds `Awaiting: maintainer` (see Autonomous spend), or the Analysis column is at its WIP limit (`analysis_deferred`) |
| `set_awaiting` / `set_priority` / `triage_labels` | grooming debt: write the board field or label. `set_awaiting` also fires when the board field still reads `analysis` but a Stage 2 label (`analyzed` / `needs-human-review`) is on — a stale "needs Stage 2" placeholder that no other rule contradicts, so it pins the item in *Analysis* until you re-point `Awaiting` at the real wait or clear it |
| `add_card` | open issue, no card on the board at all — add it to Project #1 first, **then** set `Priority`; until both exist it is unrankable and invisible to every board pass |
| `move_card` | the card sits somewhere the evidence does not support — always move it to match `column`, never re-derive `column` to match the card |
| `archive_pr_card` | a **PullRequest** card whose PR has closed or merged (#638). A PR card only carries a deferral while its PR is open; once it merges move the card to *Done*, once it closes unmerged delete it. Also listed under `orphans` as `stale_pr_card` |

**This pass does not drive the review loop, and must not learn to.**
`implement-issue` owns a PR from its first commit to `gh pr ready`, and now
does so by invoking `advance-pr` — its only copy — from Step 11. Re-implementing
any of that logic here is a second copy of one loop, which is how one of them
goes stale — the same argument that put resume in Step 0 instead of a separate
skill. `advance-pr` has three callers: `implement-issue`, this pass, and you
directly (`/advance-pr <n>`) — reach for the direct form whenever a PR needs
one step and you do not want to wait on a full `resume_implementation` hand-off.

**The one carve-out is `mark_ready`, and it earned it.** An APPROVED, green,
still-draft PR used to hand back like any other, and that is exactly why #629
sat finished-but-draft: the remedy on offer was a whole `implement-issue`
session, and nobody spends one of those to run a single command. `gh pr ready`
is a terminal action, not a loop — naming it here, routed through `advance-pr`
rather than run by hand, duplicates nothing and keeps the one copy of the loop
the one place that flips the flag.

## Deferring an issue — how a decision gets recorded once

**One card per unit of work, on the issue — PR cards go away.** A PR never
carries its own `Priority` or `Awaiting`; those live on the issue the PR
belongs to, whatever `Status` that issue is currently in (including `In
Review`, while its PRs are open). Before this, a judgement about a PR's board
card had nowhere unambiguous to live: two cards for one piece of work meant a
decision recorded on one was invisible from the other, and "#167 and #354 are
blocked", "#437 and #490 are lower priority, later" were real decisions that
every pass re-reported as due because nothing recorded them anywhere both
sides would see. The same conversation happened every 30 minutes. Putting the
fields on the issue instead removes the ambiguity: there is exactly one card,
so a decision recorded once is visible from every angle — the issue's own
grooming, and any PR raised against it.

| Decision | Set on the issue card | Effect |
|---|---|---|
| blocked / parked on a call | `Awaiting: discussion` (or `upstream`) | suppressed from actions |
| later, not never | `Priority: P4` | suppressed from actions |
| loop cannot advance without a decision | `Awaiting: maintainer` | **louder, not quieter** — ranked above every other action, rank 0 |
| actively being driven | no `Awaiting`, `P1`–`P3` | reported every tick |

**`Awaiting: maintainer` is the one value that inverts the usual effect.**
Every other `Awaiting` value means someone else owes us and correctly goes
quiet; this one means the loop cannot advance without *you*, so quieting it
would be exactly backwards — see **States and transitions** above.

Suppressed items are **counted and listed**, never dropped — the pass ends
with `deferred: 4 (#490 priority P4; #167 awaiting discussion; …)` so the item
stays findable and the reason travels with it. Losing the item would trade one
failure for another.

`mark_ready` ignores all of this, per the carve-out above — it is a pipeline
failure, not a priority call, so no deferral defers it. `awaiting_maintainer`
does not ignore it either: an approved PR waiting on a merge is not broken, it
is the maintainer's call when to take it, and `P4` is how they say "later".

**Restarting a stalled issue is always a resume, never a fresh start.** Step 0
re-enters at the earliest incomplete step. A restart runs Step 4, which branches
from `origin/main` and deletes commits that exist nowhere else — an audit found 8
abandoned branches carrying real work, one with 32 commits.

**A session reporting `working` may have written nothing.** Three background
dispatches in one day produced zero tracked-file writes while reporting healthy
state, and `claude logs` returns only spinner frames. Read `claude agents --json`
**unsandboxed** (`~/.claude/jobs` is sandbox-denied, so a sandboxed listing
silently truncates — it returned 1 session where the truth was 17), and confirm
progress by work product: commits, `MERGE_HEAD`, file mtimes.

**Ordering matters.** Work `resume_implementation` first — it is the only action
that ends in something approvable. `recheck_ready` outranks the chases, because
nudging someone who has already replied is the worst output this pass can
produce.

**Quiet time is measured from the last comment, not `updatedAt`** — a label
change or a board move bumps `updatedAt`, so an issue nobody has spoken on for a
month would otherwise look active and never age into a chase.

**A `dispatchable` item is a proposal, not a launch.** Dispatch spends real
money and needs the go-ahead. And verify the item truly meets criterion 4 first:
`Ready for Dev` is derived, and a design-heavy item will stop and ask a question
no unattended session can answer.

## Flow policy: empty the board from the right

Replaces a plain alphabetical action sort, which put `dispatchable` ahead of
`resume_implementation` for no reason beyond `d < m < r` and so led every pass
with "start new work" instead of "finish started work" — the fleet on
2026-08-18 was 8 open PRs, all drafts, 6 `CONFLICTING`, none ever approved,
which is what that produces over time.

### Rule 1 — Pull from the right

Finish started work before starting new work. `backlog-rhythm.sh`'s `rank`
field (see the action table above) implements exactly this, rightmost column
first:

```
Awaiting: maintainer  ->  read first, always — the escalation valve
In Verification       ->  graduate: cut the release, close the issue
In Review              ->  advance-pr toward merge
In Progress             ->  finish the branch into a PR, or take that PR out of draft
Ready for Dev           ->  dispatch  (gated by Rules 2 and 3 below)
Analysis                ->  groom
Backlog                 ->  triage
```

Escalations sit above the column order — rank 0, ahead of everything. An
escalation that ranks by column is an escalation that waits, which defeats the
valve: see `escalated` in the action table.

### Rule 2 — Bugs pre-empt, they do not add

A `bug` opened by someone other than the maintainer jumps the queue **at
analysis**, and enters at the front of `Ready for Dev`. But it **displaces** a
feature from dispatch rather than being dispatched alongside one — this is
what stops "prioritise bugs" from quietly becoming "unbounded WIP", which is
the state the fleet above was in. `Verb: next` below applies this at ranking
time; the WIP limit applies it at dispatch time.

### Rule 3 — Nothing starts that collides

The touch-set gate under **Dispatch**, applied before anything is proposed —
not after a conflict shows up at merge time. Detecting a collision among open
PRs is detecting a fire that already started; the requirement is to never
strike the match.

### The WIP limit: 3

WIP counts `In Progress` + `In Review` **together** — a branch and its PR are
one piece of work, not two, and counting them separately would silently double
the limit. Above the limit, `dispatchable` is suppressed fleet-wide and the
pass reports it on every path, same as the touch-set gate:

    WIP 7/3 -- finish before starting; dispatch suppressed

Three is deliberately aggressive. With 7 in flight, dispatch stays shut until
the fleet drains to 2 — the point is that the current jam has to clear before
anything new starts. A limit low enough to hold also makes same-file
collisions rare on its own, without the touch-set gate having to catch every
one of them.

### The Analysis WIP limit: 8

The same rule one column to the left. Analysis is only worth anything once its
output reaches *Ready for Dev*, so an Analysis column holding 18 items is 18
pieces of half-finished work, not progress — and every tick the pass was still
pulling a new bug in for Stage 2 on top of them. At or above
`RHYTHM_ANALYSIS_WIP_LIMIT` (default 8), `autonomous_analyze` is suppressed —
the held bugs surface as `analysis_deferred`, counted and listed, never
dropped — and the pass reports it on every path:

    ANALYSIS 18/8 -- promote analysed items to Ready for Dev before analysing more

It does **not** gate `refire_analyze`: re-poking a Stage 2 run that stalled
finishes an item already in Analysis rather than adding one. And `bug` still
pre-empts `feature` — the WIP limit only decides *whether* new analysis starts;
Rule 2 and `Verb: next` decide *what* does when it can. Do not propose a
feature request for analysis while Analysis is over the limit.

## Verb: next

Rank Backlog and Ready items in this order:

1. **User-facing breakage** — `bug` opened by someone other than the
   maintainer. A wrong number on a real dashboard outranks everything, and per
   Rule 2 above it displaces a feature from dispatch rather than adding to it.
2. **Roadmap direction** — advances a theme in
   `docs/agents/product-roadmap.md`, or moves an experimental platform toward
   stable.
3. **Cheap wins and batching** — prefer small and low-risk; group items
   touching the same subsystem, subject to the touch-set gate under Dispatch.

Tiebreaker: release-blocking. Suppressed: `blocked`, anything awaiting a
reporter, duplicates, and — per the WIP limit above — everything once
`In Progress` + `In Review` is already at 3.

Propose the top 1–3 with reasoning. Then stop and wait — dispatch needs the
maintainer's go-ahead.

## Dispatch

Only after approval, and only for an item that meets the Definition of Ready:

    scripts/run-agent.sh <n>
    scripts/run-agent.sh --with-compose <n>   # when Step 8 (local run & observe) applies

**Never create a worktree or a clone.** `run-agent.sh` owns the isolation: a
private clone at `.agent-clones/issue-<n>`, the dev-role gh token, a restricted
egress allowlist, and permissions skipped inside the disposable container — the
boundary is the container, not an allowlist entry. That is what keeps a headless
dispatch from ever stopping to ask for a permission nobody can answer (the old
`claude --bg` path hung exactly there). Implement-issue's Step 4 creates the
branch in that clone directly.

Gated three ways, and any one of them holds `dispatchable` shut:

- **The WIP limit.** `In Progress` + `In Review` at or above 3 suppresses
  every `dispatchable` action fleet-wide; the pass reports `WIP n/3` on every
  path so the reason is never silent. Unblocks only by something finishing —
  a branch landing a PR, a PR merging.
- **The collision gate.** `backlog-digest.sh` computes the exact **in-flight**
  file set — the union of `gh pr diff --name-only` over every open PR — and
  `backlog-rhythm.sh` checks each Ready item's **predicted** touch-set against
  it. A clash reports `queued_behind` instead of `dispatchable`; two Ready
  items whose predictions overlap each other report `cluster` — dispatch them
  as one branch, one PR, since that costs less than two PRs fighting over the
  same file plus a conflict resolution. Unblocks when the in-flight PR lands,
  or by clustering.
- **Undiffable PRs.** If `gh pr diff` fails for even one open PR, the
  in-flight set is known incomplete, so collision cannot be safely evaluated
  for *anything* — dispatch is held fleet-wide, the same way over-WIP holds
  it, and the pass reports `undiffable_pr`. Unblocks by re-running the digest
  once the PR diffs cleanly again.

**A `dispatchable` proposal must carry its predicted touch-set.** No
touch-set, no dispatch — the pass reports `needs_touch_set` instead. This
replaces the advisory "queue same-file work" paragraph that used to live here,
which was prose with no gate and never fired: five of eight open PRs ended up
editing the same three files. Name the files from the Stage 2 analysis, or the
issue text when there is no analysis, before proposing the item.

**As shipped, no board field or digest computation carries `predicted_files`
into the pass** — `backlog-digest.sh` has nothing that writes it, so
`needs_touch_set` fires for every `Ready for Dev` item and `dispatchable`
cannot appear from the script alone. Until that plumbing exists, treat the
touch-set as something *you* name and check against `in_flight_files` by hand
(from the digest) before proposing an item under **Verb: next** — the gate's
reasoning holds even though the automation that would clear it does not exist
yet.

Serialise, do not stack:

- An item with an unmet `blocked_by` stays put. When the blocker's PR merges,
  drop `blocked`, move it to *Ready*, and dispatch fresh.

## Autonomous spend

Exactly one action costs money without asking: firing Stage 2
(`@claude-bot analyze`, ~$0.50–2). **Post it as the PO, never as the
maintainer:**

    scripts/gh-agent.sh --as po issue comment <n> --body "@claude-bot analyze"

`issue-analyze.yml`'s actor gate accepts `bess-product-owner` for exactly this
trigger. It did not always, and the mismatch had a real cost: the rule
authorised the PO to spend while the gate accepted only the repo owner, so the
trigger went out as the maintainer — putting their name on comments they never
wrote, and hiding which decisions were the agent's. An automation decision
carries the automation's face. If this ever fails the gate, **that is the
finding** — report it; do not route around it with plain `gh`.

The rhythm pass surfaces the qualifying items as `autonomous_analyze`
(ranked with the other Analysis actions) — a check against the item's
**evidence**, not the board field: labelled `bug`, opened by someone other
than the maintainer, with its debug log attached. `ready-for-analysis` is the
debug-log proof and the no-prior-analyze guard in one: triage sets it only
when it has confirmed the log is attached, and Stage 2 removes it (replacing
it with `analyzed` or `needs-human-review`). The rule itself also refuses an
item carrying either Stage 2 label — triage re-stamps `ready-for-analysis`
on an edited issue even after an inconclusive run, so without that check the
spend would re-fire on items analysis has already settled. A stale `Awaiting`
field must not quiet it — #681/#680 was a `bug` + `ready-for-analysis` item
whose card still said `Awaiting: reporter`, and the old carve-out, evaluated
only on items the pass surfaced, never saw it. The carve-out overrides the
stale wait values (`reporter`, `upstream`, `discussion`) but stands down on
`Awaiting: maintainer`, where the loop is deliberately held for your
decision; and the same evidence makes the `park` / `nudge_reporter` /
`surface_discussion` chases stand down, so the pass never tells the PO to
bury what it just un-hid.

The no-prior-analyze guard is now **in the script**: `last_analyze_comment`
carries the most recent `@claude-bot analyze` trigger and its age.
`autonomous_analyze` fires only when that is absent — the issue has never been
analyzed. A trigger younger than `RHYTHM_ANALYZE_STALE_HOURS` (default 6h) is
an analyze that may still be running: the pass fires neither `autonomous_analyze`
nor `refire_analyze` and waits. Once it ages past that window with the item
still `ready-for-analysis` and unstamped, the run is treated as failed —
almost always an out-of-credit workflow — and `refire_analyze` re-posts the
trigger. Under `/loop` that just retries until Stage 2 lands; it is never a
maintainer escalation. This is a check against the item itself, not a ranking
pass: an
item entering Analysis is never a member of the Backlog/Ready list that
`next` ranks, so it cannot "rank" into a tier. Every other item entering
Analysis gets a proposal instead.

## Close the loop

When a fix reaches a release, comment on the originating issue to tell the
reporter, as the PO identity.
