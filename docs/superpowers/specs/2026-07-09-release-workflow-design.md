# Release Workflow Redesign

**Status:** Approved design, not yet implemented
**Date:** 2026-07-09

## Problem

BESS Manager ships two Home Assistant add-ons from two GitHub repos:

- `bess-manager` (origin) — stable, add-on "BESS Manager"
- `bess-manager-beta` (beta) — prerelease, add-on "BESS Manager (Beta)"

The intent was always that beta tracks main plus a version bump. In practice
work has landed inconsistently: sometimes a PR merges to `origin/main` and is
later ported to beta; sometimes a fix or experimental feature is committed
directly to `beta/main` and ported back to main later, if at all. There is no
enforced direction of flow.

As of this design, `main` and `beta/main` have diverged by 13 commits each
way. Beta-only work includes at least "Remove ad hoc DP guardrails in favor
of pure backward induction" (#59) and the action-derived GRID_CHARGING
display fix (#62). Main-only work includes 13 merged PRs never ported to
beta. A stray branch (`release/v9.9.0b8`) also exists on origin, already
behind beta's published `v9.9.0b9`.

The `CHANGELOG.md` compounds this: beta entries are hand-authored with
`(beta-only)` markers and their own `9.9.0bN` headings, which then have to be
manually reconciled with main's changelog when features are ported.

## Goals

- One direction of flow: `main` → `beta`, never the reverse.
- No commit ever exists only on beta.
- Preserve the ability to install stable and beta side by side on the same
  HA instance (even though only one can run at a time, since they share
  port 8080) — this is why two repos/add-ons are kept rather than collapsed
  into one. (Verified this matches the standard community pattern: the
  largest third-party add-on org, hassio-addons, uses the identical
  `repository` + `repository-beta` split — Home Assistant has no per-add-on
  beta-channel toggle for third-party add-ons, only for HA Core itself.)
- A documented, low-drama path for hotfixing the currently-published stable
  version when main has moved on with unrelated, unreleased work.
- A single authored changelog, not two that need reconciling.

## Design

### 1. Branch model

- **`origin/main`** is the single source of truth and always represents
  "next release in progress." Every change — features, fixes, and
  experimental integrations (gated behind a stability flag/marker, not a
  branch) — merges here via normal PR + CI. Nothing is ever committed
  directly to the beta repo.
- **`beta/main`** is a *content* mirror, not a literal git fast-forward of
  `origin/main` — those are not the same thing here, and the original version
  of this doc conflated them. Each beta release adds a version-stamp +
  changelog-heading-rename commit that changes `bess_manager/config.yaml`'s
  `version`/`name`/`slug`/`image` fields and renames `CHANGELOG.md`'s
  `## [Unreleased]` heading. Because that commit only exists on `beta/main`,
  `beta/main`'s tip is never again an ancestor of `origin/main` after the
  very first release — a literal `git merge --ff-only origin/main` run from
  `beta/main` **cannot succeed from the second release onward**, by
  construction, not as a failure mode. (An earlier version of this doc
  described that ff-only merge as the steady-state mechanism and treated a
  conflict as a hard error signaling a rule violation; two releases into the
  new model that turned out to be wrong — see the retrospective note below.)

  The actual mechanism: each release branches fresh from `origin/main`,
  applies the version-stamp + changelog-rename commit, then merges
  `beta/main` into that branch (not the other way around) before opening the
  beta PR. This merge has exactly two **structurally guaranteed, mechanical**
  conflicts every single time — not a sign anything is wrong:
  - `bess_manager/config.yaml`'s `version:` line (`origin/main`-based branch
    says the new `bN`; `beta/main` says the previous release's `bN` — always
    keep the new one)
  - `CHANGELOG.md`'s heading line (`origin/main`-based branch renames
    `## [Unreleased]` to the new version; `beta/main` already renamed it to
    the previous version — always keep the new one, and splice the previous
    release's already-published section back in immediately below rather
    than dropping it)

  Any *other* conflicting file is not expected and needs real investigation
  — it usually means `origin/main` moved between when a beta build's base
  commit was chosen and when the merge runs, surfacing content `beta/main`
  hasn't seen yet (normal beta-lag, resolved by taking the newer side, not a
  rule violation).

  **Retrospective note (added after the `v9.9.0b11` release):** the
  recurring two-line conflict above was initially mistaken for something
  needing a one-off "reconciliation," the same framing as the one-time
  13/13 divergence cleanup in the Migration section below. It isn't one-off
  — it recurs every release by construction, as explained above. The release
  skill now documents it as an expected step instead of a surprise.
