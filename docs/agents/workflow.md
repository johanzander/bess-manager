# Development Workflow

## Git Commit Policy

**Never commit without explicit user instruction.**

Good commit message format:

```
Fix settings not updating from config.yaml due to camelCase/snake_case mismatch

The update() method was checking for camelCase keys but dataclass attributes
use snake_case. Added conversion to properly map keys before validation.
```

Bad commit messages: `Fix issue`, `Update settings`, `Changes by bot`.

## PR Merge Workflow

1. **Review** — Read the diff, check for correctness, architecture fit, CLAUDE.md compliance.
2. **Fix minor issues** — Apply small fixes directly. For substantial issues, request changes.
3. **Update CHANGELOG** — Add entry under new version heading. Credit author:
   `(thanks [@username](https://github.com/username))`
4. **Bump version** in `config.yaml`:
   - `PATCH` (x.y.**Z**): bug fixes, doc/comment changes, no behavior change
   - `MINOR` (x.**Y**.0): new features, backwards-compatible
   - `MAJOR` (**X**.0.0): breaking changes
5. **Merge** — Squash merge. Wait for explicit user approval.
6. **Tag** — After user confirms hardware test: `git tag vX.Y.Z && git push origin vX.Y.Z`

Never tag or merge without explicit user instruction.

## CHANGELOG Format

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added

- Short description of new feature. (thanks [@author](https://github.com/author))

### Fixed

- Short description of fix.
```

One line per change. No implementation details. Match the existing style.

## Issue → PR Pipeline

The automated pipeline (via GitHub Actions):

1. Issue opened → triage bot classifies, requests debug log if needed
2. User provides debug log → bot analyzes, identifies root cause
3. User comments `@claude-bot fix this` → fix bot implements, runs tests, opens draft PR
4. User comments `@claude-bot review` on PR → review bot checks against rules.md
5. **User approves and merges** (human gate — never automated)

## Labels

| Label | Meaning |
|-------|---------|
| `bug` | Confirmed defect |
| `enhancement` | Feature request |
| `question` | Usage/config question |
| `needs-debug-log` | Waiting for user to provide debug export |
| `bot-analyzed` | Triage bot has processed this issue |
| `ready-for-review` | Draft PR is ready for human review |

## Quality Checks

Before any commit, run:

```bash
./scripts/quality-check.sh
```

Or individually:

```bash
black .
ruff check --fix .
cd frontend && npm run lint:fix
pytest
```

All checks must pass. Zero tolerance for linter errors.
