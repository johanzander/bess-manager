# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
this repository. Read `docs/agents/rules.md` first — those constraints are
non-negotiable and apply to all agents.

## Agent Documentation Index

| File | When to Read |
|------|-------------|
| [`docs/agents/rules.md`](docs/agents/rules.md) | **Always** — hard constraints |
| [`docs/agents/architecture.md`](docs/agents/architecture.md) | Before any structural change |
| [`docs/agents/patterns.md`](docs/agents/patterns.md) | Before writing new code |
| [`docs/agents/testing.md`](docs/agents/testing.md) | Before writing or changing tests |
| [`docs/agents/workflow.md`](docs/agents/workflow.md) | Before any commit, PR, or release |

## Project Overview

BESS Manager is a Home Assistant add-on for optimizing battery energy storage
systems. It provides price-based optimization, solar integration, and a web
interface for managing battery schedules and monitoring energy flows.

## Development Commands

### Backend (Python)

```bash
pip install -r backend/requirements.txt
pytest                         # run all tests
pytest core/bess/tests/unit/   # unit tests only
black . && ruff check --fix .  # format and lint
./scripts/quality-check.sh     # full quality gate
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
docker-compose up -d           # backend + frontend
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

Issues on GitHub are handled by a three-stage pipeline powered by
`anthropics/claude-code-action@v1`. This CLAUDE.md file is the primary
instruction source — Claude reads it at the start of every bot session.

### Stage 1 — Auto Triage (`.github/workflows/issue-triage.yml`)

Runs automatically on every new issue. Classifies, labels, and either asks for
a debug log or posts an initial analysis. Does NOT confirm bugs in source code.

### Stage 2 — Confirm (`@claude-bot confirm` on an issue)

**When triggered:** Read the full issue including all comments. Then:
1. Read `docs/agents/rules.md` and `docs/agents/architecture.md`.
2. Use `gh issue view <n>` to see the full issue context.
3. Search the codebase for the code paths mentioned in the bug report.
4. Read the actual source files (do not rely on search snippets alone).
5. Post a comment with your verdict:
   - **Bug confirmed** — quote the exact defective lines (file:line), explain
     the root cause, and say: "To trigger a fix: `@claude-bot fix this`"
   - **Cannot confirm** — explain what you read and why the bug isn't there.
   - **Needs more info** — ask for the specific information missing.

### Stage 3 — Fix (`@claude-bot fix this` on an issue)

**When triggered:** Fix the confirmed bug and open a draft PR.
1. Read `docs/agents/rules.md`, `docs/agents/architecture.md`,
   `docs/agents/patterns.md`, and `docs/agents/workflow.md`.
2. Use `gh issue view <n>` to understand the bug and any confirm-step evidence.
3. Implement the minimal fix — no refactoring, no unrelated changes.
4. Run `./scripts/quality-check.sh` and fix any failures before committing.
5. Create a fresh branch `fix/issue-<number>-<short-slug>` and push it.
6. Open a **draft** PR linked to the issue: `gh pr create --draft ...`
7. Post a comment on the issue linking the PR.

### PR Review (`@claude-bot` on a PR comment)

Read `docs/agents/rules.md` and `.github/claude-bot.md` for the review
checklist. Post inline comments on specific lines where issues are found.
Summarize with an overall verdict (approve / request changes / comment).

### General bot rules

- Only the repo owner can trigger bot commands.
- Always use `gh` CLI for all GitHub operations (issues, PRs, labels).
- Never push directly to `main`.
- Commit as the GitHub App bot identity (handled automatically by the action).

## Home Assistant Integration

- **Sensors**: battery SOC/power, solar production, grid import/export, pricing
- **Device**: Growatt inverter (TOU schedule control)
- **Add-on config**: `config.yaml` in root (version field, HA schema)
- **Pricing sources**: Nordpool and Octopus Energy

## Configuration Files

- `pyproject.toml` — Black, Ruff, mypy settings
- `frontend/package.json` — React/TypeScript dependencies
- `docker-compose.yml` — development environment
- `config.yaml` — HA add-on schema and current version