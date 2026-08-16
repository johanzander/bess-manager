# Backlogger Agent — Design

**Status:** Tasks 1–4 implemented (`scripts/backlog-digest.sh`,
`scripts/gh-agent.sh`, `.claude/skills/backlog/SKILL.md`,
`.claude/agents/product-owner.md`). Tasks 5–8 (identity creation, board
setup, Reflex rewrite, dispatch verification) deferred — they need GitHub
accounts and secrets only the maintainer can create.
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
- Fire Stage 2 (`@claude-bot analyze`) on a **user-facing bug — labelled
  `bug`, opened by someone other than the maintainer — that already has its
  log** — bounded autonomous spend, ~$0.50–2 a shot. Everything else waits
  for the maintainer.

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
| Rationale for a decision | Issue comment from `bess-product-owner` |
| Duplicate | Close-as-duplicate |
| Blocked-by | `Blocked by #N` line in the issue body + `blocked` label |
| Source (`issue` / `TODO`) | `Source` field on the board |

`TODO.md` is an **input to drain, not a store to sync**. Real items get
promoted to issues; items that will never be issues get marked as such. Over
time there is one backlog rather than two.

**Prerequisite:** the maintainer's `gh` token lacks project scope. A one-time
`gh auth refresh -s project` is required before any board write, and the
`bess-product-owner` PAT must carry `project` scope when it is created — the
PO is the only role that writes to the board.

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
section. v1 emits two kinds: `worktree_no_issue` (a worktree whose path and
branch match no open issue) and `pr_no_issue` (a PR with no
`fixes/closes/resolves #N` reference in its body).

This exists so the model never reads 37 issue bodies to answer "what's next".
It reads an issue body only when actually deciding on that issue. This follows
the pattern that has worked in this repo before: pre-compute the evidence and
feed the digest, rather than instructing a model to go gather it.

### 2. `.claude/agents/product-owner.md` + `.claude/skills/backlog/SKILL.md` — the judgment layer

The agent file makes the backlogger a first-class thing to talk to rather than
a skill someone must remember to invoke: `claude --agent product-owner` boots
straight into a backlog pass. Verified frontmatter fields used:

| Field | Value | Why |
|---|---|---|
| `color` | `purple` | Distinguishes it in the task list and transcript |
| `initialPrompt` | a backlog pass | Auto-submitted first turn when run as a main session |
| `memory` | `project` | Accumulates standing judgment ("dashboard work keeps getting deferred") |
| `skills` | `backlog`, `sweep-prs` | Preloaded, so a pass needs no skill lookup |

The skill holds the procedure. It reads the digest, applies the ranking
policy, and drives three verbs:

- **triage** — label, dedupe, promote TODO items, set the Priority field
- **board** — move cards to the column the digest says they are actually in
- **next** — propose the next 1–3 items with reasoning; on approval, dispatch

Holds no state.

### 3. The board — a GitHub Project v2

Columns: `Backlog / Analysis / Ready / In progress / In review / Done`.

`Analysis` is the refinement column, and it exists so refinement stalls are
visible as such: an item stuck there for weeks is the PO's problem, not a
developer's. It is also where the existing Stage 2 pipeline lives — an item
enters Analysis when refinement starts and leaves it when the Definition of
Ready is met.

### Analysis sub-states

Refinement stalls for more reasons than a missing log, and the PO's follow-up
differs by reason. Four sub-states, held in an `Awaiting` field on the board:

| Sub-state | Meaning | PO follow-up |
|---|---|---|
| `reporter` | Debug log or reproduction requested, not yet supplied | Nudge at 14 days; park at 28 |
| `discussion` | Behaviour, scope, or expected outcome still being agreed with the reporter or maintainer — e.g. #592 "VPP idle mode", #593 "Growatt VPP order of register values" | Summarise the thread and put the open question to the maintainer; never auto-park an active conversation |
| `upstream` | Blocked on a vendor or third party (inverter register semantics, an HA release) | Track, restate the dependency, do not chase the reporter |
| `analysis` | Log present, approach not yet agreed; Stage 2 not run or running | Fire or propose Stage 2 (below) |

**Label-based derivation is not sufficient here.** #592 and #593 are open,
actively discussed, and carry *no labels at all* — a label-only rule files
both under Backlog while a live conversation runs. So an open issue with
comment activity and no development artefact belongs in Analysis regardless of
labels, and assigning its sub-state is a judgment the PO makes by reading the
thread. Applying the missing labels is itself PO work.

