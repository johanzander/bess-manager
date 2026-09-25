# Release Skill

## Beta Release (`release beta`)

1. **Sync local `main` with `origin/main`** — `git fetch origin main && git merge --ff-only origin/main` (run this from a plain `main` checkout, not a feature branch). If this fails to fast-forward, something is wrong locally — do not force it, investigate first. **Sandbox note**: `git fetch`/`git push`/`gh` calls against GitHub need network egress beyond the default allowlist — pass `allowed_domains: ["github.com"]` (add `"api.github.com"` too for `gh api`/`gh pr`/`gh release` calls) rather than reaching for `dangerouslyDisableSandbox`; a bare `403`/`CONNECT tunnel failed` on a `git`/`gh` command is this, not an auth problem.
2. **Check beta's only unique commits are its own past release stamps** — `git fetch beta main && git log --oneline origin/main..beta/main`. Each prior beta release adds exactly one commit here (titled `release: v<version>`, or `chore: reset beta/main to mirror origin/main...` for the one-time migration reset) — that's expected, not a problem. What's NOT expected is anything else: a feature commit, a fix, an unexplained message. If you see a commit that isn't one of this skill's own release-stamp commits, stop — something landed on beta directly, breaking the one-directional flow this skill exists to enforce. Do not silently overwrite it; surface it to the user. (Note: `bess-manager-beta`'s branch protection forbids force-push, so this history accumulates one merge commit per release rather than staying literally empty — that's fine, the check is about content, not commit count.) This range legitimately spans the *entire* beta history (every past release's merge, back to the first), not just recent ones — that's fine, since a regular merge (step 12) keeps every past release-stamp commit as beta/main's own ancestry; only check the *newest* end of the list (the commits right above the last release's merge) for anything unexpected.
3. **Build the release commit locally, on top of `origin/main`, before touching the beta remote** — `git checkout -b beta-release-tmp origin/main`. Bump `bess_manager/config.yaml`'s `version` field to the next beta number (check `git show beta/main:bess_manager/config.yaml | grep '^version:'` and `gh release list -L 5 -R johanzander/bess-manager-beta` first — e.g. `9.9.0b9` → `9.9.0b10`, or start `X.Y.0b1` if promoting past what main last shipped as stable **and check `gh release list -L 5 -R johanzander/bess-manager` too — if `origin/main` has itself cut a new stable release since the last beta, the beta version resets off *that* new stable number, not off beta's own last `bN`**). Use a version-specific branch name (`beta-release-v<version>-tmp`) rather than the bare `beta-release-tmp` — old local/remote branches from prior releases accumulate under that literal name and collide. In the same commit, re-apply the beta identity fields, which never exist on main by design:
   - `bess_manager/config.yaml`: `name: "BESS Manager (Beta)"`, `slug: "bess_manager_beta"`, `image: "ghcr.io/johanzander/bess-manager-beta-{arch}"`
   - `repository.yaml`: `name: BESS Battery Manager (Beta) Repository`, `url: https://github.com/johanzander/bess-manager-beta`

   Commit as `git commit -am "release: v<beta-version>"`. Pushing this single commit (not raw `origin/main`) is what keeps the beta repo from ever momentarily claiming to be the prod add-on.
