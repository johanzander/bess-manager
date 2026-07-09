# Development Workflow (Agent Reference)

> **Full guide**: `docs/DEVELOPMENT.md` — environment setup, Docker, VS Code,
> deploying to hardware. This file covers only agent-specific process rules.

## Git Commit Policy

**Never commit without explicit user instruction.**

**Before the first commit of new/unrelated work, check the branch.** Run
`git branch --show-current` and confirm it matches the work — new features
and specs get their own branch off `main`, never piggybacked onto whatever
branch happened to be checked out (e.g. an unrelated in-progress feature
branch). If it doesn't match, create/switch to the right branch first.

Good commit message format:

```
Fix settings not updating from config.yaml due to camelCase/snake_case mismatch

The update() method was checking for camelCase keys but dataclass attributes
use snake_case. Added conversion to properly map keys before validation.
```

Bad messages: `Fix issue`, `Update settings`, `Changes by bot`.

## Automated Issue Pipeline

Four-stage pipeline. Each stage is its own workflow file under
`.github/workflows/` and runs `anthropics/claude-code-action@v1`. There is
no cross-stage routing through CLAUDE.md — each stage's prompt is
self-contained.

```
Issue opened/edited  → issue-triage.yml      [auto, ~$0.05]
                       → classify, label
                       → if log present:    label `ready-for-analysis`
                       → if log missing:    label `needs-debug-log`,
                                            ask user for log

@claude-bot analyze  → issue-analyze.yml    [manual, ~$0.50–2]
                       → reads CLAUDE.md, docs/agents/, debug log
                       → delegates to `bess-analyst` sub-agent
                       → posts Root cause / Evidence / Proposed fix
                       → label `analyzed` (or `needs-human-review`)

@claude-bot fix      → issue-fix.yml        [manual, ~$1–4]
                       → reads Stage 2 diagnosis comment
                       → implements minimal fix, runs quality-check.sh
                       → opens DRAFT PR (never auto-merged)
                       → label `has-fix-pr`

@claude-bot review   → pr-review.yml        [manual, ~$0.50–2]
                       → reviews diff against rules.md + claude-bot.md
                       → posts inline comments + summary verdict

YOU approve + merge  → human decision, always
```

**Gates:** Stages 2, 3, and 4 are manually triggered — the bot never
spends money on its own. Stage 1 is auto but cheap.

## PR Merge Workflow

1. **Review** — check diff for correctness, architecture fit, `rules.md` compliance
2. **Fix minor issues** — apply small fixes directly; request changes for anything substantial
3. **Update CHANGELOG** — add entry under the `## [Unreleased]` heading (create it if a previous production release consumed it and it's currently missing), credit author:
   `(thanks [@username](https://github.com/username))`
4. **Bump version** in `bess_manager/config.yaml` (single source of truth):
   - `PATCH` (x.y.**Z**): bug fixes, doc/comment changes, no behavior change
   - `MINOR` (x.**Y**.0): new features, backwards-compatible
   - `MAJOR` (**X**.0.0): breaking changes
5. **Merge** — squash merge, only after **both** preconditions hold:
   - **a) All CI checks green**, including the Algorithm (slow) job (~30–46 min)
     when `core/bess/` changed. The **Merge gate** check (`ci-gate` job in
     `ci.yml`) aggregates every job and is the single required status check on
     `main` — it is green only when nothing genuinely failed.
   - **b) Explicit user approval** for this specific merge.

   Never use `gh pr merge --auto`. With branch protection it merges
   automatically the moment the required checks pass — removing the human
   "merge this PR now" decision (precondition **b**); and without protection
   (as was the case for #146) it merges *immediately*, bypassing CI entirely.
   Merge manually with `gh pr merge --squash` once green **and** approved.
6. **Release** — create a GitHub Release (tag `vX.Y.Z`, target `main`).
   This triggers `release-addon.yml` which builds per-arch Docker images
   (amd64 + aarch64) and pushes them to GHCR.
7. **Verify** — wait for the release workflow to complete, then confirm
   images are pullable: `docker pull ghcr.io/johanzander/bess-manager-amd64:X.Y.Z`

Never tag or merge without explicit user instruction.

## Spec & Plan Lifecycle

Superpowers produces two documents per feature: a **spec**
(`docs/superpowers/specs/`) and a **plan** (`docs/superpowers/plans/`).

- The **spec** is the durable design record — the *what and why* (problem,
  approach, decisions, trade-offs, acceptance criteria). Keep it, and keep it
  accurate; treat it like an ADR.
- The **plan** is execution scaffolding — the *how*, a step-by-step build
  checklist. Once the feature ships, the code and tests are the source of truth
  and the plan only drifts (it keeps referencing intermediate stubs that were
  deleted during implementation).

**Policy: when a feature is implemented and merged, delete its plan; keep its
spec.** The `finishing-a-development-branch` step should drop the plan as part of
completion. A completed feature's record is its spec + the code/tests, not the
build checklist.

## CHANGELOG Format

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added

- Short description. (thanks [@author](https://github.com/author))

### Fixed

- Short description.
```

One line per change. No implementation details. Match existing style.

## Labels

| Label | Applied by | Meaning |
|-------|------------|---------|
| `bug` | Stage 1 | Reported defect |
| `enhancement` | Stage 1 | Feature request |
| `question` | Stage 1 | Usage/config question |
| `needs-debug-log` | Stage 1 | Waiting for user debug export |
| `bot-analyzed` | Stage 1 | Triage bot has processed this issue |
| `ready-for-analysis` | Stage 1 | Debug log present, awaiting `@claude-bot analyze` |
| `analyzed` | Stage 2 | Root-cause diagnosis posted, awaiting `@claude-bot fix` |
| `needs-human-review` | Stage 2 | Stage 2 couldn't reach a conclusion |
| `has-fix-pr` | Stage 3 | Draft PR opened |

## Email Notifications

When a draft PR is opened by the issue fixer, two notifications fire:

1. **GitHub native** — the repo owner is auto-assigned, which triggers GitHub's
   own notification email. No extra setup needed.

2. **Direct email** — for a dedicated email with PR link and test/lint status,
   add two repository secrets (`Settings → Secrets → Actions`):

   | Secret | Value |
   |--------|-------|
   | `NOTIFICATION_EMAIL` | Address to send to (and from, if using Gmail) |
   | `SMTP_PASSWORD` | Gmail App Password (not your login password) |

   Gmail App Password: `myaccount.google.com → Security → App passwords`.
   Defaults to `smtp.gmail.com:587`. Override with `SMTP_HOST`, `SMTP_PORT`,
   and `SMTP_FROM` secrets if using a different provider.

   If the secrets are absent the step is silently skipped.

## Quality Gate

Before any PR: `./scripts/quality-check.sh` must pass with zero errors.