**Entering Analysis has one autonomous action.** If the item meets the
tier-1 bar from the ranking policy directly — labelled `bug`, opened by
someone other than the maintainer, with its debug log attached — the PO
fires Stage 2 itself rather than waiting to be asked. This is a check
against the item, not a ranking pass: an item entering Analysis is not a
member of the Backlog/Ready list the ranking policy ranks, so it has no tier
to "rank" into. Those are the items the maintainer would have approved
anyway, and refining them overnight is the point of having a PO. Every
other item entering Analysis gets a proposal
instead ("#502 has its log, shall I analyze?"). This is the only place in v1
where the PO spends real money unprompted, and the gate is deliberately narrow
because Stage 2 costs ~$0.50–2 per run.
Fields: `Priority` (single-select), `Source` (`issue` / `TODO`), `Awaiting`
(`reporter` / `discussion` / `upstream` / `analysis`, meaningful only in the
Analysis column).

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

Roles must be visibly distinct actors in an issue timeline — the Product Owner
asking for a log, the Developer posting a diagnosis, and the Reviewer
commenting on a PR should not look like the same account. A comment prefix
cannot do that; only a separate account has a name and an avatar.

### What exists today

An audit of the current identities, because two of the three roles already
exist under names that hide what they do:

- **`bess-agent`** is *not* a release agent, despite the description in
  `CLAUDE.md`. It has exactly one caller, `scripts/request-pr-review.sh`, and
  one job: `pr-review.yml` gates on
  `comment.user.login == owner || == 'bess-agent'`, so an `implement-issue`
  session can post `@claude-bot review` on its own PR without wearing the
  maintainer's face. Requesting review of your own PR is a **developer**
  action — `bess-agent` already is the Developer, badly named.
- **`CLAUDE_REVIEWER`** (the App behind `CLAUDE_REVIEWER_APP_ID`) is the
  Reviewer, likewise already correct and likewise unlabelled as such.
- **Release needs no identity.** Nothing automated posts releases; the
  `release` skill runs as the maintainer, deliberately. Inventing a release
  bot would be inventing a role that does not exist.

### The three roles

| Role | Does | Identity | Work needed |
|---|---|---|---|
| **Product Owner** | Intake, log chases, backlog, board, reporter comments | `bess-product-owner` (machine user) | Create — the only genuinely new one |
| **Developer** | Stage 2 analyze, Stage 3 fix, PR authorship, requesting review | `bess-agent` → renamed `bess-developer` | Rename, upload avatar, update the `pr-review.yml` gate |
| **Reviewer** | Stage 4 PR review only | existing `CLAUDE_REVIEWER` App | Rebrand, upload avatar |

**Developer and Reviewer must stay distinct, and this is the strongest
identity argument in the design.** Stage 4 reviews Stage 3's own output. Under
one face the timeline reads as an account approving its own PR, and no later
reader can tell independent review from self-approval at a glance. Elsewhere
separate identities are a nicety; here the separation *is* the meaning.

This supersedes the earlier rule that the identity axis is *review, not
topic*. That rule existed to stop unreviewed output masquerading as the
maintainer's voice, and it still holds — none of these three is the
maintainer. Within automation, role is now the axis.

### Auth

**Machine users for Product Owner and Developer; the Reviewer stays an App.**
A machine-user PAT works identically in CI (as a secret) and locally (from
`.env`), so a role wears one avatar in both places with no new machinery:
`gh-agent.sh` is generalised to `gh-agent.sh --as po|dev` and that is the
whole change. Minting installation tokens locally from an App key would have
required a JWT-signing script; that component is deliberately not built.

Per new role, one-time setup: create the account, upload an avatar, add the
PAT to `.env` and to Actions secrets.

**Avatars are supplied by the maintainer**, who already has a set in a
consistent style and will produce the new ones. Implementation neither
generates nor specifies images; it only assumes each account has one uploaded
before the role goes live.

**Locally, Claude Code has names and colors but no avatars** — verified: agent
frontmatter supports `color` (`red, blue, green, yellow, purple, orange, pink,
cyan`) and sessions take `-n`, but there is no `icon` or `avatar` field.

| Agent | Local |
|---|---|
| `product-owner` | `color: purple`, `memory: project`, `initialPrompt` |
| `bess-analyst` (exists) | `color: cyan` |
| implementer sessions | `claude --bg -n "issue-<n>"` |

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
| Backlog | open issue, no `blocked`, no worktree, no PR, and no refinement started |
| Analysis | being refined toward Ready — see the four sub-states below |
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
| in *Analysis*/`reporter`, quiet 14 days | nudge once; park back to *Backlog* with a comment at 28 |
| in *Analysis*/`discussion`, quiet 14 days | summarise the thread, put the open question to the maintainer |
| open issue, comment activity, no labels | file into *Analysis*, assign a sub-state, apply the missing labels |
| in *Analysis*, `analyzed`, DoR met | promote to *Ready* |

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