4. **Copy the changelog, don't author it** — on the same `beta-release-tmp` branch from step 3, take the current `## [Unreleased]` section verbatim from `origin/main`'s `CHANGELOG.md` (synced in step 1) and rename it to `## [<beta-version>] - <date>` in `CHANGELOG.md`. Amend it into the same commit (`git commit --amend`) rather than adding a second commit.

   **Let `scripts/check-changelog.py check` do the gap detection and the curation — don't hand-grep.** On this `beta-release-tmp` branch, run it against the section you just renamed:

   ```
   scripts/check-changelog.py check --changelog CHANGELOG.md \
     --since-ref "$(git merge-base origin/main beta/main)" --section <beta-version>
   ```

   `--since-ref` is the previous beta's sync point — the merge-base of `origin/main` and `beta/main` — which is precise, unlike the previous release's *publish* timestamp (a PR can merge after the cut but before the release is published). `--section <beta-version>` targets the renamed `## [<beta-version>]` section explicitly rather than assuming it is the topmost `## [` heading (finding: after a stable release, the topmost section is the stable version).

   `check` asserts two invariants against that section (with `--beta-ref`/`--beta-file` omitted it skips the prepend-only check, which only makes sense after the step-5 merge):
   - **coverage** — every `(#N)` merge commit on `origin/main` since the previous beta's sync point must appear as a `[#N](...)` link in this section — by its PR number or by an issue it references. A missing link is a real gap: it merged with no changelog entry, not just already-shipped content to curate away. Do not silently drop it.
   - **no re-announcing** — every `[#N](...)` link in this section must correspond to a PR that merged *after* that same sync point (by its number or a referenced issue). Anything merged before already shipped in an earlier `bN` and must be dropped, not re-listed (see the `v9.9.0b10`/`v9.9.0b11` entries for the pattern). Getting this wrong silently double-announces old work as new in every subsequent release — it compounds.

   Iterate until `check` exits 0. When it flags a coverage gap, read the PR's diff/description (`gh pr view <N> --repo johanzander/bess-manager`) and judge whether it's user-facing (a real user would notice the behavior/UI change) or purely internal (refactor, CI wiring, doc/skill-only) — internal PRs correctly have no entry and need none, so add their numbers to a comma-separated `--internal` list and re-run. For user-facing gaps, draft a one-line entry in the existing style and present it in chat for confirmation. Once confirmed, add it both to `origin/main` (a small separate PR against `origin/main`'s `CHANGELOG.md` `Unreleased` section, since that file is the canonical source of truth for every future release, per `CLAUDE.md`) and to this beta's `## [<beta-version>]` section.

   **If `origin/main` cut its own stable release since the last beta sync**, some flagged gaps will be PRs that merged *before* that release's own commit — i.e. they already shipped to stable, and (if user-facing) may already have an entry sitting in that release's own `## [<version>]` section further down the file. `check` only ever looks inside the section named by `--section`, so it cannot see that existing entry and will flag the PR as uncovered anyway. Don't duplicate the entry: `git log --format='%h %ci %s' -1 <sha>` for the flagged PR's merge commit against the release-commit's own timestamp tells you which side of the cut it fell on. Before the release commit and already described in that section → `--internal` (with the real reason being "already documented in `<version>`", not "no user-facing effect" — note this distinction to whoever reads the internal list later). Before the release commit but genuinely never documented anywhere → this is a real historical gap in an already-published stable changelog; add a beta-section entry so beta users see it (they're still behind), but treat editing the already-published section on `origin/main` as optional cleanup, not part of this release. After the release commit → an ordinary new gap, handled as above.
   A prose changelog bullet with no `[#N](...)` link (older entries sometimes have this) also fails coverage even though the content is right there — the fix is adding the link, not the paragraph.
