---
name: implement-issue
description: Use when asked to implement, fix, or resolve a bess-manager GitHub issue end-to-end from the command line, especially when local verification (not just CI) is wanted before the PR opens.
---

# Implement Issue

## Overview

Drive a bess-manager GitHub issue from diagnosis to a locally-verified draft
PR against `main`. This is the CLI counterpart to the `@claude-bot analyze` +
`@claude-bot fix` pipeline (`docs/agents/workflow.md`) — same diagnose-then-fix
shape, but with the one thing the bot pipeline structurally cannot do: run the
app locally and observe the fix working before the PR opens. That local
verification step is the entire reason to run this from the command line
instead of the bot, so it is never optional.

This skill orchestrates other skills — it does not re-implement them:
`superpowers:using-git-worktrees`, `superpowers:test-driven-development`,
`superpowers:finishing-a-development-branch`, `code-review`, `verify`, and
the `bess-analyst` sub-agent.

## When to Use

- User gives you a bess-manager issue number/URL and asks you to implement,
  fix, or resolve it locally.
- Not for the `feature-lifecycle` multi-release integration flow (new
  inverter/price-provider platforms) — that skill owns experimental→stable
  graduation across multiple beta cycles. Use `implement-issue` for
  single-PR bug fixes and small enhancements.

## Process

### 1. Fetch & scope

```bash
gh issue view <n> --json title,body,labels,comments
```

Read chronologically for the CURRENT problem — issues evolve, don't fix a
stale complaint. Branch prefix from label: `bug` → `fix/`, `enhancement` →
`feat/`. Branch name: `<prefix>/issue-<n>-<slug>`.

### 2. Diagnose (conditional)

Check the issue comments for an existing Stage 2 diagnosis: a bot comment
with `## Root cause` / `## Evidence` / `## Proposed fix` sections (label
`analyzed`). This is the common case — issues are usually run through
`@claude-bot analyze` first.

- **Comment present:** use it as the diagnosis. Independently verify by
  reading the cited `file:line` locations against current code — quote real
  code, don't just trust the summary. Do NOT re-run `bess-analyst` from
  scratch.
- **Comment absent:** dispatch `bess-analyst` as a sub-agent (`Agent` tool,
  `subagent_type: bess-analyst`) for a full independent diagnosis — pass it
  the issue title, body, and comment history, and the task: "diagnose
  independently; the reporter's explanation is a hypothesis, not a
  conclusion."

### 3. Confirm gate

Present the root cause and proposed fix to the user. Wait for explicit
go-ahead before touching code. One message — cheap insurance against
building an entire implementation on a wrong diagnosis.

### 4. Worktree + branch

Invoke `superpowers:using-git-worktrees`.

### 5. TDD implementation

Invoke `superpowers:test-driven-development`. Write a test that reproduces
the bug (from the diagnosis's evidence — the specific period/scenario/input)
and watch it fail, then write the minimal fix. No refactors outside the bug
— match `docs/agents/patterns.md`.

### 6. Quality gate

```bash
./scripts/quality-check.sh
```

Zero errors. If it fails, fix and re-run — do not proceed with failures.

### 7. Code review

Invoke `code-review` (the project's `/code-review` skill). CONFIRMED
findings block progress — fix them before continuing. Everything else goes
to `TODO.md`. This runs BEFORE local verification (Step 8) on purpose: catch
cheap-to-fix issues before spending time on manual observation.

### 8. Local run & observe (never skip this)

Invoke the `verify` skill: actually exercise the fix and capture real
output — the reproducing mock-HA scenario via
`docker compose -f docker-compose.ci.yml`, a dev-server flow for frontend
changes, or the relevant CLI/pytest path with output inspected, not just its
exit code. A green test suite is necessary, not sufficient — this step is
what makes this skill worth running instead of the bot pipeline, and it is
not satisfied by re-stating that `quality-check.sh` passed.

### 9. Commit + draft PR

Commit per `docs/agents/workflow.md` format (subject + blank line + body
explaining WHY). Open a draft PR against `main` via
`superpowers:finishing-a-development-branch` (Option 2: push + PR), body:

```
## Summary
- <bullet>

## Root cause
<quote from the Step 2 diagnosis>

## Fix
<what changed and why>

## Test plan
- [ ] `./scripts/quality-check.sh` passes locally (already done)
- [ ] <what you actually observed in Step 8 — be concrete>

Closes #<n>
```

### 10. Hard constraints

- Draft PR only. Never auto-merge.
- Never push directly to `main`.
- Do NOT modify `CHANGELOG.md` or the version in `bess_manager/config.yaml`
  — that's a human step at merge time.
- If `quality-check.sh` keeps failing after 3 fix attempts, or Step 8 can't
  demonstrate the fix actually works, stop, push the branch as-is, and
  report what failed — don't force a PR through.

## Rationalizations — Reality

| Excuse | Reality |
|---|---|
| "quality-check.sh passed, that's enough" | Green tests prove the suite is satisfied, not that the fix behaves correctly against the real scenario. Step 8 requires observed output, every time. |
| "the diagnosis is obviously right, skip the confirm gate" | Wrong diagnoses are exactly when confidence is highest. One message, cheap insurance. |
| "I'll clean up this other thing while I'm in here" | Out of scope. Minimal fix only. |
| "code review can wait until after I've verified it works" | Reordered on purpose — catch cheap issues before spending time on manual verification, not after. |
| "there's already a bot diagnosis, let me re-derive it anyway to be safe" | Re-verify the cited evidence; don't redo the whole investigation. |
| "the user is in a hurry, just open the PR" | Time pressure from the user is not permission to skip Step 8 — it's the reason to say so explicitly and give a real ETA instead. |

## Red Flags — Stop and Go Back

- About to commit or open the PR without having actually run/observed the
  fix — only ran automated tests.
- About to skip the Step 3 confirm gate because of time pressure.
- About to open the PR before `/code-review` CONFIRMED findings are
  resolved.
- About to re-run the full `bess-analyst` diagnosis when a verified bot
  comment already exists.

## Quick Reference

| Step | Skill/Tool | Skippable? |
|---|---|---|
| 1. Fetch & scope | `gh issue view` | No |
| 2. Diagnose | `bess-analyst` (if no bot comment) | Conditional |
| 3. Confirm gate | — | No |
| 4. Worktree | `using-git-worktrees` | No |
| 5. TDD | `test-driven-development` | No |
| 6. Quality gate | `quality-check.sh` | No |
| 7. Code review | `code-review` | No |
| 8. Local run & observe | `verify` | **Never** |
| 9. Commit + PR | `finishing-a-development-branch` | No |
