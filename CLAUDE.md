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

- Only the repo owner can trigger bot commands. The one exception is Stage 4:
  `pr-review.yml` also accepts `@claude-bot` from the developer automation
  identity (currently the `bess-agent` GitHub account; being renamed to
  `bess-developer` — see `scripts/gh-agent.sh`), so `implement-issue`'s
  Step 11 loop can request its own review. `bess-developer` is added to that
  gate only in the same commit that renames the account — never before,
  since pre-authorising an unregistered username on a public repo is
  exploitable. Stages 1–3 and 5 stay owner-only — those spend money on work
  nobody has asked for yet.
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

**An agent should run end-to-end without approving anything that the sandbox
already contains.** Prompts are the cost, not the safety: a stalled autonomous
run is a guaranteed loss, while anything the sandbox bounds is recoverable.
`rm`, `git reset --hard`, `rebase`, `merge`, `git branch -D`, `git worktree
remove` all run unattended. **A `git push` naming a feature branch runs
unattended too**; a push that forces, deletes a ref, publishes a tag, or targets
`main`/`master`/`beta` asks — see below for how that line is drawn.

What still asks is one closed list, and every entry is there because the
**sandbox cannot contain it** — it bounds the filesystem, not the network, and
not `.git`'s own recovery data:

| Category | Rules |
|---|---|
| Escapes to GitHub | **a `git push` that forces / deletes a ref / publishes a tag / targets `main`, `master` or `beta`**, **every `gh api`**, `gh pr merge`, `gh release create` / `edit` / `delete` / `delete-asset` / `upload`, `gh repo edit`, `gh secret`, `gh workflow run` |
| Destroys the recovery mechanism | `git gc`, `git prune`, `git repack`, `git maintenance`, `git reflog expire`, `git reflog delete`, `git update-ref`, `git tag -d` / `--delete` / `-f` |
| Leaves the user boundary | `sudo` |

Each of those also has a `git -* <verb>` twin covering the global-option
spelling (`git -C <path> gc`, `git --no-pager push`). The twins name a **verb**
on purpose: a blanket `Bash(git -*)` was tried and put read-only inspection —
`git -C sub status`, `git -C <wt> diff`, the verify step of the cross-checkout
patch recipe — behind a prompt, and it shadowed the `git commit` allow via
`git -c user.email=… commit`.

**`*` compiles to a greedy `.*` that spans spaces**, which bounds how precise
any of this can be. `git -* push*` therefore also matches a `git -c … commit`
whose *message* contains " push". That is an extra prompt, not a gap, and it is
accepted — the alternative is dropping the global-option guard on push, which
is a real bypass. When the choice is between a false prompt and a hole, take
the prompt. The one case where that trade flips is `deny`, which has no
override: an over-broad deny **blocks** documented work rather than prompting
for it, which is why `git prune` has no twin (it caught `git worktree prune`,
and Step 4 prunes in a loop) and why the stash twins are per-verb.

Denied outright: the shared podman VM (`machine rm`, `system reset`) and every
mutating `git stash` form, **including `git -C <path> stash …`**. That last
clause is load-bearing rather than decorative: the global-option spelling was
briefly covered only by an `ask`, and since `deny > ask` applies by category, a
matching `ask` with no matching `deny` turns a prohibition into a prompt. The
gate checks stash and podman shapes against `deny` **only** for that reason.

The standard for adding an entry: **the effect escapes the repo and git cannot
undo it.** Not "the command looks dangerous". Both halves have to hold, which
is why **`gh pr ready` is deliberately unattended** even though it plainly
escapes to GitHub: `gh pr ready --undo` puts the PR straight back, it changes
no content (the diff was already public — the `git push` that created it
prompted), and it is the codified endpoint of `implement-issue` Step 11's
review loop. Prompting there would stall the one flow whose entire point is to
reach that state without you. Contrast `gh pr merge` one row up, which is the
same category and *is* gated: nothing undoes a merge to `main`.

