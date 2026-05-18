---
name: Beta release workflow
description: How to release beta versions — must use PR with CI checks before merging to beta/main
type: project
originSessionId: 65d25685-af51-429c-80ea-1d6975329e1d
---
HA Supervisor has built-in beta channel support based on version string conventions.

**Beta release**: set `version` in `config.yaml` to e.g. `"9.0.0b11"`, tag as `v9.0.0b11`.
**Stable release**: set `version` to `"9.0.0"`, tag as `v9.0.0`.

Only users who enable "Show beta and dev channel releases" in the add-on UI will see beta versions.

**Release process (since 2026-05-18):**
1. Never push directly to `beta/main` — always go through a PR
2. Push branch to beta remote, create PR against `beta/main`
3. CI runs automatically (Fast tests, Frontend checks, E2E tests, Code quality)
4. Merge only after CI passes
5. Tag the merged commit and push tag

Branch protection is enabled on `beta/main` requiring these CI checks to pass.

**Why:** Direct pushes skip CI validation. A prior release (v9.0.0b11) was pushed without CI. PRs ensure all tests run before code reaches users.

**How to apply:** Use the release skill (`/release beta`) which encodes the full PR-based workflow. Version in `config.yaml` must match the git tag.
