# Release Skill

## Beta Release (`release beta`)

1. **Sync local `main` with `origin/main`** — `git fetch origin main && git merge --ff-only origin/main` (run this from a plain `main` checkout, not a feature branch). If this fails to fast-forward, something is wrong locally — do not force it, investigate first.
2. **Check beta has no unique commits** — `git fetch beta main && git log --oneline origin/main..beta/main`. Expected: empty (beta is a pure mirror as of the migration). If this is non-empty, stop — a commit landed on beta directly, breaking the one-directional flow this skill exists to enforce. Do not silently overwrite it; surface it to the user.
3. **Build the release commit locally, on top of `origin/main`, before touching the beta remote** — `git checkout -b beta-release-tmp origin/main`. Bump `bess_manager/config.yaml`'s `version` field to the next beta number (check `git show beta/main:bess_manager/config.yaml | grep '^version:'` and `gh release list -L 5 -R johanzander/bess-manager-beta` first — e.g. `9.9.0b9` → `9.9.0b10`, or start `X.Y.0b1` if promoting past what main last shipped as stable). In the same commit, re-apply the beta identity fields, which never exist on main by design:
   - `bess_manager/config.yaml`: `name: "BESS Manager (Beta)"`, `slug: "bess_manager_beta"`, `image: "ghcr.io/johanzander/bess-manager-beta-{arch}"`
   - `repository.yaml`: `name: BESS Battery Manager (Beta) Repository`, `url: https://github.com/johanzander/bess-manager-beta`

   Commit as `git commit -am "release: v<beta-version>"`. Pushing this single commit (not raw `origin/main`) is what keeps the beta repo from ever momentarily claiming to be the prod add-on.
4. **Copy the changelog, don't author it** — on the same `beta-release-tmp` branch from step 3, take the current `## [Unreleased]` section verbatim from `origin/main`'s `CHANGELOG.md` (synced in step 1) and rename it to `## [<beta-version>] - <date>` in `CHANGELOG.md`. Amend it into the same commit (`git commit --amend`) rather than adding a second commit. Do not hand-write beta-specific entries — if content is missing from `Unreleased`, it means a PR merged to main without a changelog entry, which is a bug in that PR's merge process, not something to patch around here.
5. **Run tests locally** — ALL of these must pass before proceeding:
   - `pytest -m "not slow"` (includes scenario discovery regression tests)
   - `pytest core/bess/tests/unit/test_scenario_discovery.py -v` (show individual scenario results)
   - `npx vitest run` (frontend tests)
   - `cd frontend && npx tsc --noEmit` (TypeScript type check — catches errors that vitest and vite build miss)
   - If any fix during this session revealed another bug, fix it now. Do not cut a release per fix — batch fixes locally until all tests pass.
6. **Run `black --check .` and `ruff check .`** — fix any formatting issues before committing.
7. **Commit** all changes to the beta-release-tmp branch.
8. **Push branch to beta remote**: `git push beta beta-release-tmp:beta-release-tmp`
9. **Create PR** against `beta/main`:
   ```
   gh pr create --repo johanzander/bess-manager-beta \
     --base main --head beta-release-tmp \
     --title "release: v<version>" --body "<changelog>"
   ```
10. **Monitor CI** on the PR. Check with:
   ```
   gh pr checks <pr-number> --repo johanzander/bess-manager-beta --watch
   ```
   **If any check fails**: read the failure logs with `gh run view <run-id> --repo johanzander/bess-manager-beta --log-failed`, fix the issue locally, commit, push, and re-check. Do NOT proceed to merge until all required checks pass. Also run `npx tsc --noEmit` locally before pushing — the CI type-check catches errors that `npm run build` misses.
11. **Merge PR**: `gh pr merge <pr-number> --repo johanzander/bess-manager-beta --squash`
12. **Tag and push tag**:
    ```
    git fetch beta main
    git tag v<version> beta/main
    git push beta v<version>
    ```
13. **Create a published GitHub Release** — pushing the tag alone does NOT trigger the image build; `release-addon.yml` only fires on `release: published`:
    ```
    gh release create v<version> --repo johanzander/bess-manager-beta \
      --title "v<version>" --prerelease --notes "<changelog>"
    ```
14. **Verify the build and images**:
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