**`gh release` names its verbs for the same reason.** The standard is "the
effect escapes the repo *and* git cannot undo it" — `gh release list` and `gh
release view` fail the first half outright, since reading changes nothing on
GitHub. A blanket `gh release*` therefore prompted on the exact command the
release rule above *requires* ("always check the current published version
before tagging"), and on every beta/stable version comparison. `create`,
`edit`, `delete`, `delete-asset` and `upload` still ask; `list`, `view` and
`download` run unattended, and `quality-check.sh` pins both halves so the
split cannot collapse back into either a blanket rule or a hole.

The second category exists
because leaving `rm` and `reset --hard` unattended is only defensible while the
object database and reflog can recover them — a `gc --prune=now` that ran
unprompted would remove the ground that argument stands on.

**`gh api` is guarded bluntly, and that is deliberate. `git push` no longer is,
and that took three tries to get right.** Both were enumerated by shape first,
and both leaked:

```
git push origin main --force          # --force not adjacent to `push`
git push origin +beta-release-9.9     # force via refspec
git push origin --delete release-X.Y  # destroys a shared ref
git push origin v9.9.0                # publishes a release tag
git push origin HEAD:main             # protected ref via colon refspec
git push origin refs/heads/main       # bare source-side refspec: no space, no colon
git push origin refs/tags/v1.2.3      # same, for a TAG: `*:refs/tags/*` saw only the colon form
git push --all                        # every local branch, main included
git push --branches origin            # exact synonym for --all
gh api repos/o/r/pulls/N/merge -X PUT # merges, bypassing `gh pr merge`
gh api <path> -f key=val              # any -f/-F makes it a POST
```

**The last three were found by the Stage 4 review of the PR that fixed the
first five**, which is the point worth remembering: each round of this
enumeration has been incomplete, and each hole was invisible to the round
before. `refs/heads/main` slipped because every protected-branch rule keyed off
the character *before* the branch name — a space in `* main`, a colon in
`*:main` — and in `refs/heads/main` that character is `/`. The guards are now
spelled `*refs/heads/main*` without the colon, which subsumes the
destination-side form rather than sitting beside it. `--all` slipped because
its neighbours `--mirror`, `--prune` and `--tags` were all covered and it
simply was not; `--branches` is its documented synonym (`git push --help`:
"--all, --branches") and was added in the same pass rather than waiting to
become the fourth leak.

`refs/tags/` had the same colon-shaped blind spot as `refs/heads/`, and it is
the one entry here that **branch protection can never replace**: a tag is not a
branch, so no protected-branch setting covers publishing a release tag. Both
guards are now spelled without the colon (`*refs/tags/*`, `*refs/heads/main*`),
each subsuming its destination-side form rather than sitting beside it.

The marker sits at an arbitrary argument position. The first enumeration was
**prefix-anchored** — `Bash(git push --force*)` — which genuinely cannot reach
position 3, so it leaked every line above and was replaced by a blanket
`Bash(git push *)`. That blanket rule was justified here by the claim that "a
prefix glob cannot reach it", **and that claim was wrong**: `*` compiles to `.*`
under `re.fullmatch` and spans spaces, so `Bash(git push *--force*)` matches
`git push origin main --force` perfectly well. The very next paragraph about
greedy globs said so all along; the two contradicted each other for four review
rounds.

**The protected-ref half of that enumeration is now GONE, and branch protection
replaces it.** `enforce_admins` is `true` on `origin/main` and `beta/main`, so
GitHub refuses a push to `main` server-side — including from the owner token
every agent uses. That is a *provable* guarantee; an enumeration of command
spellings is only ever a list of the ones somebody thought of, and that list
leaked three times, the last two spellings (`git push origin refs/heads/main`,
`git push --all`) found by the review of the PR meant to fix it. A fourth round
was the expected outcome of keeping it.

So `git push origin main`, `HEAD:main`, `refs/heads/main`, `-u origin main`
and the `master` equivalents now run unattended and are rejected by GitHub
instead of by a prompt.

**`enforce_admins: true` is therefore LOAD-BEARING.** Turn it off and this repo
has no guard on pushing to `main` at all. `quality-check.sh` asserts it on both
remotes for exactly that reason — a false answer is an error naming the fix, an
unreadable one is a warning, because a CI token cannot read branch protection
and "I could not check" is not "it is off". If it ever fires, either re-enable
the setting or restore the protected-ref patterns; do not silence the check.

What stays guarded is what branch protection does **not** cover — and each of
these is a real gap, not belt-and-braces:

- **force in any position**, `--force-with-lease` included, and refspec `+`
- **ref deletion**, `--mirror`, `--prune`, `--tags`, `--all`, `--branches`
- **tags**: `refs/tags/` on either side, and `* v*`. A tag is not a branch, so
  no protected-branch setting will ever cover publishing a release tag
- **the `beta` remote**, and `beta-release-*` branches on origin. Only `main`
  is protected, so these are still ours

A push naming a feature branch runs unattended, which is what
`implement-issue` Step 9 and `sweep-prs` actually do.

`gh api` keeps its blanket rule because it is **not** separable this way: any
`-f`, `-F` or `-X` turns a read into a mutation, so there is no lexical marker
that isolates the safe subset. If it starts stalling runs, the fix is an
allow-list of read-only paths, not a shape guard.

`quality-check.sh` pins all of this by COMMAND STRING in three lists, never by
rule name. Adding a rule that "looks right" without adding its command string is
how every previous version of this section went stale.

**But the gate proves "the strings we thought of are covered", not "no push
spelling reaches a protected branch"** — and after three incomplete rounds that
distinction is the honest summary of where this stands. The durable fix is
normalisation: resolve a refspec's effective destination ref before matching,
instead of pattern-matching the raw command string. That is tracked separately;
until it exists, treat any newly-discovered spelling as expected rather than
surprising, and add it to `MUST_BE_GUARDED` first.

**Patterns match the command as written — prefix globbing, no normalisation.**
This is the single biggest source of rules that look right and match nothing,
and it produced a bug here in four consecutive review rounds.

**Nothing normalises `git`'s global options**, so `git -C <path> stash pop`,
`git --git-dir=… push`, `git -c k=v push` and `git --no-pager gc` sidestep every
rule anchored on `git stash` / `git push` / `git gc`. The deleted hook
normalised for exactly this — and CLAUDE.md itself teaches `git -C
.claude/worktrees/<name>` as the cross-checkout idiom, so it is the spelling an
agent reaches for first. `Bash(git -*)` covers the whole class in one rule,
including options nobody has thought of yet. Do not replace it with an
enumeration.

**`scripts/quality-check.sh` asserts this by COMMAND STRING, not by rule name.**
Presence checks — "is rule X in the list" — passed for four review rounds while
real spellings slipped through, because they answer the wrong question. The gate
now carries ~56 real command strings in three lists, using the same prefix-glob
semantics the harness applies:

- `MUST_BE_DENIED` — checked against `deny` **only**, so a matching `ask` cannot
  certify a command that policy says is unapprovable.
- `MUST_BE_GUARDED` — checked against `deny` + `ask`; a prompt is acceptable.
- `MUST_NOT_BE_GUARDED` — read-only git that must stay unattended. This is what
  catches a rule that is too *broad*, the failure the blanket `Bash(git -*)`
  introduced.

When a new bypass spelling turns up, add the string to the right list first —
then fix the rule until the gate goes green.

**A rule that fails to match does not fall through to the `auto` classifier.**
It falls through to whatever `allow` rule covers the command — here
`Bash(git push *)` in project settings and `Bash(git *)` in user settings — and
runs unattended. Precedence is `deny > ask > allow` **by category**, not by
specificity, so a broad `allow` is only ever overridden by an `ask` that
actually matches. That is why a too-narrow `ask` is worse than no rule: it
reads as covered while changing nothing.

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
`store`), **each with a `git -* stash <verb>` twin**, so the global-option
spelling `git -C <dir> stash pop` is denied too — that is the form the
cross-checkout recipe below would otherwise reach for, and it was a live
bypass until #596.

`git stash list` and `git stash show` still work, in both spellings. The twins
name a verb for exactly that reason: a blanket `git -* stash *` deny also
caught `git -C sub stash list`, and `deny` has no override, so it hard-blocked
inspection rather than merely prompting for it. `scripts/quality-check.sh` pins
both directions — the mutating forms must match a **deny**, the read-only forms
must match **nothing**.

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
- **`git checkout -b <branch> origin/<branch>` fails**, because recording the
  upstream writes `.git/config` — and it fails *after* creating the branch, so
  the branch exists while the command reports an error and leaves you on the
  old one. Use `git checkout -b <branch> --no-track origin/<branch>`, or just
  re-run `git checkout <branch>`. Set upstream at push time with
  `git push -u`. *(measured)*
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

**The sandbox captures its policy ONCE, at activation, and ignores every later
edit. You cannot iterate on `sandbox.*` in one session.** The trap is that it
*looks* like you can: editing `.claude/settings.json` mid-session does activate
the sandbox, so a session that turns it on immediately finds itself sandboxed
and concludes the config live-reloads. It does not. Every subsequent edit —
widening `allowWrite`, adding `allowMachLookup`, anything — is silently ignored
while probes keep returning confident results measured against the *first*
config. This was learned the expensive way: four knobs were "tested" that way
and none of the results meant anything. A probe write to a path added to
`allowWrite` minutes earlier still returned `Operation not permitted`, which is
what exposed it.

**So: one config change, then a genuinely fresh session, then
`verify-sandbox.sh`.** Never a second edit in the same session. If a result
contradicts the config you are looking at, the config is not what is running.

### Why each non-default knob is there

All four were verified together by a fresh-session `verify-sandbox.sh` run.
Each exists for one measured failure — don't drop one because it looks
redundant:

- **`enableWeakerNetworkIsolation`** — `gh` is a Go binary and returned
  *"tls: failed to verify certificate: x509: OSStatus -26276"*: it cannot reach
  `trustd` to verify TLS. Egress itself was never the problem — `curl
  https://github.com` returned 200 in the same sandbox. This is the documented
  knob for exactly this, and it is explicitly weaker: it opens `trustd`, which
  is a potential exfiltration path.
- **`network.allowMachLookup`** (`SecurityServer`, `securityd`, `trustd`) —
  `gh auth status` returned *"The token in keyring is invalid"*. gh reads its
  token from the macOS keychain, which is XPC, not network. The same block is
  why `git push` emitted `failed to store: 100001` — the credential helper
  could not cache the credential, though the push itself still landed.
- **`network.allowLocalBinding`** — `podman info` returned *"dial tcp
  127.0.0.1:64752: connect: operation not permitted"*. The podman VM is reached
  over a local TCP port, so `filesystem.allowRead` and
  `network.allowUnixSockets` are both the wrong knob.
- **`filesystem.allowWrite: [".", "~/GitHub/bess-manager"]`** —
  `frontend/node_modules` and `.venv` are symlinks into the main checkout, so
  writes through them land outside a worktree's own root and fail `EPERM`,
  breaking `vitest` and `vite build`. Native worktrees live under
  `.claude/worktrees/`, i.e. *inside* the main checkout, so that one entry
  covers them and every symlink target. That entry hardcodes this machine's
  layout, which is ugly in a tracked file; it is there because the alternative,
  a user-level `allowWrite`, is refused by the auto-mode classifier —
  correctly, since that is a session widening its own containment.

  **It does not cover a sibling checkout.** `../bess-manager-feature/` sits
  under `~/GitHub/`, not `~/GitHub/bess-manager`, so it is writable only via
  the `"."` entry resolving to that session's own cwd. A session working *on* a
  sibling from elsewhere — the main checkout, or another worktree — is silently
  blocked. Sibling folders are still first-class for running and inspecting
  code; they just need their own `allowWrite` entry if a session has to reach
  one from outside. `verify-sandbox.sh` skips its symlink check outside a
  linked worktree rather than reporting a PASS that proves nothing.

`sandbox.excludedCommands` is **not** used and is not needed. It was tried in
both project and user settings while the four knobs above were missing, appeared
to do nothing, and is now moot.

**What the verification does and does not cover.** It exercises `gh auth
status` (the keychain and TLS paths — good coverage of what `gh pr create`
needs) and `podman info` (the socket/TCP connection only, *not* that a compose
E2E completes). A full Step 8 run and a `gh pr create` are still the first real
proof. If either fails, re-read the error before touching config: every knob
here was found by reading the actual message, and every wrong guess came from
reasoning about what *ought* to be blocked.

**Verify with `bash scripts/verify-sandbox.sh` in a FRESH session after any
change to `sandbox.*`, and let the Bash TOOL run it.** Fresh because of the
capture-once behaviour above. Bash tool because the sandbox applies only to
commands Claude Code itself runs — a `!`-prefixed or terminal-typed invocation
is unsandboxed and would pass the permissive checks while failing the
restrictive ones, which reads exactly like a real result. Check 0 catches that.

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

**Don't add a prompt where git already refuses.** `git branch -D` and plain
`git worktree remove` are deliberately not in the `ask` list: git itself blocks
the dangerous case (it won't delete a branch checked out in another worktree,
and won't remove a worktree holding uncommitted or untracked files). A second
prompt there buys nothing and costs a stall on every run — `implement-issue`
Step 4's prune loop alone would have hit ~24 of them.

`git push --force-with-lease` **still asks**, and unlike the ordinary
feature-branch push it is not carved out. `Bash(git push *--force*)` catches it
at any argument position, and that is intended: a lease makes the force safer
against a *concurrent* writer, not against a wrong local history.

**That prompt costs nothing here, which is why it stays.** Neither
`implement-issue` nor `release` mentions `rebase`, `--force` or
`--force-with-lease` anywhere, and this project merges the target branch before
a PR instead of rebasing — a merge-based flow never needs a force push. So the
rule should lie dormant. **If it ever fires, treat that as the finding**: an
agent has gone off-script into a rebase or an amend of already-pushed commits.
Answer the prompt on its merits; do not "fix" it by widening what runs
unattended — that is how the gaps PR #596 had to close were introduced in #588.
The feature-branch carve-out is safe precisely because it is defined by what the
command *lacks* (no force, no `+`, no `--delete`, no tag, no protected ref),
with every one of those shapes pinned by command string in the gate.

**What the unattended set actually risks is uncommitted work**, since the
sandbox contains writes to the repo but cannot distinguish a wanted write from
an unwanted one. Tracked content
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