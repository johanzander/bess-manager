---
name: Beta release workflow
description: How to release beta versions — must use PR with CI checks before merging to beta/main
type: project
originSessionId: 65d25685-af51-429c-80ea-1d6975329e1d
---
HA Supervisor has built-in beta channel support based on version string conventions.

**Beta release**: set `version` in `bess_manager/config.yaml` to e.g. `"9.0.0b11"`, tag as `v9.0.0b11`.
**Stable release**: set `version` to `"9.0.0"`, tag as `v9.0.0`.

Only users who enable "Show beta and dev channel releases" in the add-on UI will see beta versions.

**Release process (since 2026-06-12):**
1. Never push directly to `beta/main` — always go through a PR
2. Push branch to beta remote, create PR against `beta/main`
3. CI runs automatically (Fast tests, Frontend checks, E2E tests, Code quality)
4. Merge only after CI passes
5. Create a GitHub Release (tag `vX.Y.Zb1`, target branch) — this triggers `release-addon.yml`
6. Wait for the release workflow to build and push Docker images (amd64 + aarch64) to GHCR
7. Verify images are pullable
8. Ensure GHCR packages are public (first release of a new package name requires manual visibility toggle)

Branch protection is enabled on `beta/main` requiring these CI checks to pass.

**Why:** Direct pushes skip CI validation. A prior release (v9.0.0b11) was pushed without CI. PRs ensure all tests run before code reaches users. Pre-built Docker images (since v9.3.0) replaced source-based builds for faster installs and no build failures on user hardware.

**How to apply:** Version in `bess_manager/config.yaml` must match the git tag. Always verify GHCR images are pullable after the release workflow completes.
