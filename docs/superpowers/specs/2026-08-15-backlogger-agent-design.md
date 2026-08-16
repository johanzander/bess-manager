# Backlogger Agent — Design

**Status:** approved design, not yet implemented
**Date:** 2026-08-15

## Problem

The backlog is split across three stores that nobody can reason about
together: 37 open GitHub issues, 4 open PRs, and a 792-line `TODO.md`. There
is no view that answers "what should I work on next", no detection of
duplicates across the stores, and no record of which issues depend on which.

Dispatch is manual. Today the maintainer opens a terminal and types
`/implement-issue 502`, having chosen 502 by memory. Ordering between related
issues is held in the maintainer's head, so two sessions can touch the same
file concurrently and the second one eats a merge conflict it did nothing to
earn — with 31 live worktrees, this is not hypothetical.

## What this is

**A Product Owner, in the SCRUM sense.** It owns the product backlog: it
faces the customer, gets reports into a state a developer can act on, orders
the backlog, and decides what is ready. It does not implement anything, and —
per the same discipline — it does not assign work either. The implementing
agents pull the top of the Ready column; the PO's leverage is entirely in what
reaches that column and in what order.

Its duties, in the order a report travels:

1. **Intake** — answer the reporter, ask for the debug log, classify.
2. **Readiness** — chase what's missing until the item satisfies the
   Definition of Ready. Nothing is handed to a developer before that line.
3. **Ordering** — dedupe, prioritise, hold a coherent roadmap.
4. **Flow** — keep the board honest, keep the PR fleet unblocked.
5. **Close the loop** — tell the reporter when their fix ships.

## Scope

**In v1, without asking:**

- Respond to new and edited issues: classify, request debug logs, flag likely
  duplicates
- Chase stale reports (`needs-debug-log` quiet for 14 days)
- Label, prioritise, dedupe, and promote `TODO.md` items into issues
- Reconcile the kanban board against reality
- Run `sweep-prs` maintenance on the open PR fleet
- Notify reporters when a fix reaches a release

**In v1, only on explicit go-ahead:**

- Launching an implementation session

**Not in v1:**

- Autonomous implement-and-release of easy fixes (explicitly a later version)
- Stacked PRs (see Dependency orchestration)

## Runtime shape — three surfaces, one agent

A PO is not a chat session. A customer-facing response cannot depend on the
maintainer's laptop being open, and cross-issue judgment cannot run on Haiku
in a 12-turn CI job. So one definition and one identity execute on three
surfaces:

| Surface | Trigger | Where | Model | Owns |
|---|---|---|---|---|
| **Reflex** | `issues: opened/edited/reopened` | GitHub Actions | Haiku | First response, log request, classification, duplicate flag |
| **Rhythm** | `/loop`, self-paced | Local session | cheap | Follow-up chases, dedupe, board reconciliation, `sweep-prs` |
| **Conversation** | the maintainer speaks | Local session | strong | Ranking judgment, roadmap themes, approving dispatch |

**Reflex already exists** as Stage 1 (`issue-triage.yml`) and is well-built:
event-driven, `allowed_non_write_users: "*"` so external reporters are
answered at all, Haiku at ~$0.05. It is rewritten as the PO's intake arm
rather than replaced — same trigger and cost, but the PO persona and a backlog
digest, so it can spot duplicates and reference related issues on first
contact. Today it reads one issue and knows nothing of the other 36.

**Rhythm runs locally, on a loop, by deliberate choice.** The consequence is
explicit: first response to a reporter is always immediate because that is
Reflex in CI, but *follow-up* — the 14-day log chase, the shipped-notification
— happens only while the maintainer is at the machine. If reports start going
stale, that is the signal to move Rhythm to an Actions cron; nothing else in
this design changes if it does.

No surface holds durable state. Every pass reads fresh from the digest, so a
`/clear`, a crash, or a machine restart costs nothing.

