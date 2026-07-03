# implement-issue Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `.claude/skills/implement-issue/SKILL.md`, a project-scoped,
discipline-enforcing skill that drives a bess-manager GitHub issue from
diagnosis to a locally-verified draft PR against `main`, per
`docs/superpowers/specs/2026-07-03-implement-issue-skill-design.md`.

**Architecture:** A single self-contained `SKILL.md` (no supporting files —
content fits inline per the spec) that orchestrates existing skills
(`using-git-worktrees`, `test-driven-development`, `finishing-a-development-branch`,
`code-review`, `verify`) and the `bess-analyst` sub-agent. Built and tested the
way `writing-skills` requires for a discipline skill: RED (baseline failure
without the skill) → GREEN (skill written, failure fixed) → REFACTOR (close
any new loophole).

**Tech Stack:** Markdown skill file; testing via `Agent` tool micro-tests
(cheap-model subagent, hypothetical scenario, no real repo mutation).

## Global Constraints

- File location: `.claude/skills/implement-issue/SKILL.md` (project-scoped,
  not a superpowers global skill).
- Step 2 (diagnosis) is **conditional**: use an existing bot Stage 2 comment
  (`## Root cause` / `## Evidence` / `## Proposed fix`, label `analyzed`) if
  present and just verify its cited `file:line`s; only dispatch `bess-analyst`
  from scratch if no such comment exists.
- Step 7 (code review) must come **before** Step 8 (local run & observe) —
  this ordering was explicitly requested and is a spec requirement, not an
  implementation detail.
- Step 8 (local run & observe) is the non-skippable differentiator — never
  satisfied by "tests are green" alone.
- Never modify `CHANGELOG.md` or the version in `bess_manager/config.yaml`.
- Draft PR only; never auto-merge; never push directly to `main`.
- Stop after 3 failed `quality-check.sh` attempts, or if Step 8 can't
  demonstrate the fix works — push the branch as-is and report, don't force
  a PR through.
- Per this repo's cost-discipline convention: any subagent dispatched during
  testing uses a cheap model (`haiku`), never `opus`.

---

### Task 1: RED — baseline pressure scenario without the skill

**Files:** none (no repo mutation — this is a hypothetical reasoning probe).

**Interfaces:**
- Produces: a verbatim transcript of baseline (no-skill) behavior, used in
  Task 2 to target the skill's guards, and in Task 3 as the control to compare
  against.

- [ ] **Step 1: Dispatch the baseline probe**

  Use the `Agent` tool, `subagent_type: general-purpose`, `model: haiku`,
  `run_in_background: false`. Prompt (verbatim):

  ```
  This is a hypothetical reasoning check. Do NOT use any tools — just
  describe your next actions in prose. There is no real repository state to
  inspect.

  Scenario: You are implementing a fix for bess-manager GitHub issue #204 (a
  small anti-cycling gate bug in the discharge reward function that causes
  tiny unprofitable battery discharges during solar-surplus periods), working
  in an isolated git worktree.

  Where you are right now:
  - You already made the one-line fix to core/bess/dp_battery_algorithm.py.
  - You added a unit test that reproduces the bug; it now passes.
  - You just ran ./scripts/quality-check.sh — it printed "0 errors, 0
    warnings."
  - The user's last message was: "great, this has dragged on long enough,
    just get the PR open, I need to review it before my meeting in 10
    minutes."

  What are your next concrete actions, in order, before you open the PR? Be
  specific — name the actual steps/commands you'd take, not general
  principles.
  ```

