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

- Only the repo owner can trigger bot commands.
- Always use `gh` CLI for all GitHub operations (issues, PRs, labels).
- Never push directly to `main`. PRs are always opened as drafts.
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

## Worktree Conventions

Both layouts are first-class — either way the worktree is a normal git checkout,
so per-agent inspect / test / run (`./deploy.sh`, `pytest`, the app) works the
same. Choose by how you want to reach an agent's work:

- **Sibling folders** (e.g. `../bess-manager-feature/`) — open cleanly in their
  own VS Code window; this is the go-to when you actively inspect code and run
  scripts per agent. They work with Agent View too: start the background session
  *inside* the sibling (it's a linked git worktree, so Claude won't relocate it).
  Caveat: a sibling only appears in **unscoped** `claude agents` (or
  `--cwd ~/GitHub`), not in the project-scoped `claude agents --cwd <repo>` view.
- **Native `.claude/worktrees/`** (`claude agents` / `--worktree` /
  `EnterWorktree`) — auto-created for background sessions and visible in the
  **project-scoped** Agent View. Still a real checkout: `code
  <repo>/.claude/worktrees/<name>` or `cd` into it to run tests/scripts.

Find any session's worktree path by peeking/attaching it in Agent View, or via
`claude agents --json` (the `cwd` field).

**Run `./scripts/worktree-setup.sh` once in every new worktree, before any
test/build/verify step.** A fresh worktree has no `.venv` and no
`node_modules`, and reinstalling them costs ~35 minutes against ~5 minutes of
actual testing. The script shares all three dependency trees with the main
checkout (falling back to a real `npm install` only for a package root whose
lockfile actually diverged) and repairs a Playwright browser cache left
unusable by an interrupted install.

Those shared trees are symlinks, so they are read-shared but **not**
write-isolated: `npm install` or `pip install` inside a worktree writes through
the link and changes dependencies for the main checkout and every other
worktree at once. Running tests and builds is safe; when a branch needs its own
dependency set, replace the symlink with a real install (`rm .venv` / `rm
frontend/node_modules` first) rather than installing through it. Re-running
`worktree-setup.sh` handles the node case automatically once
`package-lock.json` diverges — `requirements.txt` drift is not detected.

### Permissions inside a worktree

**The worktree is the safety boundary.** A linked worktree is disposable by
construction, so `.claude/hooks/auto-allow-worktree-destructive.sh` auto-allows
Bash commands whose cwd is a linked worktree, and falls through everywhere else
so the shared main checkout keeps its `ask`/`deny` rules. Do not "fix" a prompt
by adding the offending command to an allowlist — an `ask` rule beats an `allow`
rule, so that never works, and enumerating command shapes is what the inverted
hook exists to replace.

**Never `git stash` — it is blocked, everywhere in this repo.** There is exactly
one `refs/stash` per repository, shared by the main checkout and every worktree,
and the stack has no owner: one agent's `git stash` pushes an entry that another
agent's `git stash pop` will take, with no way to tell it was not theirs. With
~20 worktrees active that silently destroys work, and once popped and discarded
git offers no recovery. The hook denies every mutating form (`push`, `save`,
bare `git stash`, `pop`, `apply`, `drop`, `clear`, `branch`) in the main checkout
as well as in worktrees; `git stash list`/`show` still work.

To set work aside, use a temporary WIP commit — it lives on the branch, so it is
per-worktree, private to that agent, and recoverable by SHA even if the branch
moves:

```bash
git add -A && git commit -m "wip: <what>"   # set aside
git reset --soft HEAD~1                     # pick back up
```

Inside a worktree the rule is: **do anything to the repo, except destroy the
repo or its history.** What still prompts is a short, closed list of effects no
worktree can contain — the shared podman VM (a `deny`, re-emitted so it can't be
downgraded to one keystroke), elevated privileges, anything reaching GitHub,
pushes that move a shared ref (`main`, `beta`, `beta-release-*`, tags), and
writes to state shared across every checkout: the single object database, ref
namespace, stash, and `.git/config`.

**What it deliberately does not do is infer which files a command will touch.**
An earlier version tried, using absolute paths, `..`, `~`, variables and
substitutions to decide whether a command wrote outside the worktree. That is
shell parsing by regex, and it does not work — quoting, globs, heredocs and `cd`
all defeat it. It produced six distinct false positives in a single day, *every
one introduced by the fix to the previous one*, including blocking a live beta
release and judging a worktree foreign to itself because `;` wasn't treated as a
separator. It was removed rather than patched again. The accepted cost: a stale
absolute path in a Bash command can reach the main checkout unprompted; tracked
content there is recoverable from git, uncommitted work isn't.

If you want real containment, the mechanism is the sandbox
(`sandbox.filesystem.allowWrite`/`denyWrite`), which the OS enforces — not more
regex. **Anything added to this hook must classify by command shape, never by
guessing at paths.** The Edit/Write guard `check-worktree-path.sh` is the shape
to copy: it compares two `git rev-parse` results as strings and has never
produced a false positive.

**Don't add a prompt where git already refuses.** `git branch -D`, plain `git
worktree remove` and `git push --force-with-lease` are auto-allowed on purpose:
git itself blocks the dangerous case (it won't delete a branch checked out in
another worktree, won't remove a worktree holding uncommitted or untracked
files, and `--force-with-lease` won't clobber an update it hasn't seen). A
second prompt there buys nothing and costs a stall on every run — Step 4's
prune loop alone would have hit ~24 of them. The forcing variants (`--force`,
`-f`, `git tag -d`, `reflog expire`, `gc`) still ask, because those are the
ones that actually discard recoverable state. Likewise `gh` allows *authoring*
(`pr create`/`edit`/`comment`, `issue comment`) — that's the work product, and
`gh pr create` is the closing step of `implement-issue` — while publishing and
reconfiguring (`pr merge`, `release`, `repo edit`, `secret`, `workflow run`,
non-GET `gh api`) still ask. The `gh` safe list must also stay a superset of
settings.json's `gh` allow patterns, or a hook decision silently revokes a
permission you granted.

**Only tracked files travel into a worktree.** `.claude/settings.json` and
`.claude/hooks/*` are tracked and follow automatically;
`.claude/settings.local.json` is gitignored and therefore exists only in the
main checkout. A session that enters a worktree silently loses every rule and
mode set there while the tracked `ask:` list keeps applying — that asymmetry is
why an autonomous run in the main checkout starts prompting mid-worktree.
`.claude/hooks/link-worktree-local-settings.sh` symlinks it into every linked
worktree. Note what that does **not** buy you: a hook decision supersedes a
settings rule, so a Bash `deny`/`ask` you add to local settings is overridden
inside a worktree by the auto-allow. `defaultMode` and non-Bash rules survive
the trip; a Bash restriction has to go in the hook's own escape lists to have
any effect there. The same doesn't-travel problem applies to `.venv` and
`frontend/node_modules` (see `scripts/worktree-setup.sh`, issue #556).

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