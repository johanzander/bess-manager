# Release Skill

## Beta Release (`release beta`)

1. **Determine next version**: Run `git fetch beta main` then check `git show beta/main:config.yaml | grep '^version:'` to see the version **currently on beta/main**. Also check `gh release list -L 5 -R johanzander/bess-manager-beta` for published releases. The new version MUST be higher than both. Increment the beta number (e.g. `9.0.0b12` → `9.0.0b13`). **CRITICAL: If local config.yaml already matches beta/main, you MUST still bump — same version = HA won't detect the update.**
2. **Sync with target branch** — `git fetch beta main && git merge beta/main`. Resolve any conflicts locally. Never push a branch that is behind the target.
3. **Run tests locally** — ALL of these must pass before proceeding:
   - `pytest -m "not slow"` (includes scenario discovery regression tests)
   - `pytest core/bess/tests/unit/test_scenario_discovery.py -v` (show individual scenario results)
   - `npx vitest run` (frontend tests)
   - `cd frontend && npx tsc --noEmit` (TypeScript type check — catches errors that vitest and vite build miss)
   - If any fix during this session revealed another bug, fix it now. Do not cut a release per fix — batch fixes locally until all tests pass.
4. **Bump version** in `config.yaml` to the next version determined in step 1.
4. **Update CHANGELOG.md** — add entry at the top following Keep a Changelog format (Fixed/Added/Changed sections). This is NOT optional. When an item links to a PR, keep it to one line (bold title + a short clause) — the PR description already has the full explanation, don't duplicate it in the changelog.
5. **Run `black --check .` and `ruff check .`** — fix any formatting issues before committing.
6. **Commit** all changes to the current branch.
7. **Push branch to beta remote**: `git push beta <branch>:<branch>`
8. **Create PR** against `beta/main`:
   ```
   gh pr create --repo johanzander/bess-manager-beta \
     --base main --head <branch> \
     --title "release: v<version>" --body "<changelog>"
   ```
9. **Monitor CI** on the PR. Check with:
   ```
   gh pr checks <pr-number> --repo johanzander/bess-manager-beta --watch
   ```
   **If any check fails**: read the failure logs with `gh run view <run-id> --repo johanzander/bess-manager-beta --log-failed`, fix the issue locally, commit, push, and re-check. Do NOT proceed to merge until all required checks pass. Also run `npx tsc --noEmit` locally before pushing — the CI type-check catches errors that `npm run build` misses.
10. **Merge PR**: `gh pr merge <pr-number> --repo johanzander/bess-manager-beta --squash`
11. **Tag and push tag**:
    ```
    git fetch beta main
    git tag v<version> beta/main
    git push beta v<version>
    ```
12. **Create a published GitHub Release** — pushing the tag alone does NOT trigger the image build; `release-addon.yml` only fires on `release: published`:
    ```
    gh release create v<version> --repo johanzander/bess-manager-beta \
      --title "v<version>" --prerelease --notes "<changelog>"
    ```
13. **Verify the build and images**:
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

1. **Check version**: `gh release list -L 5` (origin repo)
2. **Run full test suite** — including `pytest -m slow`
3. **Bump version** in `config.yaml`
4. **Update CHANGELOG.md** — this is NOT optional. Same rule as beta: one line per PR-linked item, no restating the PR body.
5. **Run `black --check .` and `ruff check .`** — fix any formatting issues.
6. **Create PR** against `origin/main`, wait for CI
7. **Merge**, tag, push tag to origin
8. **Create GitHub Release**: `gh release create v<version> --title "v<version>" --notes "<changelog>"`
