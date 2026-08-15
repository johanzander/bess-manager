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

One agent the maintainer talks to. It holds the whole-backlog picture,
prioritises, keeps a kanban board honest, and — on the maintainer's
go-ahead — launches the implementation sessions that do the work.

It does not implement anything itself.

## Scope

**In v1, without asking:**

- Label, prioritise, dedupe, and promote `TODO.md` items into issues
- Reconcile the kanban board against reality
- Run `sweep-prs` maintenance on the open PR fleet

**In v1, only on explicit go-ahead:**

- Launching an implementation session

**Not in v1:**

- Autonomous implement-and-release of easy fixes (explicitly a later version)
- Stacked PRs (see Dependency orchestration)

## Runtime shape

A long-lived Claude session the maintainer chats with. On-demand by default:
it acts when spoken to and is otherwise silent. An opt-in `/loop /backlog`
heartbeat (~20–30 min, self-paced) reconciles the board and catches PR rot
without being asked.

The session holds no durable state. Every pass reads fresh from the digest,
so a `/clear`, a crash, or a machine restart costs nothing. This is what makes
a long-lived session affordable despite the cost-discipline rules in
`CLAUDE.md`: the expensive pattern is a session that *holds* a large context
across long waits, not one that is merely long-lived.

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

### 2. `.claude/skills/backlog/SKILL.md` — the judgment layer

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

## Kanban state machine

Columns are **derived, then reconciled**. The backlogger never trusts a card's
position; it computes where the item actually is and moves the card to match.
That is what makes the board survive a dragged card, a dead session, or a 2am
CI merge.

| Column | Derivation |
|---|---|
| Backlog | open issue, no `blocked`, no worktree, no PR |
| Ready | approach agreed (`analyzed` label, or maintainer okay) and Priority set |
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

## Ranking policy

Applied in order, to items in *Backlog* / *Ready* only:

1. **User-facing breakage** — `bug` opened by someone other than the
   maintainer, the beta user especially. A wrong number on a real dashboard
   outranks everything.
2. **Roadmap direction** — advances `docs/agents/roadmap.md`, or moves an
   experimental inverter platform toward stable.
3. **Cheap wins and batching** — within a tier, prefer small and low-risk, and
   group items touching the same subsystem.

Tiebreaker: release-blocking.
Suppressed entirely: `blocked`, `needs-debug-log` (waiting on the reporter),
duplicates.

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
