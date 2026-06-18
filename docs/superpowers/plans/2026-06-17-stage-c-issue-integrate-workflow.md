# Stage C — `issue-integrate.yml` Entry Point — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub workflow that, on owner `@claude-bot integrate`, drives a
new-integration issue through the `feature-lifecycle` skill — resumably, one stage
per invocation — reusing the existing `@claude-bot` pipeline conventions.

**Architecture:** One new workflow `.github/workflows/issue-integrate.yml`,
modeled on `issue-analyze.yml` / `issue-fix.yml` (owner-gated `issue_comment`
trigger, app-token identity, `claude-code-action@v1`, inline prompt). The prompt
uses the **read-the-file** pattern (read `.claude/skills/feature-lifecycle/SKILL.md`
and follow it) — NOT the Skill tool — matching the existing pipeline and avoiding
any dependency on CI skill auto-discovery. State lives in the **PR-body
checklist**; each `@claude-bot integrate` invocation reads it and advances to the
next human gate, then stops. Auto-advance (CI `workflow_run`) and triage routing
are deferred to Stage D.

**Tech Stack:** GitHub Actions YAML, `anthropics/claude-code-action@v1`,
`gh` CLI, the existing `feature-lifecycle` + implementation skills (now on `main`).

---

## Design decisions (baked in; flag during review if you disagree)

- **D-C1 — Skill usage = read-the-file.** The prompt instructs Claude to *read*
  `.claude/skills/feature-lifecycle/SKILL.md` and the matching implementation
  skill and follow them. No reliance on the Skill tool being surfaced in CI.
  Rationale: `issue-fix.yml` / `issue-analyze.yml` already use this pattern; the
  action's skill auto-discovery is undocumented/unverified.
- **D-C2 — Resume model = manual, owner-gated.** The owner re-issues
  `@claude-bot integrate` to advance each stage (exactly like Stages 2/3 are
  re-triggered). Each run reads the PR checklist and advances one stage to the
  next gate. No firing on arbitrary user comments. (Auto-advance = Stage D.)
- **D-C3 — Feature type inferred from the issue.** The prompt determines
  inverter vs price-provider from the issue text/labels and reads the matching
  implementation skill (`add-inverter-platform` or `add-price-provider`).
- **D-C4 — Identity & tokens reuse the existing secrets.**
  `create-github-app-token` (`CLAUDE_REVIEWER_APP_ID` / `CLAUDE_REVIEWER_PRIVATE_KEY`)
  for git/gh, `CLAUDE_CODE_OAUTH_TOKEN` for the model — identical to
  `issue-analyze.yml`.
- **D-C5 — No live end-to-end run in this stage.** A real lifecycle run ships a
  beta and comments on a user's issue (cost + outward-facing). Stage C delivers
  the workflow + validation (YAML lint, prompt review, a dry "report-only"
  smoke invocation on a throwaway test issue). The first real run is Solis #130,
  gated on @tatusbar.

---

## File Structure

- Create: `.github/workflows/issue-integrate.yml` — the entry/resume workflow.
- Modify: `docs/agents/skill-architecture.md` — add `issue-integrate.yml` to the
  GitHub-automation table so the docs match reality.
- Modify: `CLAUDE.md` — add the integrate stage to the Automated Agent Workflow
  table.

---

## Task 1: Scaffold the workflow (trigger, gating, identity)

**Files:**
- Create: `.github/workflows/issue-integrate.yml`

- [ ] **Step 1: Write the workflow header, trigger, and job gating**

Create the file with the trigger + owner gating, mirroring `issue-analyze.yml`.
The `if` also excludes PR comments (`issue.pull_request == null`) and requires
the literal `@claude-bot integrate`:

```yaml
# Integration Lifecycle (gated)
#
# Triggered manually with `@claude-bot integrate` on a new-integration issue
# (a new inverter platform or price provider). Drives the issue through the
# feature-lifecycle skill, ONE stage per invocation, resuming from the PR-body
# checklist. Re-issue `@claude-bot integrate` to advance to the next stage.

name: Integration Lifecycle

on:
  issue_comment:
    types: [created]

jobs:
  integrate:
    name: Integration Lifecycle
    if: |
      github.event.comment.user.login == github.repository_owner &&
      github.event.issue.pull_request == null &&
      contains(github.event.comment.body, '@claude-bot integrate')
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: write
      pull-requests: write
```

- [ ] **Step 2: Add the checkout + token + action steps (no prompt yet)**

Append the steps block, identical in shape to `issue-analyze.yml` but with
write-capable permissions (already set above) and a higher turn budget (the
lifecycle does real implementation work):

```yaml
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0

      - uses: actions/create-github-app-token@v2
        id: app-token
        with:
          app-id: ${{ secrets.CLAUDE_REVIEWER_APP_ID }}
          private-key: ${{ secrets.CLAUDE_REVIEWER_PRIVATE_KEY }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          github_token: ${{ steps.app-token.outputs.token }}
          trigger_phrase: "@claude-bot integrate"
          claude_args: "--max-turns 200 --permission-mode bypassPermissions"
          prompt: |
            PLACEHOLDER_PROMPT
```

