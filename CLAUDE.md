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

### Permissions

**An agent should run end-to-end without approving anything.** Prompts are the
cost, not the safety: a stalled autonomous run is a guaranteed loss, while the
commands that used to prompt are recoverable. Only two shapes still ask, and
both reach past the repository where nothing local can contain them:
`git push --force` and `sudo`. Two are denied outright: the shared podman VM
(`machine rm`, `system reset`) and `git stash`. **That is the entire list.**
Everything else — `rm`, `git reset --hard`, `rebase`, `merge`, `git branch -D`,
`git worktree remove` — runs unattended. Do not add to the list because a
command *looks* dangerous; add to it only when the effect escapes the repo and
git cannot undo it.

**`defaultMode` is `auto`, and it is what makes the list above short enough to
work.** The `allow` list cannot enumerate what an issue actually needs — a
single `implement-issue` run reaches for compose, npm, python3, mkdir, cp and
a dozen one-off shapes nobody predicted — so under the plain `default` mode
everything unlisted prompts and the run stalls dozens of times. `auto` sends
those to a classifier instead, which decides without involving you; `deny` and
`ask` still bind on top of it. This lives in the **tracked** settings on
purpose: `defaultMode` is not a Bash rule, so it travels into every worktree by
itself. Putting it in the gitignored `settings.local.json` is what made an
autonomous run in the main checkout start prompting the moment it entered a
worktree, and what the deleted symlink hook existed to paper over.

The two `Bash` permission hooks that used to shape this are gone:
`auto-allow-worktree-destructive.sh` (a cwd-conditional auto-allow) and
`link-worktree-local-settings.sh` (a SessionStart symlink undoing the asymmetry
the first one created). They existed to express what settings.json could not,
and cost six false positives in a single day, *every one introduced by the fix
to the previous one*, including blocking a live beta release. With nothing left
to auto-allow around, the plain rules say it directly. Do not reintroduce a hook
to route around a prompt — delete the `ask` entry instead, and remember `deny`
beats `ask` beats `allow`, so adding an `allow` never cancels an `ask`.

`check-worktree-path.sh` stays. It guards Edit/Write, not Bash, and it is the
one thing here that has never produced a false positive: it compares two `git
rev-parse` results as strings and refuses an edit aimed at a different checkout
than the session's cwd. That is the failure this repo actually hits — a stale
absolute path from an earlier turn writing into the main checkout while ~20
worktrees are live — and unlike the Bash guards it never has to parse a command.
Anything added here must be that shape: compare resolved paths, never guess at
what a command string will touch.

**Never `git stash` — it is denied, everywhere in this repo.** There is exactly
one `refs/stash` per repository, shared by the main checkout and every worktree,
and the stack has no owner: one agent's `git stash` pushes an entry that another
agent's `git stash pop` will take, with no way to tell it was not theirs. With
~20 worktrees active that silently destroys work, and once popped and discarded
git offers no recovery. `permissions.deny` lists every mutating form (bare `git
stash`, `push`, `save`, `pop`, `apply`, `drop`, `clear`, `branch`, `create`,
`store`); `git stash list`/`show` still work. The rules match the command as
written, so a prefixed form such as `git -C <dir> stash pop` slips past — don't
reach for one.

**The OS sandbox is what makes the unattended list safe, and it is on.**
`sandbox.enabled` confines every Bash write to the repository, decided by the OS
from the actual syscall rather than guessed from a command string. That is why
`rm -rf` needs no prompt: outside the repo it cannot create *or* unlink — the
macOS profile denies `file-write-create` and `file-write-unlink` in one rule.

**`allowWrite` must name the repo root, and that is the whole trick.** Writes
are `allowOnly` minus `denyWithinAllow`, and the built-in `allowOnly` is only
`/dev/*`, `/tmp/claude`, `~/.npm/_logs` and `~/.claude/debug` — **the repository
is not in it**. So `allowWrite: ["."]` is what opens the repo at all. An earlier
attempt set `allowWrite: [".claude", ".git", "scripts"]`, three paths that are
all on the deny list, never opened the repo root, and concluded from the
resulting breakage that the sandbox was unusable. It isn't; that config was.

**What stays denied cannot be re-opened.** There is no allow-within-deny
primitive for writes (reads have one, which is why `allowRead` differs), so no
`allowWrite` entry overrides the built-in `denyWrite` list. Confirmed by
`verify-sandbox.sh`:

- **Create worktrees with `EnterWorktree`, never `git worktree add` from Bash** —
  the harness is not sandboxed; the Bash form writes `.git/config` and
  `.git/worktrees`, both denied. *(measured)*
- **`.git/objects`, refs and the index are NOT denied**, so commit, branch,
  reset and reflog work normally. *(measured — this is the one that matters)*
- The agent-config files are denied individually — `.claude/settings.json`,
  `.claude/hooks`, `.claude/skills`, `.claude/workflows`, `.claude/routines`,
  `.claude/output-styles`, `.claude/launch.json`, `.mcp.json` — but **not the
  `.claude` directory as a whole**. Edit those files with the Edit/Write tools,
  which the sandbox does not govern at all. *(measured)*
