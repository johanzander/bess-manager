# Release Skill

## Beta Release (`release beta`)

1. **Determine next version**: Run `git fetch beta main` then check `git show beta/main:config.yaml | grep '^version:'` to see the version **currently on beta/main**. Also check `gh release list -L 5 -R johanzander/bess-manager-beta` for published releases. The new version MUST be higher than both. Increment the beta number (e.g. `9.0.0b12` → `9.0.0b13`). **CRITICAL: If local config.yaml already matches beta/main, you MUST still bump — same version = HA won't detect the update.**
2. **Run tests locally** — backend (`pytest -m "not slow"`), frontend (`npx vitest run`). Do NOT proceed if any fail.
3. **Bump version** in `config.yaml` to the next version determined in step 1.
4. **Update CHANGELOG.md** — add entry at the top following Keep a Changelog format (Fixed/Added/Changed sections). This is NOT optional.
5. **Run `black --check .` and `ruff check .`** — fix any formatting issues before committing.
6. **Commit** all changes to the current branch.
7. **Push branch to beta remote**: `git push beta <branch>:<branch>`
8. **Create PR** against `beta/main`:
   ```
   gh pr create --repo johanzander/bess-manager-beta \
     --base main --head <branch> \
     --title "release: v<version>" --body "<changelog>"
   ```
9. **Wait for CI** to pass on the PR. Check with:
   ```
   gh pr checks <pr-number> --repo johanzander/bess-manager-beta --watch
   ```
10. **Merge PR**: `gh pr merge <pr-number> --repo johanzander/bess-manager-beta --squash`
11. **Tag and push tag**:
    ```
    git fetch beta main
    git tag v<version> beta/main
    git push beta v<version>
    ```
12. **Verify**: `git ls-remote --tags beta | grep v<version>`

### Required CI checks on `beta/main`
- Fast tests
- Frontend checks
- E2E tests
- Code quality

## Production Release (`release` or `release prod`)

1. **Check version**: `gh release list -L 5` (origin repo)
2. **Run full test suite** — including `pytest -m slow`
3. **Bump version** in `config.yaml`
4. **Update CHANGELOG.md** — this is NOT optional.
5. **Run `black --check .` and `ruff check .`** — fix any formatting issues.
6. **Create PR** against `origin/main`, wait for CI
7. **Merge**, tag, push tag to origin
8. **Create GitHub Release**: `gh release create v<version> --title "v<version>" --notes "<changelog>"`
