# `implement-issue` Skill (Design Spec)

**Date:** 2026-07-03
**Status:** Approved design, pre-implementation
**Goal:** A project-scoped, discipline-enforcing skill that takes a bess-manager
GitHub issue from diagnosis to a locally-verified draft PR against `main` —
the CLI counterpart to the `@claude-bot analyze` + `@claude-bot fix` pipeline.

## Problem

The user repeatedly runs the same manual sequence: review an issue as
`bess-analyst`, set up a worktree + branch, implement with TDD, and open a PR
to `main`. This duplicates most of `issue-analyze.yml` + `issue-fix.yml`
(`docs/agents/workflow.md`), but the CLI version has one capability the bot
pipeline structurally lacks: **the ability to actually run the app and observe
the fix working before the PR opens.** The bot only runs
`./scripts/quality-check.sh`; it cannot start a dev server, run a mock-HA
scenario, or eyeball real output.

That local-verification step is the reason to do this from the command line at
all, so it must be a required, non-skippable gate — not an optional nicety.

## Non-goals

- Not a replacement for the bot pipeline — both are kept; this is for issues
  the user wants to drive interactively with local verification.
- Not for the `feature-lifecycle` multi-release-cycle flow (new inverter/price
  provider integrations) — that skill already owns experimental→stable
  graduation. `implement-issue` is for single-PR bug fixes and small
  enhancements.
- Does not touch CHANGELOG.md or version bump — those stay a human step at
  merge time (`docs/agents/workflow.md` PR Merge Workflow).
- Does not merge or push to `main` directly.

## Design

### Step 1 — Fetch & scope

```
gh issue view <n> --json title,body,labels,comments
```

Read chronologically for the **current** problem (issues evolve; the bot's
own Stage 1 does this too). Branch prefix from label: `bug` → `fix/`,
`enhancement` → `feat/` (per user's existing feat-branch convention). Branch
name: `<prefix>/issue-<n>-<slug>`.

### Step 2 — Diagnose (conditional)

Check whether the issue already carries a Stage 2 diagnosis: a comment from
the bot identity with `## Root cause` / `## Evidence` / `## Proposed fix`
sections (label `analyzed`). This is the common case — the user usually runs
`@claude-bot analyze` before reaching for this skill.

- **If present:** use it as the diagnosis. Independently verify by reading the
  cited `file:line` locations against current code (mirrors
  `issue-analyze.yml` step 3 — quote real code, don't just trust the summary).
  Do not re-run `bess-analyst` from scratch.
- **If absent:** dispatch `bess-analyst` as a sub-agent (`Agent` tool,
  `subagent_type: bess-analyst`) for a full independent diagnosis, same task
  framing as `issue-analyze.yml`.

### Step 3 — Confirm gate

Present root cause + proposed fix, wait for explicit go-ahead before touching
code. Cheap insurance against building on a wrong diagnosis — one round trip,
not a heavyweight review.

### Step 4 — Worktree + branch

`superpowers:using-git-worktrees`.

### Step 5 — TDD implementation

`superpowers:test-driven-development`: a test that reproduces the bug (from
the diagnosis's evidence — the specific period/scenario) fails first, then the
minimal fix. No drive-by refactors (rules.md scope discipline already
governs this).

### Step 6 — Quality gate

`./scripts/quality-check.sh`, zero errors.

### Step 7 — Code review

`/code-review`. CONFIRMED findings block progress — fix before continuing;
everything else goes to TODO.md. **Placed before local verification** so
code-quality issues are caught before spending time on manual observation.

### Step 8 — Local run & observe (the differentiator)

Invoke the `verify` skill: actually exercise the fix — the reproducing
mock-HA scenario, dev server flow, or relevant CLI path — and capture real
output (log excerpt, screenshot, scenario diff), not just a green test run.
This step is what the bot pipeline cannot do and is the entire reason this
skill exists; it is never skipped because "tests already pass."

### Step 9 — Commit + draft PR

Commit per `docs/agents/workflow.md` format. Open a **draft** PR against
`main` via `superpowers:finishing-a-development-branch` (Option 2), using the
`issue-fix.yml` PR body template (Summary / Root cause / Fix / Test plan,
`Closes #<n>`).

### Step 10 — Hard constraints

- Draft PR only, never auto-merge.
- Never push to `main` directly.
- Do not modify CHANGELOG.md or `config.yaml` version.
- If quality-check.sh keeps failing after 3 fix attempts, or the fix can't be
  made to demonstrably work in Step 8, stop, push the branch as-is, and report
  what failed so the user can take over — don't force a PR through.

## Discipline guards (rationalization table)

This is a discipline-enforcing skill (Match-the-Form-to-the-Failure: prohibition
+ rationalization table + red flags), because the entire point is a step
(local verification) that's easy to rationalize away once automated tests are
green.

| Excuse | Reality |
|---|---|
| "quality-check.sh passed, that's enough" | Green tests prove the test suite is satisfied, not that the fix behaves correctly against the real scenario. Step 8 requires observed output. |
| "the diagnosis is obviously right, skip the confirm gate" | Wrong diagnoses are exactly when confidence is highest. One message, cheap insurance. |
| "I'll clean up this other thing while I'm in here" | Out of scope. Minimal fix only (rules.md). |
| "code review can wait until after I've verified it works" | Reordered on purpose — catch cheap-to-fix issues before spending time on manual verification, not after. |
| "there's already a bot diagnosis, but let me re-derive it anyway to be safe" | Re-verify the cited evidence, don't redo the whole investigation — that's what Step 2's conditional is for. |

### Red flags — stop and go back

- About to commit without having actually run/observed the fix (only ran
  automated tests).
- About to skip the Step 3 confirm gate "because time pressure."
- About to open the PR before `/code-review` CONFIRMED findings are resolved.

## Testing plan (per `writing-skills`)

This is a discipline skill, so it needs pressure-scenario testing, not just
academic review:

1. **RED baseline** — run a subagent through a mocked issue-fix task *without*
   the skill, under combined pressure (time pressure + "tests already pass,
   just open the PR"). Document verbatim whether it skips local verification
   or the confirm gate.
2. **GREEN** — write the skill addressing exactly those rationalizations, then
   re-run the same scenario with the skill present. Confirm it holds the line.
3. **REFACTOR** — capture any new rationalization that surfaces, add an
   explicit counter, re-test until bulletproof.

## File location

`.claude/skills/implement-issue/SKILL.md` (project-scoped, alongside
`add-price-provider`, `add-inverter-platform`, `feature-lifecycle`, `release`).