## State model — GitHub only

There is no new tracked file, and no local mirror of GitHub state. A generated
snapshot goes stale the moment a card is dragged in the UI, and then two
readers disagree about what is true. The repo already has one duplicate store
(`TODO.md`) and that is the reason the backlog cannot currently be reasoned
about as a whole.

| Fact | Home |
|---|---|
| Priority | `Priority` single-select field on the Project board |
| Ordering / status | Board column |
| Rationale for a decision | Issue comment from `bess-agent` |
| Duplicate | Close-as-duplicate |
| Blocked-by | `Blocked by #N` line in the issue body + `blocked` label |
| Source (`issue` / `TODO`) | `Source` field on the board |

`TODO.md` is an **input to drain, not a store to sync**. Real items get
promoted to issues; items that will never be issues get marked as such. Over
time there is one backlog rather than two.

**Prerequisite:** the maintainer's `gh` token lacks project scope. A one-time
`gh auth refresh -s project` is required before any board write, and the
`bess-agent` PAT likely needs the same.

## Architecture

Four pieces, each independently testable.

### 1. `scripts/backlog-digest.sh` — the evidence gatherer

One invocation, one compact table on stdout, no model involvement. It joins:

- `gh issue list` → number, title, labels, age, author, comment count
- `gh pr list --json ...mergeable,statusCheckRollup` → green / red / `CONFLICTING`
- `git worktree list` + branch → what is physically in flight locally
- `claude agents --json` → running background sessions and their `cwd`
- `gh project item-list` → current column and Priority field per item

Output is one row per backlog item with a derived `state`, plus an **orphans**
section: worktrees with no PR, PRs with no issue, issues labelled `has-fix-pr`
whose PR has merged, cards whose session died.

This exists so the model never reads 37 issue bodies to answer "what's next".
It reads an issue body only when actually deciding on that issue. This follows
the pattern that has worked in this repo before: pre-compute the evidence and
feed the digest, rather than instructing a model to go gather it.

### 2. `.claude/agents/backlogger.md` + `.claude/skills/backlog/SKILL.md` — the judgment layer

The agent file makes the backlogger a first-class thing to talk to rather than
a skill someone must remember to invoke: `claude --agent backlogger` boots
straight into a backlog pass. Verified frontmatter fields used:

| Field | Value | Why |
|---|---|---|
| `color` | `purple` | Distinguishes it in the task list and transcript |
| `initialPrompt` | a backlog pass | Auto-submitted first turn when run as a main session |
| `memory` | `project` | Accumulates standing judgment ("dashboard work keeps getting deferred") |
| `skills` | `backlog`, `sweep-prs` | Preloaded, so a pass needs no skill lookup |

The skill holds the procedure. It

Reads the digest, applies the ranking policy, drives three verbs:

- **triage** — label, dedupe, promote TODO items, set the Priority field
- **board** — move cards to the column the digest says they are actually in
- **next** — propose the next 1–3 items with reasoning; on approval, dispatch

Holds no state.

### 3. The board — a GitHub Project v2

Columns: `Backlog / Ready / In progress / In review / Done`.
Fields: `Priority` (single-select), `Source` (`issue` / `TODO`).

The only new persistent object, and it is GitHub-native — a real board in the
browser, queryable by any agent, with no duplicate store.

### 4. Dispatch

```
claude --bg -n "issue-502" "/implement-issue 502"
```

The backlogger **never creates worktrees**. `implement-issue` Step 4 already
creates its own from a fresh `origin/main`; launching from the main checkout
preserves that invariant exactly and sidesteps the `EnterWorktree` /
`git worktree add` friction entirely. One session per issue, named
`issue-<n>`, so the join key back to the digest is obvious.

## Agent identity

Avatars exist only on GitHub, and each distinct avatar-bearing actor costs a
GitHub App — an install, a secret, and a rotation. Locally, Claude Code
supports `color` (one of `red, blue, green, yellow, purple, orange, pink,
cyan`) and session names; there is no `icon` or `avatar` field.