- **`release-X.Y` branches** are the one exception: created on demand from a
  stable tag, living only as long as a hotfix takes (see §4), then deleted.

### 2. Versioning

Keep semver with a prerelease suffix — no change to the scheme itself, only
to discipline:

- Main's `config.yaml` version is only bumped at release time (today it sits
  at the last-released `9.8.1` even though 13 unreleased commits exist past
  it — that drift stops).
- Each beta sync bumps `9.9.0b1` → `9.9.0b2` → … in the beta repo only.
- Promoting to stable is a version-stamp change on the *same commit* last
  validated as a beta: `9.9.0bN` → `9.9.0`, released from `origin/main`.
- Hotfix patches on a release branch bump the patch digit: `9.9.0` →
  `9.9.1`.

### 3. Changelog

`CHANGELOG.md` on `origin/main` is the only authored changelog. Entries
accumulate under an `## [Unreleased]` heading as each PR merges (extends the
existing "update CHANGELOG on PR merge" practice with an `Unreleased`
heading convention). Nothing beta-specific is ever hand-written:

- **Beta sync**: the beta repo's `CHANGELOG.md` gets the current
  `Unreleased` section from `origin/main` copied in verbatim under a new
  `9.9.0bN` heading — mechanical, not authored.
- **Stable promotion**: on `origin/main`, the `Unreleased` heading is
  renamed to the stable version (`## [9.9.0] - date`), capturing everything
  that accumulated across however many beta iterations it took, as one
  entry in main's real history.

Net effect: main's changelog only ever shows stable versions; beta's
changelog shows the finer-grained `bN` drops; there is exactly one place
content is ever written by hand.

### 4. Hotfix process

For a bug found in the currently-published stable version while `main` has
moved on with unrelated, unreleased work:

1. The fix is authored and merged to `main` first via a normal PR — `main`
   remains the only place a fix is ever authored.
2. `git checkout -b release-X.Y vX.Y.Z` (branch from the stable tag, not
   from main).
3. Cherry-pick just the fix commit(s) from `main` onto `release-X.Y`.
4. Bump the patch version, update `CHANGELOG.md` on that branch, tag
   `vX.Y.(Z+1)`, release from `origin`.
5. Delete `release-X.Y` once the patch is out — it is not long-lived.

This is a judgment call, not a hard rule: if `main` is still close to the
last stable tag (little or no risky work merged since), it's simpler to cut
a normal patch release from `main` directly instead of branching. Reach for
the release-branch/cherry-pick path specifically when main has accumulated
unrelated, unreleased, or unvalidated work that shouldn't ship alongside the
fix.

### 5. Experimental features

`feature-lifecycle`-driven work (new inverter/price-provider integrations
that can't be self-validated) now merges to `origin/main` behind a stability
flag/marker instead of going to beta first. It flows to beta through the
normal sync like everything else. The feature "graduates" (flag removed)
once a real user has validated it on beta — that is a metadata change, not a
different code path or branch.

### 6. Tooling & docs changes

- `.claude/skills/release/SKILL.md` rewritten around the new mechanics:
  `release beta` = fetch + `merge --ff-only origin/main` into beta, version
  bump, changelog copy, tag, release (no more diffing beta against main to
  find "what's new"). `release prod` = rename `Unreleased` → stable version
  on `origin/main`, tag, release (no more diffing against beta at all). A
  new `release hotfix` procedure documents §4.
- `feature-lifecycle` skill's target branch changes from beta-first to
  main-first-behind-a-flag.
- `docs/agents/workflow.md` and the CLAUDE.md "Release Workflow" section
  updated to describe this model.
- Memory entries `feedback_beta_vs_prod_channel.md` and
  `project_beta_release_workflow.md` will need updating once this ships to
  reflect that beta-first development no longer exists as a pattern.

## Migration (one-time, separate from tooling work)

Before the new model can start, the current 13/13 divergence must be
reconciled once:

1. Forward-port the beta-only commits into `origin/main` via normal PR +
   review + CI (the last time anything ever moves beta → main).
2. Fast-forward `beta/main` to match `origin/main` exactly — this is now a
   clean fast-forward, not a force-push clobbering unique work, because step
   1 already emptied beta's unique commits.
3. Delete the stale `release/v9.9.0b8` branch on origin.

This reconciliation is real work with its own risk (behavioral changes like
the DP guardrail removal need real review, not a blind port) and should be
its own PR/session, not bundled with the tooling changes in §6.

## Non-goals

- Collapsing the two repos/add-ons into one. Ruled out: no HA mechanism
  supports per-add-on stable/beta channel selection for third-party add-ons,
  and users rely on installing both side by side (even if only one runs at
  a time).
- Changing the semver scheme itself.
