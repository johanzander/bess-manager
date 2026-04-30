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

```
Issue opened       → issue-triage.yml fires automatically
                     → classifies, labels, requests debug log if needed
                     → posts root-cause analysis if debug log provided

User provides log  → analyze_log job fires automatically
                     → deeper analysis, suggests "@claude-bot fix this"

@claude-bot fix    → claude-bot.yml fires → issue_fixer.py
                     → explores codebase, implements fix, runs tests
                     → opens draft PR (human gate — never auto-merged)

@claude-bot review → claude-bot.yml fires → pr_reviewer.py
                     → checks against rules.md, posts review comment

YOU approve + merge → human decision, always
```

## PR Merge Workflow

1. **Review** — check diff for correctness, architecture fit, `rules.md` compliance
2. **Fix minor issues** — apply small fixes directly; request changes for anything substantial
3. **Update CHANGELOG** — add entry under new version heading, credit author:
   `(thanks [@username](https://github.com/username))`
4. **Bump version** in `config.yaml`:
   - `PATCH` (x.y.**Z**): bug fixes, doc/comment changes, no behavior change
   - `MINOR` (x.**Y**.0): new features, backwards-compatible
   - `MAJOR` (**X**.0.0): breaking changes
5. **Merge** — squash merge; wait for explicit user approval
6. **Tag** — after user confirms hardware test: `git tag vX.Y.Z && git push origin vX.Y.Z`

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

| Label | Meaning |
|-------|---------|
| `bug` | Confirmed defect |
| `enhancement` | Feature request |
| `question` | Usage/config question |
| `needs-debug-log` | Waiting for user debug export |
| `bot-analyzed` | Triage bot has processed this issue |
| `ready-for-review` | Draft PR ready for human review |

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