So: **colors and names locally, one identity on GitHub.**

| Role | Local | GitHub |
|---|---|---|
| `backlogger` | `color: purple`, `memory: project`, `initialPrompt` | `bess-agent`, comment prefixed `🗂️ **backlogger**` |
| `bess-analyst` (exists) | `color: cyan` | `bess-agent`, prefixed `🔍 **analyst**` |
| implementer sessions | `claude --bg -n "issue-<n>"` | `bess-agent` (unchanged) |

A second App (`bess-backlogger`) is deliberately **not** created. It would cut
against the established rule that the identity axis is *review*, not topic —
everything unreviewed posts as `bess-agent` — and the role tag in the comment
body buys the same timeline legibility for nothing. Revisit only if the
timeline actually becomes ambiguous.

### 5. `issue-triage.yml` — Reflex, rewritten as PO intake

Kept in place, same trigger and same Haiku budget. Three changes:

- The prompt becomes the PO persona, so the reporter hears one voice from
  first contact through to the shipped-notification.
- It is fed a compact digest of open issue titles and labels, so it can flag a
  likely duplicate on first response instead of reading one issue in
  isolation.
- Its labels are stated in terms of the Definition of Ready, so intake and the
  board agree on what "Ready" means.

`allowed_non_write_users: "*"` and the Haiku model are load-bearing and stay
— external reporters must be answered, and this runs on every issue edit.
The pipeline table in `CLAUDE.md` needs updating to match.

## Kanban state machine

Columns are **derived, then reconciled**. The backlogger never trusts a card's
position; it computes where the item actually is and moves the card to match.
That is what makes the board survive a dragged card, a dead session, or a 2am
CI merge.

| Column | Derivation |
|---|---|
| Backlog | open issue, no `blocked`, no worktree, no PR |
| Ready | satisfies the Definition of Ready below, and Priority is set |
| In progress | live worktree on a branch naming the issue, or draft PR with no review |
| In review | PR open and review requested / `has-fix-pr` |
| Done | PR merged and issue closed |

The primary in-progress signal is **the worktree, not a label**. With 31 live
worktrees the filesystem is the honest record of what is being worked on;
labels lag.

The valuable output is the **mismatches**, each mapping to one action:

| Mismatch | Action |
|---|---|
| card *In progress*, no worktree, no PR | abandoned — move back to *Ready*, report |
| PR `CONFLICTING` | hand to `sweep-prs` |
| worktree whose PR merged | prune via `sweep-prs` |
| issue closed, card not *Done* | move card |
| `needs-debug-log` older than 14 days | nudge the reporter or park |

## Definition of Ready

The line between the PO's work and the developers'. Moving items across it is
the PO's main job on the left of the board, and **nothing is dispatched that
has not crossed it** — that is what stops a developer agent burning a session
on a report it cannot reproduce.

A bug is Ready when:

1. A debug log or bundle is attached (the existing `needs-debug-log` gate)
2. There is a reproduction, or enough real data to replay one
3. Expected versus actual behaviour is stated explicitly, in system terms
4. An approach is agreed — the Stage 2 analysis, or the maintainer's say-so
5. No unresolved blocker (`blocked` label clear)

An enhancement is Ready when 3–5 hold and the user-visible outcome is stated.

An item failing any criterion stays in *Backlog* and becomes a PO follow-up
action, not a developer's problem. Criterion 1 is what Reflex chases on
intake; criteria 2–3 are what Rhythm chases when a reporter replies with
something vague.

## Ranking policy

Applied in order, to items in *Backlog* / *Ready* only:

1. **User-facing breakage** — `bug` opened by someone other than the
   maintainer, the beta user especially. A wrong number on a real dashboard
   outranks everything.
