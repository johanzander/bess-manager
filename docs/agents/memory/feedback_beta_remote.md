---
name: Beta releases go to beta remote main branch
description: Push beta releases to the 'beta' remote's main branch, never to 'origin' or feature branches on beta
type: feedback
originSessionId: 1229ad8f-3bfa-4c05-8c12-014e71b97589
---
Beta releases (v9.0.0bN) must be pushed to the `beta` remote's **main** branch, not `origin`.

**Why:** The beta repo (bess-manager-beta) is a separate GitHub repo used by HA Supervisor's beta add-on channel. GitHub/HA picks up releases from `main`, not feature branches. The main repo (origin/bess-manager) tracks stable releases (currently 8.3.x) and must not have beta branches or tags.

**How to apply:** When releasing a beta:
1. `git push beta release/v9.0.0b1:main` — push local branch to beta's main
2. `git push beta v9.0.0bN` — push the tag
3. Never push beta branches/tags to `origin`
4. Don't create feature branches on the beta remote — only main matters
