# `add-inverter-platform` Skill — Implementation Plan (Stage A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write `.claude/skills/add-inverter-platform/SKILL.md` — the inverter
equivalent of `add-price-provider` — so the existing generic `feature-lifecycle`
orchestrator can drive a new inverter platform from research to graduated stable.

**Architecture:** The deliverable is a single skill document. It is **modeled
section-for-section on `add-price-provider`** but retargeted to the inverter
subsystem. The "tests" for a skill are verification passes, not pytest: (1) every
file/symbol it names must exist in the repo, (2) its structure must mirror
`add-price-provider`, and (3) a dry-run trace must show it would carry Solis S6
(#130) end-to-end. Frequent commits, one per section.

**Tech Stack:** Markdown skill file; the codebase it documents is Python
(`core/bess/`, `backend/`), React/TS (`frontend/`), Playwright E2E (`e2e/`).

**Reference skills (live on the `feature/entsoe-belpex-price-source` branch, not
on this branch).** Read them via git:
```bash
git show feature/entsoe-belpex-price-source:.claude/skills/add-price-provider/SKILL.md
git show feature/entsoe-belpex-price-source:.claude/skills/feature-lifecycle/SKILL.md
```

---

## Verified touch-point inventory (the skill must encode these)

All paths/symbols below were verified to exist on `feat/inverter-integration`
(branched from `main`).

**Backend — controller (the heaviest part):**
- Base ABC: `core/bess/inverter_controller.py` → `InverterController`. Abstract
  methods a new controller MUST implement: `active_tou_intervals`,
  `create_schedule`, `write_schedule_to_hardware`, `compare_schedules`,
  `read_and_initialize_from_hardware`, `sync_soc_limits`, `get_all_tou_segments`,
  `get_daily_TOU_settings`, `log_current_TOU_schedule`, `log_detailed_schedule`,
  `check_health`.
- Existing controllers to model on, **by control paradigm**:
  - `core/bess/growatt_min_controller.py` → `GrowattMinController` — 9-slot TOU,
    cloud service calls (`growatt_server.update_time_segment`).
  - `core/bess/growatt_sph_controller.py` → `GrowattSphController` —
    charge/discharge **period lists** (`write_ac_charge_times`).
  - `core/bess/solax_modbus_growatt_controller.py` → `SolaxModbusGrowattController`
    — local Modbus, single-segment TOU (GEN4) / mode-specific slots (GEN3),
    entity writes (select/number/button).
  - `core/bess/solax_controller.py` → `SolaxController` — ephemeral **VPP** power
    commands, auto-expiring.

**Backend — wiring:**
- `core/bess/battery_system_manager.py`:
  - `_create_inverter_controller()` (~L235) — add a `platform == "<id>"` branch.
  - `VALID_PLATFORMS` ClassVar (L187) — add the new platform id.
  - `_INVERTER_TYPE_TO_PLATFORM` (L195) — add id + any legacy alias.
  - `switch_inverter_platform()` (L254) — already generic; verify no per-platform
    special-casing needed.
- `backend/settings_store.py`:
  - `VALID_PLATFORMS` — **defined twice (L35 and L58)**; the skill MUST note both
    occurrences must be updated, and flag the duplication as a known wart.
  - `SHARED_SENSOR_KEYS` — sensor keys not tied to a platform.

**Backend — detection + sensor maps (`core/bess/ha_api_controller.py`):**
- Per-platform suffix maps (entity suffix → BESS sensor key): `GROWATT_MIN_SUFFIX_MAP`
  (L428), `GROWATT_SPH_SUFFIX_MAP` (L480), `SOLAX_GROWATT_MIN_SUFFIX_MAP` (L554),
  `SOLAX_GROWATT_SPH_SUFFIX_MAP` (L627), `SOLAX_NATIVE_SUFFIX_MAP` (L653) — add a
  new `<INVERTER>_SUFFIX_MAP`.
- Marker suffixes used for detection: `_GROWATT_TOU_MARKER_SUFFIX` (L2653),
  `_GROWATT_GEN3_MARKER_SUFFIX` (L2654), `_SOLAX_NATIVE_MARKER_SUFFIX` (L2657) —
  add a new `_<INVERTER>_MARKER_SUFFIX`.
- `_INVERTER_PLATFORMS` ClassVar (L2600) — platform → HA integration domains.
- `detect_inverter_integrations()` (L2685) and `_detect_platforms()` — add a
  detection branch keyed on the **immutable `unique_id`** suffix.

**Frontend:**
- `frontend/src/pages/SetupWizardPage.tsx` — platform option, auto-select on
  discovery, save payload, summary.
- `frontend/src/pages/SettingsPage.tsx` — inverter-platform selector.
- `frontend/src/components/settings/SensorConfigSection.tsx` and
  `frontend/src/lib/sensorDefinitions.ts` — per-platform sensor definitions.

**Tests:**
- `core/bess/tests/unit/test_registry_discovery.py`,
  `core/bess/tests/unit/test_scenario_discovery.py` — add the new platform's
  discovery case using the **real beta-tester registry fixture**.
- New controller test, modeled on `test_solax_controller.py`,
  `test_growatt_tou_scheduling.py`, or
  `test_solax_modbus_growatt_single_segment.py` (pick by control paradigm).

**Mock-HA scenario + Playwright E2E:**
- `scripts/mock_ha/scenarios/ci-wizard-<inverter>.json` — the regression fixture
  (same file drives backend discovery test AND the wizard E2E). Existing inverter
  scenarios: `ci-wizard-growatt-modbus.json`, `ci-wizard-growatt-modbus-gen3.json`,
  `ci-wizard-nordpool-solax.json`, `ci-wizard-nordpool-sph.json`, etc.
- `e2e/tests/wizard-expectations.ts`, `e2e/tests/setup-wizard.spec.ts`,
  `e2e/tests/inverter-page.spec.ts`, `e2e/run-e2e.sh`,
  `.github/workflows/ci.yml` (per-scenario step).

**Docs:**
- `docs/INVERTER_PLATFORMS.md` (the canonical per-platform reference — new
  platform gets a "How BESS Controls" section + "Required Entities" table +
  Auto-Detection entry), `README.md` (supported-inverter list), `CHANGELOG.md`,
  and the maturity memory under `docs/agents/memory/` (mark experimental).

---

## File Structure

- Create: `.claude/skills/add-inverter-platform/SKILL.md` — the only deliverable.

The skill mirrors `add-price-provider`'s seven blocks:
1. Title + one-paragraph intro.
2. The non-negotiable discovery rule (retargeted: control paradigm + unique_id).
3. Validate against a real beta-tester config.
4. Implementation checklist (in order).
5. Frontend + E2E sub-checklist.
6. Gate before commit / PR.
7. Reference table of files.

---

## Task 1: Scaffold the skill file with intro + discovery rule

**Files:**
- Create: `.claude/skills/add-inverter-platform/SKILL.md`

- [ ] **Step 1: Read the template skill**

```bash
git show feature/entsoe-belpex-price-source:.claude/skills/add-price-provider/SKILL.md
```
Study its structure — you will mirror it.

- [ ] **Step 2: Write the title + intro paragraph**

Create the file with an H1 `# Add Inverter Platform Skill` and an intro that
states: this adds support for a new inverter hardware family + its HA
integration as a BESS inverter platform; it is a recurring pattern touching the
same files in the same order; **never guess entity names, `unique_id` formats,
control service names, or attribute keys** (cite `CLAUDE.md` → "Verification
Before Action").

- [ ] **Step 3: Write the "non-negotiable discovery + control rule" section**

This is the inverter analog of add-price-provider's discovery rule. It MUST state:
1. Discovery keys off the **immutable `unique_id`** (registry), filtered by the
   integration's `platform` domain — derived from the **integration's source**,
   not a sample `entity_id`. (Cross-reference `detect_inverter_integrations` in
   `core/bess/ha_api_controller.py`.)
2. **Identify the control paradigm** before writing a controller — one of:
   (a) numbered TOU time slots (model: `GrowattMinController`),
   (b) mode-specific time slots / GEN3,
   (c) charge/discharge **period lists** (model: `GrowattSphController`),
   (d) ephemeral **VPP** power commands (model: `SolaxController`).
   And whether control is via **HA service calls** or **entity writes**
   (select/number/button/switch).
3. **Monitoring-only is a valid first cut.** If the integration exposes
   monitoring entities but no usable control path, implement monitoring + mark
   schedule control "not yet implemented" (precedent: GEN3 in
   `docs/INVERTER_PLATFORMS.md`). The skill MUST make this branch explicit.

- [ ] **Step 4: Verify the file is valid markdown and commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
head -40 .claude/skills/add-inverter-platform/SKILL.md
git add .claude/skills/add-inverter-platform/SKILL.md
git commit -m "docs(skill): add-inverter-platform — intro + discovery/control rule"
```
Expected: file shows the H1, intro, and discovery/control rule section.

---

## Task 2: Write "validate against a real beta-tester config" section

**Files:**
- Modify: `.claude/skills/add-inverter-platform/SKILL.md`

- [ ] **Step 1: Write the section**

Mirror add-price-provider's "Validate against a real beta-tester config", but for
an inverter. It MUST instruct:
1. Ask the beta tester for a debug report (`docs/bess-debug-*.md`) containing
   their real entity registry + the inverter's monitoring/control entities.
2. Build the regression fixture from that **real registry** (not hand-invented):
   `python scripts/mock_ha/scenarios/from_debug_log.py docs/bess-debug-<ts>.md`,
   mirroring `core/bess/tests/unit/test_registry_discovery.py` and
   `test_scenario_discovery.py`.
3. Ensure the inverter's entities are captured by the debug export
   (`core/bess/debug_data_exporter.py`) so future reports include them.

- [ ] **Step 2: Verify referenced paths exist, then commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
for f in scripts/mock_ha/scenarios/from_debug_log.py \
  core/bess/tests/unit/test_registry_discovery.py \
  core/bess/tests/unit/test_scenario_discovery.py \
  core/bess/debug_data_exporter.py; do test -e "$f" && echo "OK $f" || echo "MISS $f"; done
git add .claude/skills/add-inverter-platform/SKILL.md
git commit -m "docs(skill): add-inverter-platform — validate against real config"
```
Expected: all `OK`.

---

## Task 3: Write the backend implementation checklist (controller + wiring + detection)

**Files:**
- Modify: `.claude/skills/add-inverter-platform/SKILL.md`

- [ ] **Step 1: Write the "Backend — controller" subsection**

Numbered steps. MUST name: create `core/bess/<inverter>_controller.py`
subclassing `InverterController` (`core/bess/inverter_controller.py`); list the
abstract methods to implement (`create_schedule`, `write_schedule_to_hardware`,
`compare_schedules`, `read_and_initialize_from_hardware`, `sync_soc_limits`,
`get_all_tou_segments`, `get_daily_TOU_settings`, `active_tou_intervals`,
`log_current_TOU_schedule`, `log_detailed_schedule`, `check_health`); say "model
on the closest existing controller by paradigm" and list the four
(`growatt_min_controller.py`, `growatt_sph_controller.py`,
`solax_modbus_growatt_controller.py`, `solax_controller.py`); enforce **no silent
fallbacks** (`docs/agents/rules.md`) — raise on missing entities.

- [ ] **Step 2: Write the "Backend — wiring" subsection**

MUST name: `core/bess/battery_system_manager.py` →
`_create_inverter_controller()` (add platform branch), `VALID_PLATFORMS` (L187),
`_INVERTER_TYPE_TO_PLATFORM` (L195); `backend/settings_store.py` →
`VALID_PLATFORMS` **(update BOTH definitions, L35 and L58 — note the
duplication)**, `SHARED_SENSOR_KEYS` if new shared keys.

- [ ] **Step 3: Write the "Backend — detection + sensor map" subsection**

MUST name, all in `core/bess/ha_api_controller.py`: add `<INVERTER>_SUFFIX_MAP`
(model on `GROWATT_MIN_SUFFIX_MAP` L428); add `_<INVERTER>_MARKER_SUFFIX` (model
on `_GROWATT_TOU_MARKER_SUFFIX` L2653); add the platform to `_INVERTER_PLATFORMS`
(L2600); add a branch in `detect_inverter_integrations()` (L2685) matching on
`unique_id` suffix; update `debug_data_exporter.py` so reports capture the new
entities.

- [ ] **Step 4: Verify every named symbol exists, then commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
grep -q "class InverterController" core/bess/inverter_controller.py && echo OK1
grep -q "_create_inverter_controller" core/bess/battery_system_manager.py && echo OK2
grep -q "GROWATT_MIN_SUFFIX_MAP" core/bess/ha_api_controller.py && echo OK3
grep -q "def detect_inverter_integrations" core/bess/ha_api_controller.py && echo OK4
grep -cn "^VALID_PLATFORMS" backend/settings_store.py   # expect 2
git add .claude/skills/add-inverter-platform/SKILL.md
git commit -m "docs(skill): add-inverter-platform — backend checklist"
```
Expected: OK1–OK4 print; `grep -c` reports 2.

---

## Task 4: Write the frontend + tests + E2E + docs checklist

**Files:**
- Modify: `.claude/skills/add-inverter-platform/SKILL.md`

- [ ] **Step 1: Write the "Frontend" subsection**

MUST name: `frontend/src/pages/SetupWizardPage.tsx` (option + auto-select + save
payload + summary), `frontend/src/pages/SettingsPage.tsx` (platform selector),
`frontend/src/components/settings/SensorConfigSection.tsx` +
`frontend/src/lib/sensorDefinitions.ts` (per-platform sensor definitions).

- [ ] **Step 2: Write the "Tests" subsection**

MUST name: new controller test modeled on `test_solax_controller.py` /
`test_growatt_tou_scheduling.py` / `test_solax_modbus_growatt_single_segment.py`
(by paradigm); add the platform's discovery case to `test_registry_discovery.py`
and `test_scenario_discovery.py` **using the real beta-tester registry fixture**.

- [ ] **Step 3: Write the "Frontend E2E" subsection**

MUST name: `scripts/mock_ha/scenarios/ci-wizard-<inverter>.json` (same fixture as
the discovery test); `e2e/tests/wizard-expectations.ts`;
`e2e/tests/setup-wizard.spec.ts`; `e2e/tests/inverter-page.spec.ts`;
`e2e/run-e2e.sh` `WIZARD_SCENARIOS`; `.github/workflows/ci.yml` per-scenario step.
Include the local verify command:
`cd e2e && BESS_PORT=8080 SCENARIO=ci-wizard-<inverter> npx playwright test --project=wizard`.

- [ ] **Step 4: Write the "Docs" subsection**

MUST name: `docs/INVERTER_PLATFORMS.md` (new "How BESS Controls" section +
"Required Entities" table + Auto-Detection entry), `README.md`, `CHANGELOG.md`,
and the maturity memory in `docs/agents/memory/` (mark **experimental / not
real-world tested** until a beta tester confirms).

- [ ] **Step 5: Verify named paths exist, then commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
for f in frontend/src/pages/SetupWizardPage.tsx \
  frontend/src/components/settings/SensorConfigSection.tsx \
  frontend/src/lib/sensorDefinitions.ts \
  e2e/tests/wizard-expectations.ts e2e/tests/setup-wizard.spec.ts \
  e2e/tests/inverter-page.spec.ts e2e/run-e2e.sh \
  docs/INVERTER_PLATFORMS.md; do test -e "$f" && echo "OK $f" || echo "MISS $f"; done
git add .claude/skills/add-inverter-platform/SKILL.md
git commit -m "docs(skill): add-inverter-platform — frontend, tests, E2E, docs"
```
Expected: all `OK`.

---

## Task 5: Write the gate + reference table

**Files:**
- Modify: `.claude/skills/add-inverter-platform/SKILL.md`

- [ ] **Step 1: Write the "Gate before commit / PR" section**

Mirror add-price-provider's gate verbatim where applicable:
```bash
pytest -m "not slow"                       # incl. discovery regression tests
black . && ruff check --fix .
cd frontend && npm run lint:fix && npm run build && npx tsc --noEmit
```
Then: open the PR as a **draft against `main`**, reference the originating issue,
mark the new platform **experimental / not real-world tested** until a beta tester
confirms (per `docs/agents/memory/` maturity conventions).

- [ ] **Step 2: Write the "Reference: files this skill touches" table**

A two-column table (Concern | File) covering every path in the verified
inventory above — controller ABC, the four model controllers, controller
factory, platform maps, settings, detection + suffix maps, debug export,
frontend settings + wizard, controller/discovery tests, mock-HA scenario,
frontend E2E, and user docs.

- [ ] **Step 3: Commit**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
git add .claude/skills/add-inverter-platform/SKILL.md
git commit -m "docs(skill): add-inverter-platform — gate + reference table"
```

---

## Task 6: Verification — structural parity + Solis #130 dry-run trace

**Files:**
- Modify (only if gaps found): `.claude/skills/add-inverter-platform/SKILL.md`

- [ ] **Step 1: Structural parity check vs `add-price-provider`**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
echo "=== inverter skill headings ==="; grep -nE "^#{1,3} " .claude/skills/add-inverter-platform/SKILL.md
echo "=== provider skill headings ==="; git show feature/entsoe-belpex-price-source:.claude/skills/add-price-provider/SKILL.md | grep -nE "^#{1,3} "
```
Confirm the inverter skill has the analogous blocks: discovery/control rule,
validate-against-real-config, implementation checklist (backend → frontend →
tests → E2E → docs), gate, reference table. Fix any missing block inline.

- [ ] **Step 2: Reference-accuracy scan (no dangling files/symbols)**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
grep -oE '`[a-zA-Z0-9_./-]+\.(py|tsx|ts|json|md|sh|yml)`' \
  .claude/skills/add-inverter-platform/SKILL.md | tr -d '`' | sort -u | \
  while read -r f; do test -e "$f" || echo "MISSING: $f"; done
```
Expected: no `MISSING:` lines (paths with a `<inverter>` placeholder are fine —
exclude those manually).

- [ ] **Step 3: Dry-run trace against Solis S6 (#130)**

Walk the skill top-to-bottom as if integrating the Solis S6-EH3P10K from #130.
For each checklist item, write one line naming the concrete file/symbol you would
touch and what you would put there. Confirm:
- The discovery/control-paradigm step tells you how to find the Solis HA
  integration and classify its control method (or fall back to monitoring-only).
- No step is ambiguous or missing a file path.
Record the trace as a scratch note (not committed). If any step can't be traced,
fix the skill inline and re-run Steps 1–2.

- [ ] **Step 4: Final commit if any fixes were made**

```bash
cd /Users/johanzander/GitHub/bess-manager-inverter-integration
git add -A && git commit -m "docs(skill): add-inverter-platform — fixes from verification" || echo "no changes"
```

- [ ] **Step 5: Report Stage A complete**

State that `.claude/skills/add-inverter-platform/SKILL.md` exists, mirrors
`add-price-provider`, names only real files/symbols, and traces cleanly against
Solis #130 — ready for Stage B (land skills on `main`) and the D3 manual Solis run.

---

## Self-Review (completed during planning)

- **Spec coverage:** This plan implements **Stage A only** (the spec's first
  stage). Stages B–D are intentionally out of scope per the staged rollout and
  the D3 decision (prove the skill manually before automating).
- **Placeholder scan:** `<inverter>` / `<id>` / `<ts>` are deliberate skill
  template placeholders, not plan gaps; every concrete repo path is named.
- **Type/symbol consistency:** All Python symbols (`InverterController`,
  `_create_inverter_controller`, `VALID_PLATFORMS`, `_INVERTER_TYPE_TO_PLATFORM`,
  `GROWATT_MIN_SUFFIX_MAP`, `_GROWATT_TOU_MARKER_SUFFIX`, `_INVERTER_PLATFORMS`,
  `detect_inverter_integrations`) and file paths were grep-verified on
  `feat/inverter-integration` before writing this plan.
