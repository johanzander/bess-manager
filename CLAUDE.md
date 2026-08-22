# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
this repository. Read `docs/agents/rules.md` first — those constraints are
non-negotiable and apply to all agents.

## Verification Before Action

- ALWAYS run tests locally before pushing commits — never push to any remote until local tests are green
- ALWAYS verify against actual source code/repos before making assumptions about APIs, entity names, or naming patterns
- NEVER speculate about file contents or behavior - read the file or run the code first
- Before proposing any fix, show the exact code path and evidence (logs, source) that proves the root cause — do not guess at entity names, prefixes, or discovery logic

## Issue Work

- Any request to fix, resolve, or implement a GitHub issue (e.g. "fix #123",
  "resolve this issue") MUST go through the `implement-issue` skill from the
  start — not ad-hoc brainstorming, writing-plans, or direct edits. It already
  encodes PR hygiene rules (e.g. don't commit plan files) that get skipped
  otherwise.

## Agent Documentation Index

| File | When to Read |
|------|-------------|
| [`docs/agents/rules.md`](docs/agents/rules.md) | **Always** — hard constraints |
| [`docs/agents/architecture.md`](docs/agents/architecture.md) | Before any structural change |
| [`docs/agents/optimizer-architecture.md`](docs/agents/optimizer-architecture.md) | **Normative** — before any change to the optimizer core (`action_selector.py`, `dp_battery_algorithm.py`, `pwl_window_dp.py`, `tie_detection.py`, flow derivation, intent, simulation) |
| [`docs/agents/patterns.md`](docs/agents/patterns.md) | Before writing new code |
| [`docs/agents/testing.md`](docs/agents/testing.md) | Before writing or changing tests |
| [`docs/agents/workflow.md`](docs/agents/workflow.md) | Before any commit, PR, or release |
| [`docs/agents/skill-architecture.md`](docs/agents/skill-architecture.md) | Before working on skills, the `@claude-bot` pipeline, or adding an integration |
| [`docs/agents/bess-knowledge.md`](docs/agents/bess-knowledge.md) | Before answering any question about BESS behavior, savings calculations, optimizer decisions, or schedule logic |
| [`docs/agents/local-agent-environment.md`](docs/agents/local-agent-environment.md) | Before autonomous local work — worktrees, permissions, the OS sandbox, podman, Playwright |
| [`docs/agents/memory/`](docs/agents/memory/) | Project-specific memory (beta workflow, release train) |

## Project Overview

BESS Manager is a Home Assistant add-on for optimizing battery energy storage
systems. It provides price-based optimization, solar integration, and a web
interface for managing battery schedules and monitoring energy flows.

## Development Commands

### Backend (Python)

```bash
.venv/bin/pytest -m "not slow"           # fast tests (~3s, recommended)
.venv/bin/pytest -m slow                 # algorithm/integration tests (~4min)
.venv/bin/pytest                         # run all tests
.venv/bin/black . && .venv/bin/ruff check --fix .  # format and lint
./scripts/quality-check.sh               # full quality gate
```

### Frontend (React/TypeScript)

```bash
cd frontend
npm install
npm run dev          # development server
npm run build        # production build
npm run lint:fix     # fix TypeScript issues
npm run generate-api # regenerate API client from OpenAPI spec
```

### Docker Development

```bash
docker-compose up -d                                          # backend + frontend (dev)
docker compose -f docker-compose.ci.yml up -d                 # E2E dev with mock-HA (fast, volume mounts)
docker compose -f docker-compose.prod-test.yml up -d --build  # production image smoke test
docker-compose logs -f
```

### Build Add-on

```bash
./package-addon.sh
```

## Architecture in One Paragraph

FastAPI backend (`backend/app.py`) runs an hourly scheduler. The core
optimization engine (`core/bess/`) uses dynamic programming to generate a
24-hour battery schedule from electricity spot prices and real-time sensor
data. The schedule is sent to a Growatt inverter via the Home Assistant API.
A React SPA (`frontend/`) provides the management interface.

## Automated Agent Workflow

GitHub issues flow through a four-stage pipeline. Each stage is a separate
workflow file with a self-contained prompt — there is no cross-stage routing
through CLAUDE.md. All stages run on `anthropics/claude-code-action@v1`.

| Stage | Trigger | Workflow | Cost | What it does |
|-------|---------|----------|------|--------------|
| 1. Triage | `issues: opened/edited` (auto) | `issue-triage.yml` | ~$0.05 | Classify + label only. Gates on debug log presence. |
| 2. Analyze | `@claude-bot analyze` (manual) | `issue-analyze.yml` | ~$0.50–2 | Delegates to `bess-analyst` sub-agent, posts root-cause diagnosis. No code changes. |
| 3. Fix | `@claude-bot fix` (manual) | `issue-fix.yml` | ~$1–4 | Runs the `implement-issue` skill in CI mode per the Stage 2 plan, opens draft PR. |
| 4. Review | `@claude-bot` on a PR (manual) | `pr-review.yml` | ~$0.50–2 | Reviews diff against rules and checklist. |
| 5. Integrate | `@claude-bot integrate` (manual) | `issue-integrate.yml` | ~$2–10 | Drives a new inverter/provider request through the full experimental→stable lifecycle (`feature-lifecycle`), one stage per invocation. |

**Why gated, not auto:** Stages 2 and 3 cost real money. The user explicitly
triggers each one after reading the previous stage's output.

**Label flow:**

```
opened ──► bug + needs-debug-log     (Stage 1: no log)
            │
            └─ user adds log ──► bug + ready-for-analysis  (Stage 1 re-runs on edit)
                                  │
                  @claude-bot analyze
                                  ▼
                                  analyzed                 (Stage 2)
                                  │
                  @claude-bot fix
                                  ▼
                                  has-fix-pr               (Stage 3, draft PR open)
```

If Stage 2 can't reach a conclusion it applies `needs-human-review` instead
of `analyzed`.

### General bot rules

- Bot commands are owner-triggered, with **two** exceptions, each matching an
  account that a documented rule already makes responsible for that spend:
  - **Stage 4** — `pr-review.yml` accepts `@claude-bot` from the developer
    identity (currently `bess-agent`; being renamed to `bess-developer` — see
    `scripts/gh-agent.sh`), so `implement-issue`'s Step 11 loop can request its
    own review.
  - **Stage 2** — `issue-analyze.yml` accepts `@claude-bot analyze` from
    `bess-product-owner`, because `backlog`'s Autonomous spend rule authorises
    exactly that trigger and bounds it (labelled `bug`, external reporter,
    debug log attached, no prior analyze). The rule existed before the gate
    accepted the account enforcing it, so the only way to satisfy both was to
    post as the maintainer — putting their name on comments they never wrote
    and hiding which decisions were the agent's. An automation decision should
    carry the automation's face.

  **Stages 1, 3 and 5 stay owner-only, and must not copy this.** Their spend
  ($1–4 and $2–10) is authorised by no autonomous rule, so nothing would be
  enforcing a bar on the other side of the gate.

  Only ever name a **registered** account in a gate. `bess-developer` is added
  in the same commit that renames the account, never before: on a public repo
  anyone can claim an unregistered username, so pre-authorising one is
  exploitable. `bess-product-owner` is named above because it exists today and
  is a collaborator.
- Automation writes carry a **role** identity, and role is the axis:
  `bess-product-owner` (intake, backlog, board, reporter comments),
  `bess-developer` (analyze, fix, PR authorship, requesting review),
  `bess-reviewer` (Stage 4 review only). Developer and Reviewer are
  deliberately distinct — Stage 4 reviews Stage 3's own output, and one shared
  face would read as an account approving its own PR. Post via
  `scripts/gh-agent.sh --as po|dev`. Genuine maintainer voice still uses plain
  `gh`.
- Always use `gh` CLI for all GitHub operations (issues, PRs, labels).
- Never push directly to `main`. PRs are always *opened* as drafts, and no
  agent ever merges one — the merge is the maintainer's, always.
- **Who takes a PR out of draft depends on which flow opened it.** An
  interactive `implement-issue` run drives its own review loop, so its
  Step 11 marks the PR ready (`gh pr ready`) the moment Stage 4 returns
  `APPROVED`, leaving only the merge. A **Stage 3 (`issue-fix.yml`) PR stays
  a draft even after Stage 4 approves it** — CI mode skips Step 11, so
  nothing there runs `gh pr ready`, and you are triggering that review by
  hand anyway. Flip it yourself when you're satisfied.
- The bot identity is `bess-manager-claude-bot` (a custom GitHub App). The
  official Anthropic Claude App is **suspended** to avoid collisions —
  do not unsuspend it.
- Stage 2 must invoke the `bess-analyst` sub-agent. Skipping that step is
  the failure mode the previous design suffered from.

## Release Workflow

- Always release through a PR so CI runs — never push directly to a branch bypassing CI
- Always check the current published version before tagging (e.g., check GitHub releases) to avoid version collisions
- Confirm the target remote and branch BEFORE pushing releases (beta vs main, origin vs beta remote)
- Run the full test suite locally before any release tag or beta push
- Never skip the CHANGELOG.md update or version bump
- `beta/main` only ever advances by fast-forward from `origin/main` — never commit directly to the beta repo. If a fix is needed on the currently-published stable version while main has moved on, use the hotfix procedure (short-lived `release-X.Y` branch cherry-picking from main), never a direct beta commit.
- `CHANGELOG.md` is authored once, on `origin/main`, under `## [Unreleased]`. Beta and stable releases both consume that section (copy for beta, rename for stable) — never hand-write a beta-specific or duplicate changelog entry.

## Scope Discipline

- Do NOT modify, remove, or 'clean up' items the user hasn't asked you to change
- When doing cleanup, list what you plan to change and confirm before editing
- Do not revert intentional linter changes or simplifications without explicit instruction
- After editing, list every file and symbol changed so the user can confirm nothing unrelated was touched
- Never add speculative fallbacks, defensive error handling, or "robustness" improvements beyond what was asked
- Never add a parameter, flag, default-fallback, second construction site, or extra trigger whose only job is to route around an ordering/timing/dependency problem — fix that problem directly (reorder, or reuse/expose what already exists); see `docs/agents/rules.md` Debugging Protocol step 8

## Cost Discipline

The user pays per token. A long Opus session that re-reads a large context after
every multi-minute wait is what runs up the bill — not the work itself.

- **Pick the best-fit model per task.** No model is pinned in
  `.claude/settings.json`, so sessions start on the Claude Code default.
  Reach for a stronger model on genuinely hard reasoning, and prefer a
  cheaper one for routine coordination, iteration, CI-watching, or file edits.
- **Don't put subagents on an expensive model**, and avoid agents for
  long-running watches entirely; if delegation is truly needed, use a cheap model.
- **Don't hold one big session across many long CI/test waits.** The prompt
  cache expires after ~5 min, so each long wait forces a full uncached re-read
  of the entire context. Prefer `/clear` between unrelated chunks, or let the
  session sit idle rather than re-engaging every few minutes.
- Don't re-dump large files or logs into context.
- **Treat `implement-issue` Step 8 (`verify`, podman-compose/mock-HA E2E) as
  a session boundary.** Kick it off, then either let the session sit idle
  until it completes or `/clear` and resume fresh once it's done — don't
  stay engaged re-touching the diagnosis/TDD context through the wait.

## Home Assistant Integration

- **Sensors**: battery SOC/power, solar production, grid import/export, pricing
- **Device**: Growatt inverter (TOU schedule control)
- **Add-on config**: `bess_manager/config.yaml` (version field, HA schema)
- **Pricing sources**: Nordpool and Octopus Energy

## Configuration Files

- `pyproject.toml` — Black, Ruff, mypy settings
- `frontend/package.json` — React/TypeScript dependencies
- `docker-compose.yml` — development environment
- `bess_manager/config.yaml` — HA add-on schema and current version (single source of truth)