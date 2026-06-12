# Development Workflow (Agent Reference)

> **Full guide**: `docs/DEVELOPMENT.md` — environment setup, Docker, VS Code,
> deploying to hardware. This file covers only agent-specific process rules.

## Git Commit Policy

**Never commit without explicit user instruction.**

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
3. **Update CHANGELOG** — add entry under new version heading, credit author:
   `(thanks [@username](https://github.com/username))`
4. **Bump version** in both `bess_manager/config.yaml` and `config.dev.yaml`:
   - `PATCH` (x.y.**Z**): bug fixes, doc/comment changes, no behavior change
   - `MINOR` (x.**Y**.0): new features, backwards-compatible
   - `MAJOR` (**X**.0.0): breaking changes
5. **Merge** — squash merge; wait for explicit user approval
6. **Release** — create a GitHub Release (tag `vX.Y.Z`, target `main`).
   This triggers `release-addon.yml` which builds per-arch Docker images
   (amd64 + aarch64) and pushes them to GHCR.
7. **Verify** — wait for the release workflow to complete, then confirm
   images are pullable: `docker pull ghcr.io/johanzander/bess-manager-amd64:X.Y.Z`

Never tag or merge without explicit user instruction.

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