- `scripts/**` is **writable** from Bash. *(measured)* An earlier claim here
  that it was denied, along with `.github/` and the lockfiles, came from
  misreading the binary's *GitHub Actions* default config (it listed
  `~/actions-runner` and `GITHUB_EVENT_PATH`) as the local one.

**`sandbox.*` live-reloads when a settings file is edited — it is NOT read only
at session start.** The opposite is written all over the abandoned
`chore/sandbox-replaces-worktree-hook` branch and was repeated into this file;
it is wrong. Editing `.claude/settings.json` mid-session activated the sandbox
in the session that made the edit, which then verified its own config. So you
*can* iterate on `sandbox.*` in one session — just re-run `verify-sandbox.sh`
after each edit rather than trusting the change landed.

### Known-broken under the sandbox (unresolved)

Both break `implement-issue`, and neither has the cause its old remedy text
guessed. Do not re-diagnose from scratch:

- **`gh` — the macOS keychain, not the network.** `gh auth status` returns *"The
  token in keyring is invalid"*: gh reads its token from the keychain and the
  sandbox blocks that. `enableWeakerNetworkIsolation` addresses TLS/`trustd` and
  would not have helped. Blocks `gh pr create`, the closing step of Step 9.
- **`podman` — a local TCP port, not a unix socket.** `podman info` returns
  *"dial tcp 127.0.0.1:64752: connect: operation not permitted"*, so
  `filesystem.allowRead` and `network.allowUnixSockets` are both wrong knobs.
  Blocks every E2E run, i.e. Step 8.
- `sandbox.excludedCommands` in `~/.claude/settings.json` and
  `network.allowLocalBinding` in project settings were both tried and neither
  took effect. Claude Code's own "exclude this command" action writes
  `excludedCommands` to `userSettings`/`localSettings`, never to project
  settings, so user settings is the right home — but it did not exempt `gh`
  either. Unresolved.
- **`frontend/node_modules` is a symlink into the main checkout**, so writes
  through it land outside a worktree's `allowWrite: ["."]` root and fail with
  `EPERM`. That breaks `vitest`, `vite build`, and therefore Step 6's quality
  gate in every worktree. A user-level `allowWrite` naming the main checkout
  would cover it (worktrees are nested inside), but an absolute path cannot live
  in tracked settings. Same applies to `.venv`.

**Verify with `bash scripts/verify-sandbox.sh` after any change to `sandbox.*`,
and let the Bash tool run it.** A plain terminal is not sandboxed — the sandbox
applies to commands Claude Code itself runs — so a shell invocation prints
`NOT RUNNING UNDER THE SANDBOX` and checks nothing. The script's check 0 exists
to catch exactly that. A fresh session is not required (see live-reload above),
but re-running the script after each edit is, since a settings change can fail
to apply silently.

To set work aside on the branch you are on, use a temporary WIP commit — it
lives on the branch, so it is per-worktree, private to that agent, and
recoverable by SHA even if the branch moves:

```bash
git add -A && git commit -m "wip: <what>"   # set aside
git reset --soft HEAD~1                     # pick back up
```

To move changes *across* checkouts (the case stash used to cover), pipe a patch
through the shared object database — verify it landed before reverting, since
`git checkout --` is the destructive step and there is no stash to fall back on:

```bash
git diff -- <file> | git -C .claude/worktrees/<name> apply
git -C .claude/worktrees/<name> diff -- <file>   # verify
git checkout -- <file>                           # only then
```

The full procedure, including the staged-changes variant, is in
`docs/agents/rules.md` under Working Location.

**The Bash rules apply identically in the main checkout and in every worktree.**
There is no cwd-conditional behaviour left, so nothing changes when a session
enters a worktree.

**Don't add a prompt where git already refuses.** `git branch -D`, plain `git
worktree remove` and `git push --force-with-lease` are deliberately not in the
`ask` list: git itself blocks the dangerous case (it won't delete a branch
checked out in another worktree, won't remove a worktree holding uncommitted or
untracked files, and `--force-with-lease` won't clobber an update it hasn't
seen). A second prompt there buys nothing and costs a stall on every run —
`implement-issue` Step 4's prune loop alone would have hit ~24 of them.

**What the unattended set actually risks is uncommitted work**, since the
sandbox that would have contained it is unavailable (below). Tracked content
survives anything on the list — `git reset --hard` and `rm` on a tracked file
are both recoverable from the object database, and a discarded commit is
recoverable by SHA from the reflog. Uncommitted, untracked work is not. That is
the argument for the WIP-commit habit below, and it is why `git stash` is denied
rather than merely prompted: it is the one command that destroys another agent's
uncommitted work rather than your own.

**Only tracked files travel into a worktree**, and the permission setup is now
entirely tracked: `.claude/settings.json` and `.claude/hooks/*` follow every
worktree automatically, so a session behaves the same wherever it runs. Keep it
that way. `.claude/settings.local.json` is gitignored and exists only in the
main checkout; the previous design leaned on it and then needed a SessionStart
hook to symlink it into each worktree to undo the asymmetry. Anything that has
to hold in a worktree belongs in the tracked settings. The doesn't-travel
problem still applies to `.venv` and `frontend/node_modules` (see
`scripts/worktree-setup.sh`, issue #556).

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