- [ ] **Step 3: Validate YAML syntax**

Run:
```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/issue-integrate.yml')); print('YAML OK')"
```
Expected: `YAML OK`.

- [ ] **Step 4: Commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
git add .github/workflows/issue-integrate.yml
git commit -m "ci(integrate): scaffold issue-integrate workflow (trigger + identity)"
```

---

## Task 2: Write the lifecycle prompt (REQUIRED READING + PROCESS + CONSTRAINTS)

**Files:**
- Modify: `.github/workflows/issue-integrate.yml` (replace `PLACEHOLDER_PROMPT`)

- [ ] **Step 1: Replace `PLACEHOLDER_PROMPT` with the full prompt**

Use this exact prompt body (keep the YAML block-scalar indentation under
`prompt: |`):

```
            You are the **Integration Lifecycle** bot for issue #${{ github.event.issue.number }} in johanzander/bess-manager.

            ──────────────────────────────────────────────────────────────────
            REQUIRED READING (read these files before acting)
            ──────────────────────────────────────────────────────────────────
            1. docs/agents/rules.md                       — hard constraints
            2. docs/agents/workflow.md                    — commit/PR/release process
            3. docs/agents/skill-architecture.md          — how the skills compose
            4. .claude/skills/feature-lifecycle/SKILL.md  — the orchestrator you execute
            Then read the matching IMPLEMENTATION skill (see PROCESS step 2):
              - .claude/skills/add-inverter-platform/SKILL.md   (new inverter), or
              - .claude/skills/add-price-provider/SKILL.md      (new price provider)
            And the deploy skill when you reach a ship step:
              - .claude/skills/release/SKILL.md

            ──────────────────────────────────────────────────────────────────
            PROCESS
            ──────────────────────────────────────────────────────────────────
            1. Get full context:
                 gh issue view ${{ github.event.issue.number }} --json title,body,labels,comments
               Then find any existing lifecycle PR for this issue:
                 gh pr list --state all --search "in:body #${{ github.event.issue.number }}" --json number,title,body,isDraft,state

            2. Decide feature type from the issue (a new INVERTER platform vs a
               new PRICE PROVIDER) and read the matching implementation skill.

            3. Determine the CURRENT lifecycle stage:
               - If NO lifecycle PR exists yet → you are at Stage 1. Run the
                 implementation skill end-to-end, mark the feature experimental,
                 open a DRAFT PR with the feature-lifecycle checklist in the body,
                 ship to beta via the release skill, and comment on the issue
                 asking the user to install + report back.
               - If a lifecycle PR exists → read its checklist. Advance ONLY to
                 the next unchecked stage, following feature-lifecycle. If the
                 next stage is a HUMAN GATE (Stage 2 user log, Stage 5 user
                 confirmation) and the input isn't present yet, post a polite
                 status/ask and STOP — do not fabricate it.

            4. Update the PR-body checklist to reflect the stage you completed.

            ──────────────────────────────────────────────────────────────────
            HARD CONSTRAINTS
            ──────────────────────────────────────────────────────────────────
            - Follow feature-lifecycle exactly. Advance ONE stage per run.
            - PRs are DRAFT. Never push to main. Beta vs prod remotes are owned
              by the release skill (do not improvise remotes).
            - NEVER claim real-world validation before the user confirms (Stage 5).
              Keep the `experimental` marker until then.
            - NEVER fabricate a user debug log or confirmation. Gates are human.
            - Batch fixes — do NOT cut a beta release per fix (feature-lifecycle
              Stage 4).
            - Do NOT put `Closes #${{ github.event.issue.number }}` in a beta/
              intermediate PR — only the final prod PR closes the issue.
            - Run the local gate (pytest -m "not slow"; black/ruff; frontend build)
              before any push.
```

- [ ] **Step 2: Re-validate YAML (the prompt is the most error-prone part)**

Run:
```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/issue-integrate.yml')); p=d['jobs']['integrate']['steps'][-1]['with']['prompt']; print('YAML OK; prompt chars:', len(p)); assert 'feature-lifecycle/SKILL.md' in p and 'Advance ONE stage' in p"
```
Expected: `YAML OK; prompt chars: <n>` and no assertion error.

- [ ] **Step 3: Commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
git add .github/workflows/issue-integrate.yml
git commit -m "ci(integrate): add resumable feature-lifecycle prompt"
```

---

## Task 3: Document the new stage

