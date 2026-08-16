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

    ./scripts/backlog-digest.sh

Open an individual issue only when you are deciding about that issue.

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

## Definition of Ready

Nothing is dispatched that has not crossed this line. A bug is Ready when:

1. A debug log or bundle is attached
2. There is a reproduction, or enough real data to replay one
3. Expected versus actual behaviour is stated explicitly, in system terms
4. An approach is agreed (Stage 2 analysis, or the maintainer's say-so)
5. No unresolved blocker

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
| card *In progress*, no worktree, no PR | abandoned — move to *Ready*, report it |
| worktree present, no session, no PR | the session died mid-issue. Report it and offer to relaunch; the branch's commits survive. **Never silently relaunch** — a session that died twice is telling you something |
| PR `CONFLICTING` | hand to `sweep-prs` |
| worktree whose PR merged | prune via `sweep-prs` |
| issue closed, card not *Done* | move the card |
| *Analysis*/`reporter` quiet 14 days | nudge once; park to *Backlog* at 28 |
| *Analysis*/`discussion` quiet 14 days | summarise the thread, put the open question to the maintainer |
| open issue, comment activity, no labels | file into *Analysis*, assign a sub-state, apply labels |

Never auto-park an active conversation, and never chase a reporter for
something an upstream vendor owns.

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
(`@claude-bot analyze`, ~$0.50–2) on an item entering Analysis that is a
user-facing bug, has its debug log, and ranks in the top priority tier. Every
other item entering Analysis gets a proposal instead.

## Close the loop

When a fix reaches a release, comment on the originating issue to tell the
reporter, as the PO identity.
