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
lives in the repo's `.env`, which `backlog-digest.sh` does **not** source — so
export it first, or the digest exits with a "board has not been created yet"
message that is misleading rather than wrong:

    set -a; . ./.env; set +a; ./scripts/backlog-digest.sh

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

Field options, as they actually exist — do not invent values outside these sets:

| Field | Options |
|---|---|
| `Status` | `Backlog`, `Analysis`, `Ready for Dev`, `In Progress`, `In Review`, `Done` |
| `Priority` | `P1`, `P2`, `P3`, `P4` — **there is no `P0`** |
| `Awaiting` | `reporter`, `discussion`, `upstream`, `analysis` |
| `Source` | `issue`, `TODO` |

The digest's `column` values match `Status` exactly, so reconciling a card is a
string comparison, not a translation.

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
| `stale_worktree` | The worktree's own branch has already merged, so it is rot, not progress. Hand it to `sweep-prs`. |
| `blocked` | `blocked` label, or a `Blocked by #N` whose blocker is **still open**. Fails Ready outright. |
| `blocked_by` / `blocked_by_open` | Every parsed reference, and the subset still open. Only the latter blocks — a `Blocked by #N` line is never edited out once N lands, so treating the raw scan as unresolved pins an item out of Ready forever. |

**A wait outranks a live worktree, deliberately.** An item with a recorded wait
reports *Analysis* even when a worktree is checked out for it, because unsettled
scope must not read as progress. The worktree is still reported on the item
(`worktree`, `worktree_branch`), so active undelivered code stays visible — the
wait changes the column, not the evidence. Check those fields before assuming an
*Analysis* item has no code behind it.

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
always wins** — never trust a card's current position. Act on each mismatch:

| Mismatch | Action |
|---|---|
| card *In Progress*, no worktree, no PR | abandoned — move to *Ready for Dev*, report it |
| `stale_worktree: true` | the branch already merged; the worktree is rot, not work. Hand to `sweep-prs`, and do not read it as progress |
| worktree present, no session, no PR | the session died mid-issue. The branch's commits survive — resuming is `/implement-issue <n>`, whose Step 0 detects the prior work and re-enters at the right step. **Never silently relaunch**: a session that died twice is telling you something, and a background dispatch that reports `working` may have written nothing at all — verify by work product (`git -C <wt> log`, file mtimes), never by session state |
| `last_comment.is_reporter` and `awaiting: reporter` | the reporter answered. Re-check the Definition of Ready — this wait may be satisfied, and it is the transition nothing used to notice |
| PR `CONFLICTING` | hand to `sweep-prs` |
| worktree whose PR merged | prune via `sweep-prs` |
| issue closed, card not *Done* | move the card |
| *Analysis*/`reporter` quiet 14 days | nudge once; park to *Backlog* at 28 |
| *Analysis*/`discussion` quiet 14 days | summarise the thread, put the open question to the maintainer |
| open issue, comment activity, no labels | file into *Analysis*, assign a sub-state, apply labels |

Never auto-park an active conversation, and never chase a reporter for
something an upstream vendor owns.

Also review the digest's `orphans` list (worktrees with no matching open
issue, PRs with no `fixes/closes/resolves` reference) and hand any worktree
or PR rot found there to `sweep-prs`.

## Verb: rhythm — the unattended pass

The one that carries work from incoming to a **ready PR**. Start here on every
`/loop /backlog` tick:

    scripts/backlog-rhythm.sh

It answers "what is due right now" deterministically — every rule is a
comparison over the digest, so a quiet backlog costs one process instead of a
model pass, and `RHYTHM: nothing due.` is a legitimate noop tick. **Do not
re-derive these by reading issues; act on what it lists.**

Why it exists: every follow-up rule in this skill had been written down and
**none had ever fired.** They each needed a model to notice them and nothing
scheduled one, so the 14-day chase, the 28-day park and the reporter-replied
re-check were decoration.

Actions, and who does what:

| Action | Do |
|---|---|
| `resume_implementation` | `/implement-issue <n>`. **The action that produces a ready PR** — Step 11 requests the review, acts on the verdict and runs `gh pr ready`. Covers a draft needing a first review, a rework, an approved PR that never got flipped, *and* a worktree whose session died |
| `awaiting_maintainer` | nothing; report it. Out of draft is the finish line |
| `resolve_conflict` | hand to `sweep-prs` |
| `recheck_ready` | the reporter answered: re-check Definition of Ready, clear `Awaiting` if satisfied |
| `nudge_reporter` | one nudge, as the PO identity |
| `park` | move to *Backlog* — the chase went unanswered |
| `surface_discussion` | summarise the thread, put the open question to the maintainer. **Never auto-park an open conversation** |
| `set_awaiting` / `set_priority` / `triage_labels` | grooming debt: write the board field or label |
| `dispatchable` | propose for dispatch — needs the maintainer's go-ahead |

**This pass does not drive the review loop, and must not learn to.**
`implement-issue` owns a PR from its first commit to `gh pr ready`; Step 11
already requests the review, acts on the verdict and flips the PR. So every
unfinished draft resolves to one action — hand it back — and a second copy of
that loop is never built here. It is the same argument that put resume in Step 0
instead of a separate skill: two copies of one loop means one of them goes stale.

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

## Verb: next

Rank Backlog and Ready items in this order:

1. **User-facing breakage** — `bug` opened by someone other than the
   maintainer. A wrong number on a real dashboard outranks everything.
2. **Roadmap direction** — advances a theme in
   `docs/agents/product-roadmap.md`, or moves an experimental platform toward
   stable.
3. **Cheap wins and batching** — prefer small and low-risk; group items
   touching the same subsystem.

Tiebreaker: release-blocking. Suppressed: `blocked`, anything awaiting a
reporter, duplicates.

Propose the top 1–3 with reasoning. Then stop and wait — dispatch needs the
maintainer's go-ahead.

## Dispatch

Only after approval, and only for an item that meets the Definition of Ready:

    claude --bg -n "issue-<n>" "/implement-issue <n>"

**Never create a worktree.** That session's Step 4 creates its own from a
fresh `origin/main`.

Serialise, do not stack:

- An item with an unmet `blocked_by` stays put. When the blocker's PR merges,
  drop `blocked`, move it to *Ready*, and dispatch fresh.
- Two items likely to touch the same file are queued, not run concurrently —
  the second would eat a merge conflict it did nothing to earn. Predict the
  touch-set from the Stage 2 analysis or the issue text. Warn and queue; this
  is not a hard block.

## Autonomous spend

Exactly one action costs money without asking: firing Stage 2
(`@claude-bot analyze`, ~$0.50–2) on an item entering Analysis that meets the
tier-1 bar from `Verb: next` directly — labelled `bug`, opened by someone
other than the maintainer, with its debug log attached — **and that has no
prior `@claude-bot analyze` comment already on the issue**. Check this by
reading the issue's comments from the digest (or `gh issue view` if the
digest's comment count needs confirming) — never a local file. This is a
check against the item itself, not a ranking pass: an item entering Analysis
is never a member of the Backlog/Ready list that `next` ranks, so it cannot
"rank" into a tier. The no-prior-analyze condition exists because the digest
is a stateless snapshot with no notion of "entering" — without it, an item
that Stage 2 already failed to reach a conclusion on (`needs-human-review`)
would keep matching every pass under `/loop`, firing Stage 2 again each time
at $0.50–2 a shot. Every other item entering Analysis gets a proposal
instead.

## Close the loop

When a fix reaches a release, comment on the originating issue to tell the
reporter, as the PO identity.