**Files:**
- Modify: `docs/agents/skill-architecture.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the integrate row to the GitHub-automation table in skill-architecture.md**

Find the table row for `pr-review.yml` and add a row directly after it:

```markdown
| `issue-integrate.yml` | `@claude-bot integrate` | drive a new-integration issue through `feature-lifecycle`, one stage per invocation (resumes from the PR checklist) |
```

Also add one sentence under that table:

```markdown
`issue-integrate.yml` is the bridge between the GitHub pipeline and the skill
layer: it runs `feature-lifecycle` (via read-the-file), resuming from the PR-body
checklist, one human-gated stage at a time.
```

- [ ] **Step 2: Add the integrate stage to CLAUDE.md's Automated Agent Workflow table**

In `CLAUDE.md`, find the four-stage pipeline table (rows Triage/Analyze/Fix/Review)
and add a row after Review:

```markdown
| 5. Integrate | `@claude-bot integrate` (manual) | `issue-integrate.yml` | ~$2–10 | Drives a new inverter/provider request through the full experimental→stable lifecycle (`feature-lifecycle`), one stage per invocation. |
```

- [ ] **Step 3: Verify both edits landed**

Run:
```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
grep -q "issue-integrate.yml" docs/agents/skill-architecture.md && echo "OK arch"
grep -q "@claude-bot integrate" CLAUDE.md && echo "OK claude.md"
```
Expected: `OK arch` and `OK claude.md`.

- [ ] **Step 4: Commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
git add docs/agents/skill-architecture.md CLAUDE.md
git commit -m "docs: document the integrate lifecycle stage (issue-integrate.yml)"
```

---

## Task 4: Validation + safe smoke-test plan

**Files:** none (validation only)

- [ ] **Step 1: Lint the workflow with actionlint if available, else YAML-only**

Run:
```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
if command -v actionlint >/dev/null; then actionlint .github/workflows/issue-integrate.yml && echo "actionlint OK"; else echo "actionlint not installed — YAML check only"; python3 -c "import yaml; yaml.safe_load(open('.github/workflows/issue-integrate.yml')); print('YAML OK')"; fi
```
Expected: `actionlint OK` or `YAML OK`.

- [ ] **Step 2: Confirm the gating logic matches the other workflows**

Run:
```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
for f in issue-analyze issue-integrate; do echo "== $f =="; grep -A4 "if: |" .github/workflows/$f.yml; done
```
Expected: `issue-integrate` has the same owner + non-PR gating, with
`@claude-bot integrate` as the phrase.

- [ ] **Step 3: Write the smoke-test instructions into the PR description (not a live run)**

The PR for this branch MUST document how to safely first-exercise the workflow,
because a real run ships a beta. Put this in the PR body's Test Plan:
> - [ ] Merge, then open a **throwaway test issue** ("test: integrate smoke")
>   and comment `@claude-bot integrate`. Confirm the run reads the skills, posts
>   a status comment, and (since there's no real integration to build) STOPS
>   cleanly without shipping a beta. Delete the test issue after.
> - [ ] First real run is Solis #130, once @tatusbar picks the integration.

No command to run here — this step is satisfied by including the text in Task 5's
PR body.

---

## Task 5: Open the PR

**Files:** none

- [ ] **Step 1: Merge latest main, push, open a draft PR**

```bash
cd /Users/johanzander/GitHub/bess-manager-stage-c
git fetch origin --quiet && git merge origin/main --no-edit
pytest -m "not slow" -q 2>&1 | tail -5   # sanity: nothing broke (workflow-only change)
git push -u origin feat/issue-integrate-workflow
gh pr create --draft --base main --head feat/issue-integrate-workflow \
  --title "Stage C: @claude-bot integrate — feature-lifecycle entry point" \
  --body "See docs/superpowers/plans/2026-06-17-stage-c-issue-integrate-workflow.md. Adds issue-integrate.yml (owner-gated, resumable, read-the-file feature-lifecycle). No live run yet — smoke-test + first Solis run gated on #130.

## Test Plan
- [ ] Throwaway test issue + \`@claude-bot integrate\` → reads skills, posts status, stops without shipping a beta.
- [ ] First real run = Solis #130 after @tatusbar picks the integration."
```
Expected: PR URL printed.

- [ ] **Step 2: Report Stage C complete**

State that `issue-integrate.yml` exists, is documented, YAML-valid, gated like
the other stages, and ready for the throwaway smoke test before any real run.

---

## Self-Review (completed during planning)

- **Spec coverage:** Implements the grand-plan spec's **Stage C** ("issue-integrate.yml
  entry point; `@claude-bot integrate` runs feature-lifecycle resumably; wire
  human gates to comment triggers"). Stage D (triage routing + `workflow_run`
  auto-advance) is explicitly out of scope (D-C2/D-C5).
- **Placeholder scan:** `PLACEHOLDER_PROMPT` is a deliberate two-step scaffold
  (written in Task 1, replaced in Task 2), not a plan gap. No other placeholders.
- **Consistency:** Secret names (`CLAUDE_REVIEWER_APP_ID`,
  `CLAUDE_REVIEWER_PRIVATE_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`), trigger phrase
  (`@claude-bot integrate`), and file paths match `issue-analyze.yml` /
  `issue-fix.yml` and the now-on-main skill paths, all verified before writing.