2. **Roadmap direction** — advances a theme in `docs/agents/product-roadmap.md`
   (see below), or moves an experimental inverter platform toward stable.
3. **Cheap wins and batching** — within a tier, prefer small and low-risk, and
   group items touching the same subsystem.

Tiebreaker: release-blocking.
Suppressed entirely: `blocked`, `needs-debug-log` (waiting on the reporter),
duplicates.

### The roadmap the ranking reads

`docs/agents/roadmap.md` is **not** a product roadmap — it is a note
evaluating Sweep AI and CodeRabbit as pipeline tooling. Axis 2 therefore needs
a file that does not exist yet: `docs/agents/product-roadmap.md`.

Two layers, so direction is authored once instead of re-decided per issue:

- **Direction** — 5–8 themes with a rough order, human-approved. Themes, not
  items ("get SolaX modbus to stable", "consumption forecasting works on all
  platforms"). The backlogger reads this file and never edits it.
- **Per-item priority** — the board's `Priority` field, backlogger-maintained,
  derived from how well an item serves the themes.

**Bootstrap:** the backlogger's first pass reads all 37 issues plus `TODO.md`
and proposes a *draft* set of themes with every item mapped underneath. The
maintainer edits and approves that draft; the approved result becomes
`product-roadmap.md`. This grounds the roadmap in the real backlog rather than
a blank page, and it is a one-time step — thereafter the file is read-only
input, changed by the maintainer alone.

## Dependency orchestration

The backlogger holds the ordering. The implementing sessions stay ignorant of
it — each sees one issue and a base branch. The backlogger's only primitive is
**choosing each session's start time**.

**Logical dependencies → serialise on merge.** #B stays in *Backlog* with
`blocked` while #A is in flight. When #A's PR merges, the backlogger drops the
label, moves #B to *Ready*, and dispatches it fresh from a now-current
`origin/main`.

**Physical collisions → the same treatment, inferred rather than declared.**
Two issues that will both touch `action_selector.py` are queued rather than run
concurrently, even with no logical dependency. The touch-set is predicted from
the Stage 2 analysis or the issue text. With 31 worktrees live this is the more
common case. It is a warning-and-queue, not a hard block.

**Why not stacked PRs.** Dispatching #B off #A's branch and retargeting after
#A merges is faster in wall-clock, but `implement-issue` Step 4 hardcodes
cutting from `origin/main` — a rule that exists because branching from a stale
local HEAD silently cut branches behind main and caused missed release cuts.
Stacking would also put PRs in the fleet whose `CONFLICTING` state is
normal-and-expected, which is exactly the signal `sweep-prs` treats as rot.
Serialise-on-merge costs wall-clock and zero edits to `implement-issue`; all
the intelligence stays in the backlogger. Revisit only if wall-clock actually
hurts.

## Failure handling

| Case | Behaviour |
|---|---|
| Session died mid-issue (no PR, worktree present) | Report; offer relaunch. Never silently relaunch — a session that died twice is telling you something. The branch's commits survive. |
| Session finished, PR red | `implement-issue` Step 11 owns this. Report only if red and untouched for 24h. |
| PR `CONFLICTING` | Hand to `sweep-prs`. |
| Board write fails on missing scope | Hard fail with the `gh auth refresh -s project` instruction. No fallback to a local file. |
| Digest disagrees with the board | The digest wins; the card moves. |

## Testing

- **`backlog-digest.sh`** — the testable part. Pure shell over `gh` / `git`
  JSON, so fixture-based tests with recorded JSON and no live network, covering
  the join and each orphan class.
- **The skill** — prose; verified as the other skills here are, with a dry run
  against the real 37-issue backlog, checking the ranking and the mismatch list
  by eye.
- **Dispatch** — verified once, end-to-end, on one genuinely small issue.

## Open questions

None blocking. The `gh auth refresh -s project` prerequisite must be done by
the maintainer before board work begins.
