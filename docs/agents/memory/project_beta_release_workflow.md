---
name: Beta release workflow
description: How to release beta versions of the add-on so only opt-in users receive them
type: project
originSessionId: 65d25685-af51-429c-80ea-1d6975329e1d
---
HA Supervisor has built-in beta channel support based on version string conventions.

**Beta release**: set `version` in `config.yaml` to e.g. `"8.3.0b1"`, tag as `v8.3.0b1`.
**Stable release**: set `version` to `"8.3.0"`, tag as `v8.3.0`.

Only users who enable "Show beta and dev channel releases" in the add-on UI will see beta versions.

**Why:** Allows testing on real hardware before releasing to all users. Previously, every push+tag went to everyone immediately.

**How to apply:** When the user wants to release for testing, use the `b1`/`b2` suffix. When confirmed working, drop the suffix for the stable release. Version in `config.yaml` must match the git tag.
