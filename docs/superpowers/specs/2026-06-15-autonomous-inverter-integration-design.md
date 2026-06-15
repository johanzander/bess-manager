# Autonomous Inverter Integration — Design

**Status:** Draft for review
**Date:** 2026-06-15
**Branch:** `feat/inverter-integration`
**Originating request:** Issue [#130](https://github.com/johanzander/bess-manager/issues/130)
(Solis S6-EH3P10K hybrid inverter) — first real target.
**Precedent:** Issue [#126](https://github.com/johanzander/bess-manager/issues/126)
(ENTSO-e / Belpex price provider), shipped via the skill-driven lifecycle.

## Goal

Reach **full autonomy** for new inverter support: a user requests a new
inverter on a GitHub issue, and the system implements it, ships it as an
experimental beta, collects a real user config, locks it into the regression
suite, re-ships green, waits for the user to confirm on their hardware, and
graduates it to a stable release — communicating in the issue/PR throughout,
with humans only in the two gates that genuinely require them (the user's debug
log and the user's hardware confirmation).

The endgame mirrors exactly what was done for the Belpex price provider (#126),
**reusing the pieces that already exist** rather than building a parallel
automation stack.

## Non-goals

- A new automation framework. We extend the existing `@claude-bot` pipeline and
  the existing lifecycle skills.
- Replacing human gates with fabricated logs/confirmations. Gates stay human.
- Changing the optimizer, schedule algorithm, or any inverter control semantics
  beyond what a new platform requires.

## Existing assets (reuse these)

**Manual skill layer** (run by an agent in a session):

| Skill | Role | Location |
|-------|------|----------|
| `add-price-provider` | Implementation recipe for a new price provider | `feature/entsoe-belpex-price-source` branch (not yet on `main`) |
| `feature-lifecycle` | Generic 6-stage experimental→stable orchestrator, **already inverter-aware** | same branch |
| `release` | Beta + prod deploy | on `main` (`.claude/skills/release/`) |

**Automated GitHub layer** (event-driven, stateless CI; each = a workflow +
inline prompt + `anthropics/claude-code-action@v1`, gated on owner
`@claude-bot <cmd>`):

| Workflow | Trigger | Role |
|----------|---------|------|
| `issue-triage.yml` | auto on issue open/edit | classify + label (bug / question / **enhancement** / needs-info) |
| `issue-analyze.yml` | `@claude-bot analyze` | deep root-cause; dispatches the **`bess-analyst`** subagent |
| `issue-fix.yml` | `@claude-bot fix` | minimal bug fix → draft PR |
| `pr-review.yml` | `@claude-bot` on a PR | review diff against rules |

**Supporting infrastructure:** `bess-analyst` subagent, the regression harness
(`scripts/mock_ha/scenarios/from_debug_log.py`, `test_scenario_discovery.py`),
the Playwright wizard E2E, and the `bess-agent` GitHub identity for automated
issue/PR comments.

## Gaps between today and full autonomy

1. **No inverter implementation skill.** There is no `add-inverter-platform`
   (the equivalent of `add-price-provider`). This is the largest gap. Inverters
   are harder than price providers: a full `InverterController` subclass
   (~10 abstract methods — `create_schedule`, `write_schedule_to_hardware`,
   `compare_schedules`, `read_and_initialize_from_hardware`, `sync_soc_limits`,
   `get_all_tou_segments`, …), per-platform sensor-suffix maps, detection wiring
   in `ha_api_controller.py` (`_INVERTER_PLATFORMS`, `detect_inverter_integrations`),
   and a **control paradigm that differs per family** (TOU slots vs
   charge/discharge period lists vs VPP commands).
2. **The lifecycle skills are not on `main`.** They live on
   `feature/entsoe-belpex-price-source`. CI checks out the repo, so the GitHub
   action can only load skills that are on `main`.
3. **No GitHub entry point for the integration lifecycle.** The pipeline only
   fixes bugs. Nothing invokes `feature-lifecycle`. Triage labels feature
   requests `enhancement` and parks them with no forward path.
4. **The re-entrancy problem (the core architectural issue).**
   `feature-lifecycle` spans days, with **human gates** (user installs beta →
   posts logs; user confirms on hardware) and CI polling. A single GitHub
   Actions run cannot wait days. The lifecycle must be **resumable**.

## Target architecture (full autonomy)

Reuse the command-gated pattern; do **not** build a parallel stack.

- **Entry point:** `@claude-bot integrate` on an inverter/provider issue. Later,
  triage auto-detects "new inverter / new HA integration" requests and suggests
  (or launches) it.
- **New workflow `issue-integrate.yml`** with a **thin, resumable prompt**:
  > "Invoke the `feature-lifecycle` skill for issue #N. You are *resuming* — read
  > the PR-body checklist to find the current stage, advance until the next human
  > gate or CI checkpoint, then stop and post the ask."

  It calls `add-inverter-platform` (or `add-price-provider`) for Stage 1 and the
  `release` skill for deploys.
- **State machine = the PR-body checklist.** `feature-lifecycle` already
  maintains a six-box checklist in the PR body. That *is* the durable state; no
  external store is needed.
- **Resume triggers** (what makes "autonomous + multi-day" work on stateless CI):
  - `issue_comment` / PR review submitted → a human gate may have cleared →
    re-enter, read checklist, advance.
  - `workflow_run` (CI completed) / `check_suite` → CI checkpoint reached →
    re-enter, advance past Stage 4.
- **Lifecycle host:** run `feature-lifecycle` **directly** from the workflow
  prompt (recommended — fewest moving parts, honors "no separate stack"). A
  dedicated `inverter-integrator` subagent is an alternative if isolation is
  later wanted; deferred unless needed. *(Open decision D1.)*

### Lifecycle → trigger mapping

| Lifecycle stage | Who advances it | Trigger |
|-----------------|-----------------|---------|
| 1. Implement + ship experimental beta | bot | `@claude-bot integrate` |
| 2. User debug log (GATE) | **user**, then bot verifies | `issue_comment` with log |
| 3. Lock config into regression suite | bot | continues from Stage 2 run |
| 4. Re-ship beta, CI green | bot | `workflow_run` (CI) |
| 5. User confirms on hardware (GATE) | **user** | `issue_comment` confirmation |
| 6. Graduate to stable | bot | continues from Stage 5 run |

## Staged rollout

Each stage is independently useful and shippable. This mirrors the incremental
approach that worked for #126.

### Stage A — `add-inverter-platform` skill (this session)

Write the implementation skill: the inverter equivalent of `add-price-provider`.
Manual use, exactly like its sibling. Validate by dry-running it against Solis
S6 (#130) — i.e. confirm the skill's steps map cleanly onto a real new inverter.

**Deliverable:** `.claude/skills/add-inverter-platform/SKILL.md`.
**Exit:** the skill enumerates every file an inverter integration touches, in
order, with the "verify against integration source, never guess" rules, and a
reviewer agrees it would carry Solis #130 end-to-end.

### Stage B — Land the skills on `main`

Bring `feature-lifecycle`, `add-price-provider`, and the new
`add-inverter-platform` onto `main` so CI checkouts can load them. Confirm
`claude-code-action` discovers project `.claude/skills/`.

**Deliverable:** skills merged to `main`; a note in `CLAUDE.md` referencing the
lifecycle skills.
**Exit:** a CI run can invoke `feature-lifecycle` by name.

### Stage C — `issue-integrate.yml` entry point

Add the `@claude-bot integrate` workflow that invokes `feature-lifecycle`
resumably. Wire the human-gate resume triggers (`issue_comment`, PR review).

**Deliverable:** `.github/workflows/issue-integrate.yml`.
**Exit:** `@claude-bot integrate` on a test issue runs Stage 1 (implement + ship
experimental beta + open draft PR with the checklist) and stops at the Stage 2
gate.

### Stage D — Triage routing + CI auto-advance

Triage detects new-inverter/provider requests and suggests/launches integrate.
Add the `workflow_run` trigger so the lifecycle auto-advances past the CI
checkpoint (Stage 4) without a manual nudge. This completes full autonomy.

**Deliverable:** triage prompt update + `workflow_run` trigger in
`issue-integrate.yml`.
**Exit:** an inverter request issue can reach a graduated stable release with
human input only at the two real gates.

## Open decisions

- **D1 — Lifecycle host:** run `feature-lifecycle` directly from the workflow
  prompt (recommended) vs. a dedicated `inverter-integrator` subagent.
  *Recommendation:* direct, reusing existing skills; revisit only if the prompt
  grows unwieldy.
- **D2 — Where the skills land:** merge the existing
  `feature/entsoe-belpex-price-source` lifecycle skills to `main` as part of
  Stage B, vs. cherry-pick just the skill files. *Recommendation:* cherry-pick
  the `.claude/skills/` files so Stage B doesn't drag in unrelated provider code.
- **D3 — First live run:** after Stage A, do we immediately drive Solis #130
  through the lifecycle manually (proving the skill before automating), or wait
  until Stage C? *Recommendation:* manual Solis run after Stage A — it validates
  the skill and delivers #130, and is the same "prove manually, then automate"
  path #126 followed.

## Risks

- **Inverter control complexity.** Unlike a price source (read attributes),
  a new inverter needs a working *control* path. If Solis lacks a HA integration
  exposing controllable entities, Stage 1 can implement monitoring only and must
  mark control "not yet supported" (as GEN3 already does) — the skill must make
  this branch explicit.
- **CI cannot wait for humans.** Mitigated by the PR-checklist state machine +
  event-triggered resume. If a resume trigger misfires, the lifecycle is
  idempotent: re-reading the checklist is safe.
- **Cost.** Each lifecycle resume is a paid `claude-code-action` run. Keep the
  resume prompt thin and the work per invocation bounded to one stage.
- **Never claim real-world validation** before Stage 5 — the `experimental`
  marker stays until the user confirms on hardware (per project maturity
  conventions).
