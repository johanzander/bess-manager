---
name: Parallel release train with agents
description: Use concurrent subagents for beta releases — test-runner, changelog, version-bumper, release-notes — gate on all green
type: feedback
originSessionId: 74ef2e47-02dd-4057-a65d-bc2ae8bea026
---
For beta releases, orchestrate parallel subagents: (1) test-runner: pytest + frontend type-check + E2E tests. (2) changelog-writer: diff commits since last tag, group by fix/feat/chore. (3) version-bumper: check GitHub releases (not local tags) for next beta number, update manifest.json and build.yaml. (4) release-notes-drafter: user-facing notes in existing style. Wait for all four, present unified diff, push only to beta remote after confirmation.

**Why:** 67 commits across 7 release sessions show a repeatable pipeline. The b6→b10 cycle was serial and slow. Duplicate versions were shipped because local tags were checked instead of GitHub releases.

**How to apply:** When asked to do a beta release, fan out the work with agents. Always check GitHub releases (not local tags) for version numbers. Gate everything on user approval before pushing to beta remote.
