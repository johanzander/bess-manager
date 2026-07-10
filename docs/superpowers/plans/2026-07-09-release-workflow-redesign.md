# Release Workflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `beta/main` (bess-manager-beta) a pure downstream mirror of `origin/main` (bess-manager) — reconcile the current 13/13 commit divergence once, then change the release tooling so that divergence can't recur.

**Architecture:** Two-phase. Phase 1 (Tasks 1–3) is a one-time migration: forward-port the two substantive beta-only commits into `origin/main`, then fast-forward `beta/main` to match. Phase 2 (Tasks 4–8) rewrites the release/feature-lifecycle skills and docs so the new one-directional flow (main → beta, hotfixes via short-lived release branches) is what gets followed from now on.

**Tech Stack:** git, `gh` CLI, pytest, existing `.claude/skills/release/SKILL.md` and `.claude/skills/feature-lifecycle/` skill files, `docs/agents/workflow.md`, `CLAUDE.md`.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-09-release-workflow-design.md`.
- Never push directly to `main` on either repo — always through a PR with CI green. (CLAUDE.md, `docs/agents/workflow.md`)
- Never skip `CHANGELOG.md` on a release. (CLAUDE.md)
- Full local test suite (`.venv/bin/pytest -m "not slow"` at minimum; `-m slow` for anything touching `core/bess/`) must pass before any commit that touches algorithm code. (CLAUDE.md)
- Run `./scripts/quality-check.sh` (black + ruff) before every commit.
- Every push, merge, tag, and GitHub Release in this plan is a real action against `origin/johanzander/bess-manager` or `beta/johanzander/bess-manager-beta` — get explicit user go-ahead immediately before each one. Do not batch multiple pushes/merges under one approval.
- Do this work in the existing worktree at `/Users/johanzander/GitHub/bess-manager-release-workflow-design` (branch `docs/release-workflow-design`, based on `origin/main`) for Tasks 4–8. Tasks 1–3 need their own fresh branches off current `origin/main` — create them as separate worktrees, don't reuse the docs worktree, since Task 1's PR must merge to `origin/main` before Task 3 can safely fast-forward `beta/main`.

---

### Task 1: Forward-port the two beta-only commits and beta-only assets to `origin/main`

The beta-only commit set (`git log origin/main..beta/main`) is 13 commits, but 11 of them are beta-identity/version/changelog/release noise that won't exist once beta stops taking its own commits (e.g. `release: v9.9.0b9`, `chore: restore beta identity...`, `docs: changelog for v9.10.0b1`). Verified during design that the `spot_multiplier` beta commits (`994bc74`, `42a0549`) are already superseded on main by `a6d8765` (`feat: port multiplicative spot-price adjustment (spot_multiplier) to main (#227)`) — nothing to do there.

Only two commits carry real, unshipped behavior:
- `526656d` — "Remove ad hoc DP guardrails in favor of pure backward induction (#59)"
- `64ba18c` — "fix: action-derived GRID_CHARGING charge_rate display + reduce log verbosity (#62)"

Both were verified via `git cherry-pick --no-commit` dry-run during design: `526656d` applies cleanly onto `origin/main`; `64ba18c` applies cleanly except for a single conflict in `CHANGELOG.md` (both commits add entries near the top of the file — a manual merge of the two entries, not a code conflict).

Separately, commit `a36c9cd` ("chore: restore beta identity + carry-forward files after main sync") shows beta also carries assets that don't exist on main at all: `docs/superpowers/plans/.../ci-wizard-entsoe-frank-126.json` (an E2E scenario, ~4200 lines), `scripts/gh-agent.sh`, a step in `.github/workflows/ci.yml`, and additions to `e2e/tests/wizard-expectations.ts` and `e2e/run-e2e.sh`. Per user decision during planning, these move to main permanently as part of this task rather than staying beta-exclusive — after this, beta has no unique content left at all except the identity fields handled in Task 3.

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py`, `core/bess/models.py`, `core/bess/decision_intelligence.py`, `core/bess/growatt_min_controller.py`, `core/bess/inverter_controller.py`, `core/bess/solax_modbus_growatt_controller.py` (via cherry-pick, content owned by the two beta commits)
- Modify: `core/bess/tests/unit/test_period_groups.py`, `core/bess/tests/unit/test_solar_export_discharge_gate.py`, `core/bess/tests/unit/test_surplus_disposition.py`, various `core/bess/tests/unit/data/*.json` fixtures, `core/bess/tests/integration/test_plan_faithfulness.py` (via cherry-pick)
- Remove: `core/bess/tests/unit/test_action_threshold.py` (via cherry-pick — superseded by the guardrail removal)
- Create: `core/bess/tests/unit/test_dp_no_guardrails.py` (via cherry-pick)
- Create: `docs/superpowers/plans/2026-07-06-dp-remove-guardrails.md`, `docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md` (via cherry-pick — these are the design docs for `526656d`, carry them over so main has the same record beta does)
- Create: `scripts/gh-agent.sh`, the E2E scenario JSON under its actual path (locate via `git show a36c9cd --stat` in Step 3 below — don't assume the path), additions to `e2e/tests/wizard-expectations.ts` and `e2e/run-e2e.sh` (ported from `a36c9cd`)
- Modify: `.github/workflows/ci.yml` (the one added step from `a36c9cd`, not the whole beta workflow)
- Modify: `CHANGELOG.md` (manual conflict resolution)

**Interfaces:** N/A — this task ports existing, already-tested behavior; no new interfaces are introduced for later tasks to consume.

- [ ] **Step 1: Create a fresh branch off current `origin/main`**

```bash
git fetch origin main beta -q
git worktree add ../bess-manager-port-beta-fixes origin/main -b chore/port-beta-only-fixes
cd ../bess-manager-port-beta-fixes
```

- [ ] **Step 2: Cherry-pick both commits**

```bash
git cherry-pick 526656d
```

Expected: applies cleanly, commits automatically (no conflict was found in the design-time dry run).

```bash
git cherry-pick 64ba18c
```

Expected: stops with a conflict in `CHANGELOG.md` only. Confirm nothing else conflicted:

```bash
git status --short | grep '^UU'
```

Expected output: exactly one line, `UU CHANGELOG.md`.

- [ ] **Step 3: Resolve the CHANGELOG conflict**

Open `CHANGELOG.md`. Both commits added an entry under `## [Unreleased]`. Keep both entries (one for the DP guardrail removal / #240 export-miscrediting fix, one for the GRID_CHARGING display fix / log-verbosity reduction), remove the conflict markers, then:

```bash
git add CHANGELOG.md
git cherry-pick --continue
```

- [ ] **Step 4: Port the beta-only carry-forward assets from `a36c9cd`**

First find their exact paths (don't assume — the earlier `git show --stat` output was truncated):

```bash
git show --stat a36c9cd
```

Then take each non-identity file (everything except `bess_manager/config.yaml` and `repository.yaml`, which stay beta-exclusive — see Task 3) from that commit as-is:

```bash
git checkout a36c9cd -- scripts/gh-agent.sh e2e/tests/wizard-expectations.ts e2e/run-e2e.sh
git show a36c9cd -- .github/workflows/ci.yml   # inspect the single added step
```

Apply just that one CI step by hand (don't take the whole file — `ci.yml` on main has diverged from beta's copy since `a36c9cd`, so a blind `git checkout` would clobber unrelated main-side CI changes). For the E2E scenario JSON, use the exact path `git show --stat a36c9cd` reported in this step:

```bash
git checkout a36c9cd -- <exact-scenario-path-from-git-show---stat>
git add scripts/gh-agent.sh e2e/tests/wizard-expectations.ts e2e/run-e2e.sh .github/workflows/ci.yml <exact-scenario-path>
git commit -m "chore: port beta-only E2E scenario, gh-agent.sh, and CI step from beta to main"
```

- [ ] **Step 5: Run the fast test suite**

```bash
.venv/bin/pytest -m "not slow"
```

Expected: all pass. This includes the new `test_dp_no_guardrails.py` and the updated `test_surplus_disposition.py`.

- [ ] **Step 6: Run the slow/algorithm suite**

Since this ports a DP algorithm behavior change, the slow suite must also be green — it's the thing CI's Algorithm job would gate on.

```bash
.venv/bin/pytest -m slow
```

Expected: all pass (~30 min). If anything fails, stop — do not proceed to Step 7 with a failing algorithm suite. This is a real behavior change (removal of guardrails), not a mechanical port, so a failure here is meaningful and needs investigation, not a forced merge.

- [ ] **Step 7: Format and lint**

```bash
.venv/bin/black . && .venv/bin/ruff check --fix .
git diff --stat
```

If black/ruff changed anything, commit that as a fixup:

```bash
git add -u
git commit -m "chore: black/ruff formatting after cherry-pick"
```

- [ ] **Step 8: Push and open the PR — STOP for explicit user go-ahead before pushing**

```bash
git push origin chore/port-beta-only-fixes
gh pr create --repo johanzander/bess-manager \
  --base main --head chore/port-beta-only-fixes \
  --title "chore: forward-port beta-only fixes and carry-forward assets from beta" \
  --body "Reconciles the two substantive beta-only commits (526656d, 64ba18c) plus beta-only E2E/tooling assets into main as the last step before beta becomes a pure downstream mirror. See docs/superpowers/specs/2026-07-09-release-workflow-design.md."
```

- [ ] **Step 9: Wait for CI, get explicit merge approval, merge**

```bash
gh pr checks chore/port-beta-only-fixes --repo johanzander/bess-manager --watch
```

Once green, ask the user to confirm the merge, then:

```bash
gh pr merge chore/port-beta-only-fixes --repo johanzander/bess-manager --squash
```

- [ ] **Step 10: Clean up the worktree**

```bash
cd /Users/johanzander/GitHub/bess-manager
git worktree remove ../bess-manager-port-beta-fixes
```

---

### Task 2: Fast-forward `beta/main` to match `origin/main`

Once Task 1 merges, `beta/main`'s two unique commits now exist on `origin/main` too (via the cherry-picked, squash-merged equivalents — the SHAs differ but the content doesn't). Every other beta-only commit was noise (releases, version bumps, identity restores). This step makes `beta/main` a clean mirror.

**Files:** None modified — this is a repo-state operation (branch reset + tag/branch cleanup), not a code change.

**Interfaces:** N/A.

- [ ] **Step 1: Verify Task 1 landed and re-diff**

```bash
cd /Users/johanzander/GitHub/bess-manager
git fetch origin main beta -q
git log --oneline origin/main..beta/main
```

Expected: only the 11 known-noise commits remain (releases, version bumps, changelog-only, identity restores) — confirm by eye that no new unexpected commit appears. If anything unexpected shows up, stop and investigate before proceeding — that would mean something landed on beta again after this plan was written.

- [ ] **Step 2: Build the synced-plus-identity commit locally, don't push main's identity directly**

Pushing raw `origin/main` to beta first and re-applying identity in a second push would leave a window where the beta repo's `config.yaml`/`repository.yaml` claim to be the prod add-on. Build the real target commit locally first:

```bash
git worktree add ../bess-manager-beta-sync origin/main -b beta-sync-tmp
cd ../bess-manager-beta-sync
```

```yaml
# bess_manager/config.yaml — change these 3 fields only, leave version as-is (a version bump belongs to the next `release beta` run, not this migration):
# name: "BESS Manager (Beta)"
# slug: "bess_manager_beta"
# image: "ghcr.io/johanzander/bess-manager-beta-{arch}"
```

```yaml
# repository.yaml — change these 2 fields:
# name: BESS Battery Manager (Beta) Repository
# url: https://github.com/johanzander/bess-manager-beta
```

Apply both edits, then:

```bash
git add bess_manager/config.yaml repository.yaml
git commit -m "chore: re-apply beta identity (name/slug/image) after sync to main"
```

- [ ] **Step 3: Force-sync beta's default branch — STOP for explicit user go-ahead before pushing**

This is a force-push to `beta/main`. Confirm with the user first, and confirm the target is `beta`, not `origin`.

```bash
git push beta HEAD:main --force
```

- [ ] **Step 4: Verify**

```bash
cd /Users/johanzander/GitHub/bess-manager
git fetch beta main -q
git log --oneline origin/main..beta/main
```

Expected: exactly one commit — the identity commit from Step 2.

```bash
git show beta/main:bess_manager/config.yaml | grep -E '^(name|slug|image):'
```

Expected: `name: "BESS Manager (Beta)"`, `slug: "bess_manager_beta"`, `image: "ghcr.io/johanzander/bess-manager-beta-{arch}"`.

- [ ] **Step 5: Delete the stale `release/v9.9.0b8` branch on `origin`**

This branch predates the current beta `v9.9.0b9` release and is dead. Confirm with the user, then:

```bash
git push origin --delete release/v9.9.0b8
```

- [ ] **Step 6: Clean up the temporary worktree**

```bash
git worktree remove ../bess-manager-beta-sync
git branch -D beta-sync-tmp
```

---

### Task 3: Rewrite the beta release path in `.claude/skills/release/SKILL.md`

Replace the current "diff beta against main to figure out what's new" mechanics with a strict fast-forward-only sync, per design §1 and §6.

**Files:**
- Modify: `.claude/skills/release/SKILL.md`

**Interfaces:** N/A — this is a process doc, not code. Task 4 and Task 5 both edit the same file; do this task first since it establishes the file's new section structure.

- [ ] **Step 1: Read the current beta section**

```bash
cd /Users/johanzander/GitHub/bess-manager-release-workflow-design
sed -n '1,50p' .claude/skills/release/SKILL.md
```

- [ ] **Step 2: Replace steps 0–2 (sync mechanics) with the fast-forward-only version**

Replace this text (the current step 0 "Sync local main" + step 1 "Determine next version" + step 2 "Sync with target branch"):

```
0. **Sync local `main` with `origin/main` first** — ...
1. **Determine next version**: ...
2. **Sync with target branch** — `git fetch beta main && git merge beta/main`. Resolve any conflicts locally. Never push a branch that is behind the target.
```

With:

```
1. **Sync local `main` with `origin/main`** — `git fetch origin main && git merge --ff-only origin/main` (run this from a plain `main` checkout, not a feature branch). If this fails to fast-forward, something is wrong locally — do not force it, investigate first.
2. **Check beta has no unique commits** — `git fetch beta main && git log --oneline origin/main..beta/main`. Expected: empty (beta is a pure mirror as of the migration). If this is non-empty, stop — a commit landed on beta directly, breaking the one-directional flow this skill exists to enforce. Do not silently overwrite it; surface it to the user.
3. **Build the release commit locally, on top of `origin/main`, before touching the beta remote** — `git checkout -b beta-release-tmp origin/main`. Bump `bess_manager/config.yaml`'s `version` field to the next beta number (check `git show beta/main:bess_manager/config.yaml | grep '^version:'` and `gh release list -L 5 -R johanzander/bess-manager-beta` first — e.g. `9.9.0b9` → `9.9.0b10`, or start `X.Y.0b1` if promoting past what main last shipped as stable). In the same commit, re-apply the beta identity fields, which never exist on main by design:
   - `bess_manager/config.yaml`: `name: "BESS Manager (Beta)"`, `slug: "bess_manager_beta"`, `image: "ghcr.io/johanzander/bess-manager-beta-{arch}"`
   - `repository.yaml`: `name: BESS Battery Manager (Beta) Repository`, `url: https://github.com/johanzander/bess-manager-beta`

   Commit as `git commit -am "release: v<beta-version>"`. Pushing this single commit (not raw `origin/main`) is what keeps the beta repo from ever momentarily claiming to be the prod add-on.
```

- [ ] **Step 3: Replace the changelog step**

Find the current step that says "Update CHANGELOG.md — add entry at the top following Keep a Changelog format... When an item links to a PR, keep it to one line". Replace with:

```
4. **Copy the changelog, don't author it** — on the same `beta-release-tmp` branch from step 3, take the current `## [Unreleased]` section verbatim from `origin/main`'s `CHANGELOG.md` (synced in step 1) and rename it to `## [<beta-version>] - <date>` in `CHANGELOG.md`. Amend it into the same commit (`git commit --amend`) rather than adding a second commit. Do not hand-write beta-specific entries — if content is missing from `Unreleased`, it means a PR merged to main without a changelog entry, which is a bug in that PR's merge process, not something to patch around here.
```

- [ ] **Step 4: Renumber the remaining steps** (test run, black/ruff, commit, push, PR, CI, merge, tag, GitHub Release, verify) to follow steps 1–4 above, keeping their content unchanged except: every reference to "the branch" now means `beta-release-tmp` (the branch created in step 3), and the "push branch to beta remote" step pushes `beta-release-tmp`, not `origin/main` directly. Read the full file after editing to confirm the numbering is sequential and no step references the old step numbers by name.

```bash
grep -n '^[0-9]\+\.' .claude/skills/release/SKILL.md | head -20
```

Expected: an unbroken sequence starting at 1.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "docs: rewrite release-beta skill around fast-forward-only sync"
```

---

### Task 4: Rewrite the production release path in `.claude/skills/release/SKILL.md`

Per design §6: `release prod` no longer diffs against beta at all — it operates purely on `origin/main`, renaming `Unreleased` to the stable version.

**Files:**
- Modify: `.claude/skills/release/SKILL.md`

**Interfaces:** Depends on Task 3 having already restructured the beta section; this task only touches the "Production Release" section, which is independent text.

- [ ] **Step 1: Read the current production section**

```bash
sed -n '/## Production Release/,$p' .claude/skills/release/SKILL.md
```

- [ ] **Step 2: Replace it**

Replace the whole `## Production Release (`release` or `release prod`)` section with:

```markdown
## Production Release (`release` or `release prod`)

1. **Check the current stable version**: `gh release list -L 5` (origin repo) and `git show origin/main:bess_manager/config.yaml | grep '^version:'` — they should match; if not, stop and investigate before releasing.
2. **Confirm the commit being promoted has already shipped as a beta** — `git log --oneline` on `origin/main` should show the exact commit was previously synced to `beta/main` and released there (check `gh release list -L 10 -R johanzander/bess-manager-beta` for a matching `bN` version pointing at content you recognize). Promoting a commit that was never validated on beta defeats the point of having a beta channel — if this is a small, fully self-validated change (see project memory on beta-vs-prod channel choice), that's fine, just confirm it deliberately rather than by default.
3. **Run the full test suite locally**, including `pytest -m slow`.
4. **Bump `config.yaml`** — drop the `bN` suffix (e.g. `9.9.0b12` → `9.9.0`).
5. **Rename the changelog heading** — `## [Unreleased]` becomes `## [<version>] - <date>` in `CHANGELOG.md` on `origin/main`. This is the only changelog edit a production release makes; do not also hand-add entries, they should already be there from each PR's merge.
6. **Run `black --check .` and `ruff check .`** — fix any formatting issues.
7. **Create a PR** against `origin/main` (a version-bump-only PR, branched from `origin/main`), wait for CI.
8. **Get explicit user approval, then merge, tag, and push the tag** to `origin`.
9. **Create a GitHub Release**: `gh release create v<version> --title "v<version>" --notes "<changelog>"`.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "docs: rewrite release-prod skill to promote from main without diffing beta"
```

---

### Task 5: Add the hotfix procedure to `.claude/skills/release/SKILL.md`

Per design §4 — a new `release hotfix` entry point, documenting the release-branch/cherry-pick path.

**Files:**
- Modify: `.claude/skills/release/SKILL.md`

**Interfaces:** Independent new section; no dependency on Tasks 3–4's edits beyond both existing in the same file.

- [ ] **Step 1: Append a new section after "Production Release"**

```markdown
## Hotfix Release (`release hotfix`)

Use when a bug is found in the **currently-published stable version** and `origin/main` has since moved on with unrelated, unreleased work you don't want to ship alongside the fix. If `origin/main` is still close to the last stable tag (no risky or unvalidated work merged since), skip this — just fix on `main` and run a normal Production Release instead.

1. **Fix on `main` first**, via a normal PR. `main` remains the only place any fix is ever authored — this procedure only moves it backward to where users already are, never authors it directly on a release branch.
2. **Branch from the stable tag**: `git fetch origin --tags && git checkout -b release-X.Y vX.Y.Z` (the currently-published stable tag, not `main`).
3. **Cherry-pick the fix commit(s)** from `main` onto `release-X.Y`: `git cherry-pick <sha>`.
4. **Bump the patch version** in `config.yaml` (`X.Y.Z` → `X.Y.(Z+1)`) and add a changelog entry directly on `release-X.Y` (this content also needs to make it back into `origin/main`'s next `Unreleased` section by hand, since `release-X.Y` isn't merged back into `main` — the fix code already is, only the changelog line and version bump are release-branch-only).
5. **Run the fast test suite** on `release-X.Y`: `pytest -m "not slow"`.
6. **Push, tag, and release** from `origin`: `git push origin release-X.Y`, then tag `vX.Y.(Z+1)` on `release-X.Y` and `gh release create` as in a normal production release — get explicit user approval before each push/tag/release.
7. **Delete `release-X.Y`** once the patch is published: `git push origin --delete release-X.Y`. It is not long-lived.
8. **Sync beta**: run the normal `release beta` flow afterward so beta picks up both the original fix (already on `main`) and stays ahead — no special handling needed since `main` already has the fix from step 1.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "docs: add hotfix release procedure to release skill"
```

---

### Task 6: Change `feature-lifecycle` skill's target from beta-first to main-first-behind-a-flag

Per design §5.

**Files:**
- Modify: `.claude/skills/feature-lifecycle/SKILL.md` (exact path — confirm with `find .claude/skills/feature-lifecycle -type f` since the file may be split; edit whichever file(s) name beta as the initial merge target)

**Interfaces:** N/A.

- [ ] **Step 1: Locate the beta-first language**

```bash
grep -rn -i "beta" .claude/skills/feature-lifecycle/
```

- [ ] **Step 2: Read the matched file(s) in full** to see the current experimental-feature workflow structure before editing (don't guess at surrounding context from grep alone).

- [ ] **Step 3: Replace "merge to beta first" instructions with "merge to `origin/main` behind a stability flag"**

The exact replacement text depends on what Step 2 reveals, but must specify:
- The PR target is `origin/main`, not the beta repo, for every stage including the initial experimental merge.
- The feature is marked experimental via whatever the codebase's existing stability-flag mechanism is (check `docs/agents/bess-knowledge.md` / existing "Platform maturity levels" — GEN3/SolaX are already marked experimental somewhere; find and reuse that exact mechanism rather than inventing a new one).
- Graduation (flag removed) happens after a real user validates the feature on a beta build that included it — this is a follow-up PR to `origin/main` that only changes the flag, not a branch change.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/feature-lifecycle/
git commit -m "docs: point feature-lifecycle at main-behind-a-flag instead of beta-first"
```

---

### Task 7: Update `docs/agents/workflow.md` and `CLAUDE.md`

**Files:**
- Modify: `docs/agents/workflow.md`
- Modify: `CLAUDE.md`

**Interfaces:** N/A.

- [ ] **Step 1: Update `CLAUDE.md`'s "Release Workflow" section**

Current text (from the section under `## Release Workflow`) still says "confirm beta vs main, origin vs beta remote" generically. Add the two new invariants from the design:

```markdown
- `beta/main` only ever advances by fast-forward from `origin/main` — never commit directly to the beta repo. If a fix is needed on the currently-published stable version while main has moved on, use the hotfix procedure (short-lived `release-X.Y` branch cherry-picking from main), never a direct beta commit.
- `CHANGELOG.md` is authored once, on `origin/main`, under `## [Unreleased]`. Beta and stable releases both consume that section (copy for beta, rename for stable) — never hand-write a beta-specific or duplicate changelog entry.
```

- [ ] **Step 2: Update `docs/agents/workflow.md`'s "PR Merge Workflow" section**

The current step 3 ("Update CHANGELOG — add entry at the top") should explicitly say entries go under `## [Unreleased]`, not at the very top of the file above the heading:

```markdown
3. **Update CHANGELOG** — add entry under the `## [Unreleased]` heading (create it if a previous production release consumed it and it's currently missing), credit author:
   `(thanks [@username](https://github.com/username))`
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/agents/workflow.md
git commit -m "docs: document beta-is-downstream-of-main invariant and Unreleased changelog convention"
```

---

### Task 8: Push the docs branch and open the tooling PR

**Files:** None new — this closes out Tasks 3–7's commits.

**Interfaces:** N/A.

- [ ] **Step 1: Confirm the branch has all five commits from Tasks 3–7**

```bash
cd /Users/johanzander/GitHub/bess-manager-release-workflow-design
git log --oneline origin/main..HEAD
```

Expected: 6 commits (the spec commit from brainstorming, plus Tasks 3–7's five commits).

- [ ] **Step 2: Run quality check**

```bash
./scripts/quality-check.sh
```

- [ ] **Step 3: Push and open PR — STOP for explicit user go-ahead before pushing**

```bash
git push origin docs/release-workflow-design
gh pr create --repo johanzander/bess-manager \
  --base main --head docs/release-workflow-design \
  --title "docs: adopt main-is-source-of-truth release workflow" \
  --body "Implements docs/superpowers/specs/2026-07-09-release-workflow-design.md. Requires the beta-only-commit reconciliation (chore/port-beta-only-fixes PR + beta/main fast-forward) to have landed first, since Task 3's skill rewrite assumes beta is already a clean mirror."
```

- [ ] **Step 4: Wait for CI, get explicit merge approval, merge**

```bash
gh pr checks docs/release-workflow-design --repo johanzander/bess-manager --watch
```

Once green and approved:

```bash
gh pr merge docs/release-workflow-design --repo johanzander/bess-manager --squash
```

- [ ] **Step 5: Clean up the worktree**

```bash
cd /Users/johanzander/GitHub/bess-manager
git worktree remove ../bess-manager-release-workflow-design
```