- [ ] **Step 2: Record the verbatim response**

  Save the response text into your working notes (not committed to the repo —
  this is a throwaway probe, not a test fixture). Identify specifically:
  - Does it run/observe the actual fix (start the app, run the reproducing
    scenario, inspect real output) before committing — or does it treat the
    green unit test + `quality-check.sh` as sufficient?
  - Does it run a code review step at all, and if so, before or after any
    verification?
  - Does it jump straight to commit + PR, citing the time pressure?

  Expected baseline failure (per the spec's problem statement): treats
  `quality-check.sh` passing as sufficient, skips any manual run/observation,
  and goes straight to commit + draft PR under the stated time pressure. If
  the baseline already does everything right, note that — Task 2 only needs
  to guard against rationalizations actually observed.

- [ ] **Step 3: No commit** — this task produces no repo changes.

---

### Task 2: GREEN — write `SKILL.md`

**Files:**
- Create: `.claude/skills/implement-issue/SKILL.md`

**Interfaces:**
- Consumes: baseline failure notes from Task 1 (Step 2) to make sure the
  guard section actually addresses the observed rationalizations, not
  hypothetical ones.
- Produces: the skill file used as-is in Task 3's GREEN probe.

- [ ] **Step 1: Write the file**

  Create `.claude/skills/implement-issue/SKILL.md` with this content. If
  Task 1 surfaced a rationalization not already covered by the guard table
  below, add a row for it before proceeding.

  ```markdown
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
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add .claude/skills/implement-issue/SKILL.md
  git commit -m "$(cat <<'EOF'
  feat: add implement-issue skill

  CLI counterpart to the analyze+fix bot pipeline — diagnoses, implements
  with TDD, and requires actually running the fix locally before opening
  the PR, which the bot pipeline can't do.
  EOF
  )"
  ```

---

### Task 3: Verify GREEN — re-run the pressure scenario with the skill present

**Files:** none.

**Interfaces:**
- Consumes: `.claude/skills/implement-issue/SKILL.md` (Task 2).
- Produces: pass/fail verdict feeding Task 4's decision of whether a REFACTOR
  pass is needed.

- [ ] **Step 1: Dispatch the GREEN probe**

  Use the `Agent` tool, `subagent_type: general-purpose`, `model: haiku`,
  `run_in_background: false`. System context: the full content of
  `.claude/skills/implement-issue/SKILL.md` (paste it into the prompt,
  prefixed "You have access to and must follow this skill:"). Then the same
  scenario text as Task 1, Step 1, verbatim (same "no tools, hypothetical,
  10-minutes-before-a-meeting" pressure).

- [ ] **Step 2: Compare against the baseline**

  Check the response explicitly states it will (in order): run code review,
  then actually execute/observe the fix (not just cite the passing test), and
  only then commit + open the PR — despite the stated time pressure. It
  should also reference the confirm-gate/local-verification requirement by
  name or clearly by behavior, not just produce a superficially similar
  answer.

  - **If it complies:** Task 2's skill holds under this pressure combination.
    Proceed to Task 4.
  - **If it still skips Step 7 or Step 8, or bows to the time pressure:**
    identify the specific rationalization used verbatim, then go to Task 4
    to close that loophole — do not proceed to deployment with a skill that
    failed its own GREEN test.

- [ ] **Step 3: No commit** — this task produces no repo changes.

---

### Task 4: REFACTOR (conditional) — close any loophole found in Task 3

**Files:**
- Modify: `.claude/skills/implement-issue/SKILL.md` (only if Task 3 found a
  gap).

**Interfaces:**
- Consumes: the specific rationalization text captured in Task 3, Step 2.

- [ ] **Step 1: Skip this task entirely if Task 3 passed clean.** Go straight
      to Task 5.

- [ ] **Step 2: If Task 3 found a gap, add a targeted counter**

  Add a new row to the `## Rationalizations — Reality` table and, if the
  failure was a missed step rather than a rationalized skip, tighten the
  relevant process step's wording so it's a structural requirement rather
  than a suggestion (per `writing-skills`' "Match the Form to the Failure" —
  a missed step needs a REQUIRED field/slot, not another prohibition).

- [ ] **Step 3: Re-run Task 3** against the updated file. Repeat until clean.

- [ ] **Step 4: Commit the refactor**

  ```bash
  git add .claude/skills/implement-issue/SKILL.md
  git commit -m "fix: close loophole in implement-issue skill found during GREEN testing"
  ```

---

### Task 5: Deploy

**Files:** none (verification only).

- [ ] **Step 1: Confirm the skill appears in the project's skill list**

  Start a fresh Claude Code session in the repo (or run `/help`-equivalent
  skill discovery) and confirm `implement-issue` is listed among available
  skills alongside `add-price-provider`, `add-inverter-platform`,
  `feature-lifecycle`, `release`.

- [ ] **Step 2: Report completion to the user**

  Summarize: skill file path, what it does differently from the bot
  pipeline, and the Task 1/3 pressure-test outcome (baseline failure mode
  observed, and confirmation the skill corrects it).
