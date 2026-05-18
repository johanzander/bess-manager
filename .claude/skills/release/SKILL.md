# Release Skill

## Beta Release (`release beta`)

1. **Check version**: `gh release list -L 5 -R johanzander/bess-manager-beta` and `grep '^version:' config.yaml`
2. **Run tests locally** — backend (`pytest -m "not slow"`), frontend (`npx vitest run`). Do NOT proceed if any fail.
3. **Bump version** in `config.yaml` (e.g. `9.0.0b10` → `9.0.0b11`)
4. **Commit** all changes to the current branch
5. **Push branch to beta remote**: `git push beta <branch>:<branch>`
6. **Create PR** against `beta/main`:
   ```
   gh pr create --repo johanzander/bess-manager-beta \
     --base main --head <branch> \
     --title "release: v<version>" --body "<changelog>"
   ```
7. **Wait for CI** to pass on the PR. Check with:
   ```
   gh pr checks <pr-number> --repo johanzander/bess-manager-beta --watch
   ```
8. **Merge PR**: `gh pr merge <pr-number> --repo johanzander/bess-manager-beta --squash`
9. **Tag and push tag**:
   ```
   git fetch beta main
   git tag v<version> beta/main
   git push beta v<version>
   ```
10. **Verify**: `git ls-remote --tags beta | grep v<version>`

### Required CI checks on `beta/main`
- Fast tests
- Frontend checks
- E2E tests
- Code quality

## Production Release (`release` or `release prod`)

1. **Check version**: `gh release list -L 5` (origin repo)
2. **Run full test suite** — including `pytest -m slow`
3. **Bump version** in `config.yaml`
4. **Create PR** against `origin/main`, wait for CI
5. **Merge**, tag, push tag to origin
6. **Create GitHub Release**: `gh release create v<version> --title "v<version>" --notes "<changelog>"`