5. **Merge `beta/main` into this branch — expect exactly two conflicts, and that's normal, not an error:**

   ```
   git fetch beta main && git merge beta/main --no-ff
   ```

   `beta/main`'s tip is never an ancestor of `origin/main` after the very first beta release (its own version-stamp commit only exists there), so this is never a fast-forward and a plain merge is the correct tool going forward — a failed `--ff-only` here does *not* mean the "beta never gets its own commits" rule was broken. Two conflicts are guaranteed by construction and mechanical to resolve:
   - `bess_manager/config.yaml`'s `version:` line — keep **ours** (the new `bN` this release just set in step 3).
   - `CHANGELOG.md`'s heading — don't resolve it by hand. The 3-way merge cannot express "append step 4's new section onto beta's accumulated history", so it collapses the new section into the previous one (issue #648) or misplaces the historical section. **Git may report this file as cleanly auto-merged with no conflict at all — do not trust that either**, for the same reason: a clean 3-way merge is just as capable of silently collapsing/misplacing the section as a conflicted one, it just does so without telling you. Run the `build`/`check` steps below regardless of whether git flagged a conflict on this file. Resolve deterministically instead — extract both conflicted sides (if there was no conflict, use `git show HEAD:CHANGELOG.md` for "ours" and `git show MERGE_HEAD:CHANGELOG.md` for "theirs" in place of the `:2:`/`:3:` stage lookups, which only exist for an actual conflict), rebuild, then re-verify:

     ```
     git show :2:CHANGELOG.md > changelog-new.md
     git show :3:CHANGELOG.md > changelog-beta.md
     scripts/check-changelog.py build --new changelog-new.md --beta changelog-beta.md --out CHANGELOG.md
     rm changelog-new.md changelog-beta.md
     ```

     `build` keeps beta/main's published history verbatim and inserts the new version section after the preamble — byte-stable, no section collapse. Then re-run the full invariant check against beta, now including prepend-only:

     ```
     scripts/check-changelog.py check --changelog CHANGELOG.md \
       --since-ref "$(git merge-base origin/main beta/main)" --section <beta-version> \
       --beta-ref beta/main --internal <comma-separated internal PRs>
     ```

     It must exit 0: coverage (every PR merged since the last beta is listed — by PR number or a referenced issue), no re-announcing (nothing already shipped is re-listed), and prepend-only (stripping the new section leaves beta/main's file byte-for-byte). If it fails, `build` was not the only resolution that happened — investigate before committing.

   Any *other* file conflicting is not expected and needs real investigation (usually: `origin/main` moved between when this branch's base was chosen and now, surfacing content `beta/main` hasn't seen — resolve by taking the newer, `origin/main`-based side, since that's always the more current code). Commit the resolution as `git commit -m "merge: reconcile beta/main history for v<beta-version> release"`.
6. **Run tests locally** — ALL of these must pass before proceeding:
   - **If this branch/worktree has no `.venv` yet** (e.g. it was cut fresh via `git worktree add ... origin/main`, per the Worktree Conventions in `docs/agents/local-agent-environment.md`), create one before running anything: check `.python-version` for the pinned interpreter (use `pyenv exec` if the system `python3` is older — mismatched versions surface as unrelated-looking `TypeError`s on `X | None` syntax deep in imports, not as a version error), then `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt -r backend/requirements.txt`. `.venv` is gitignored, so it never comes along with the worktree/branch even though other worktrees in the repo each have their own. Same story for `frontend/node_modules` (also gitignored, also per-worktree) — `cd frontend && npm install` before any `npx vitest`/`npx tsc` call if it isn't there.
   - **Sandbox note (pip/npm)**: a fresh install needs registry egress beyond the default allowlist — `pip install` needs `allowed_domains: ["pypi.org", "files.pythonhosted.org"]`, `npm install` needs `allowed_domains: ["registry.npmjs.org"]`. A `403`/`Tunnel connection failed`/`ERR_SOCKET` on either is this, not a real network outage.
   - **Sandbox note (pytest, important)**: run `pytest -m "not slow"` with `dangerouslyDisableSandbox: true` from the start, not sandboxed-then-retry. `backend/tests/test_quality_check_mypy_gate.py` shells out to `scripts/quality-check.sh`, whose mypy-ratchet baseline extraction does `git archive | tar` into a directory made by `mktemp` under `/var/folders` — denied under the sandbox with `mkdtemp failed ... Operation not permitted`. That failure alone would just skip the mypy delta check, but `quality-check.sh` also has a couple of unconditional `Path(...).read_text()` reads inside its bot-workflow-contract guards (`.github/workflows/issue-analyze.yml`, `.claude/settings.json`) that are fine against the real repo tree but throw when the mypy test's fixture briefly redirects the script into a throwaway directory that legitimately lacks them — and because that throw happens inside the *same* sandbox-triggered code path, all of it reads as "6 failed" with a wall of unrelated-looking tracebacks (`FileNotFoundError`, both mypy-gate and bot-workflow-guard errors mixed together). None of it is a real regression; confirm by re-running just that one file unsandboxed (`pytest backend/tests/test_quality_check_mypy_gate.py -q`) before concluding anything is actually broken, then rerun the full `-m "not slow"` suite unsandboxed.
   - `pytest -m "not slow"` (includes scenario discovery regression tests)
   - `pytest core/bess/tests/unit/test_scenario_discovery.py -v` (show individual scenario results)
   - `npx vitest run` (frontend tests)
   - `cd frontend && npx tsc --noEmit` (TypeScript type check — catches errors that vitest and vite build miss)
   - If any fix during this session revealed another bug, fix it now. Do not cut a release per fix — batch fixes locally until all tests pass.
7. **Run `black --check .` and `ruff check .`** — fix any formatting issues before committing.
8. **Commit** all changes to the beta-release-tmp branch. **Sandbox note**: from inside a worktree, `git checkout -b`/`commit`/`merge`/`branch --set-upstream-to` can fail with `error: could not lock config file .git/config: Operation not permitted` (branch creation writes upstream-tracking keys into the *main* checkout's `.git/config`, which the sandbox may not grant this worktree write access to) — the ref itself is usually still created despite the error (`git branch --show-current` / `git log -1` will confirm), so check that before assuming nothing happened, then retry the same command with `dangerouslyDisableSandbox: true` to finish cleanly (or just to set upstream tracking) rather than re-doing the whole step.
9. **Push branch to beta remote**: `git push beta beta-release-v<version>-tmp:beta-release-v<version>-tmp`
10. **Create PR** against `beta/main`:
   ```
   gh pr create --repo johanzander/bess-manager-beta \
     --base main --head beta-release-v<version>-tmp \
     --title "release: v<version>" --body "<changelog>"
   ```

   **If `beta/main`'s history still contains an old squash-merged release (from before step 12 switched to a regular merge), the Commits tab on this PR will show ~100 unrelated-looking commits spanning weeks — that's expected, not a sign something went wrong.** A squashed release commit has no ancestry to `origin/main`'s individual commits, so a branch cut fresh from `origin/main` (step 3) sees all of that history as "not yet in `beta/main`," even though most of it already shipped to beta users in substance. Once every release in the chain has used a regular merge (step 12), this stops happening — `beta/main` stays a true descendant of `origin/main` and each release's diff shrinks to the real delta. To review what's actually new regardless, use the **Files Changed** diff (`gh pr diff <pr-number> --stat`), not the Commits tab.
11. **Monitor CI** on the PR. Check with:
   ```
   gh pr checks <pr-number> --repo johanzander/bess-manager-beta --watch
   ```
   **If any check fails**: read the failure logs with `gh run view <run-id> --repo johanzander/bess-manager-beta --log-failed`, fix the issue locally, commit, push, and re-check. Do NOT proceed to merge until all required checks pass. Also run `npx tsc --noEmit` locally before pushing — the CI type-check catches errors that `npm run build` misses.
12. **Merge PR with a regular merge commit, not squash**: `gh pr merge <pr-number> --repo johanzander/bess-manager-beta --merge`. Squashing discards `beta/main`'s ancestry to `origin/main`'s real commit history, so every future release branch (cut fresh from `origin/main`, step 3) sees `beta/main`'s file content as unrelated blobs instead of an older snapshot of the same lineage — producing spurious merge conflicts in step 5 on any file that changed in between, even when one side is simply stale. A regular merge keeps `beta/main` a true descendant of `origin/main`, so subsequent releases get a clean 3-way merge with only the two structurally-expected conflicts.
13. **Tag and push tag**:
    ```
    git fetch beta main
    git tag v<version> beta/main
    git push beta v<version>
    ```
14. **Create a published GitHub Release** — pushing the tag alone does NOT trigger the image build; `release-addon.yml` only fires on `release: published`:
    ```
    gh release create v<version> --repo johanzander/bess-manager-beta \
      --title "v<version>" --prerelease --notes "<changelog>"
    ```
15. **Verify the build and images**:
    ```
    gh run list --repo johanzander/bess-manager-beta --workflow release-addon.yml -L 1
    podman pull ghcr.io/johanzander/bess-manager-beta-amd64:<version>
    ```
    A successful anonymous pull confirms both that the build succeeded and that the GHCR package is public (first release of a new package name needs a manual visibility toggle otherwise).

### Required CI checks on `beta/main`
- Fast tests
- Frontend checks
- E2E tests
- Code quality

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
