# Add Inverter Platform Skill

Add support for a new inverter hardware family and its Home Assistant
integration as a BESS **inverter platform** (e.g. Growatt MIN, Growatt SPH,
SolaX VPP, and new families such as Solis). This is a recurring pattern — every
new platform touches the same files in the same order. Follow the steps exactly;
**never guess entity names, `unique_id` formats, control service names, or
attribute keys** (see `CLAUDE.md` → "Verification Before Action"). This is the
inverter counterpart of the `add-price-provider` skill; the generic
`feature-lifecycle` skill orchestrates either one through the full
experimental→stable lifecycle.

## This skill in the lifecycle

This is the **Stage 1 implementation** skill. It produces a working
implementation + a **source-derived** regression fixture and ships it
experimental. It does **not** own what comes after — and you will be
**re-invoked** across those stages:

- **User reports an issue → fix → re-ship.** Expected and normal. The
  fix/iterate/release loop is `feature-lifecycle` **Stage 2 & 4**: a bug found
  against a real config loops back here for a minimal fix; fixes are **batched**
  into a single consolidated beta (not one release per fix). Don't treat the
  first pass as final.
- **Locking the real user config into the regression suite** is
  `feature-lifecycle` **Stage 3** (after the user's debug log arrives) — see
  "Regression fixtures" below.
- **Graduation** (strip the `experimental` marker, promote to stable) is
  `feature-lifecycle` **Stage 6**.

The `release` skill owns beta/prod deploys. This skill owns only the code +
tests + docs for one implementation pass.

## The non-negotiable discovery + control rule

A new inverter platform has **two** halves that must both be derived from the
integration's real source, never inferred from a sample entity:

### 1. Place the inverter on the two control axes (do this first)

**Before anything else**, locate the new inverter on the **two orthogonal axes**
in `docs/INVERTER_PLATFORMS.md` → **"Inverter Integration Patterns"**:

- **Transport** — how commands reach it: **TX-Cloud** (`growatt_server` service
  calls), **TX-Modbus** (`solax_modbus`, multi-brand entity writes — SolaX,
  Solis, Growatt, Sofar…), **TX-Vendor-service** (e.g. `huawei_solar`), or a new
  transport.
- **Scheduling model** — how a plan is expressed: **SM-TOU-numbered**,
  **SM-Period-lists**, **SM-Mode-slots**, or **SM-Ephemeral** (duration-bounded,
  auto-expiring).

The (transport × scheduling-model) coordinate tells you **which existing
controller to model on**, the **detection marker**, and the **suffix-map shape**,
and how much is new:

- **Existing transport + existing model** (e.g. Solis on TX-Modbus) → purely
  **additive**: new controller subclass + suffix map + a detection branch. No ABC
  change.
- **New transport** (e.g. Huawei `huawei_solar`) → additive too, but adds a new
  integration branch in detection and a new service/command helper in
  `ha_api_controller.py`.
- **New transport AND new scheduling model** → the expensive case; confirm with
  the maintainer. The safe interim is always **monitoring-only** (see §3 below).

Do not start writing a controller until the inverter is placed on both axes. Add
its coordinate row to the catalog in `docs/INVERTER_PLATFORMS.md` as you go.

### 2. Discovery keys off the immutable `unique_id`

Inverter discovery keys off the **immutable `unique_id`** from the HA entity
registry, filtered by the integration's `platform` (domain) field — this
survives entity renaming (`core/bess/ha_api_controller.py` →
`detect_inverter_integrations`). You MUST derive the real `unique_id` pattern
from the **integration's source code**, not from a sample `entity_id` and not
from inference:

1. Find the integration's GitHub repo (`gh api "search/repositories?q=..."`).
2. Read `custom_components/<domain>/sensor.py` / `number.py` / `select.py` /
   `button.py` (and `const.py`, `coordinator.py`). Locate `DOMAIN` (= the
   registry `platform`), the `_attr_unique_id` construction, and the entity
   `key`/`name` for each monitoring and control entity. Quote the exact lines in
   the PR description / code comments.
3. Note the **entity-id vs unique_id** divergence (display `name` drives
   `entity_id`, internal `key` drives `unique_id`) — BESS matches on `unique_id`.
   See the Growatt TOU note in `docs/INVERTER_PLATFORMS.md`.

### 3. Monitoring-only is a valid first cut

If the integration exposes monitoring entities but no usable control path,
implement **monitoring + detection only** and mark schedule control "not yet
implemented" — this is an existing, accepted state (precedent: Growatt GEN3 in
`docs/INVERTER_PLATFORMS.md` → "Schedule control requires a dedicated controller
(not yet implemented)"). Make this branch explicit in the PR. Never fake a
control path; **no silent fallbacks** (`docs/agents/rules.md`).

## Implementation checklist (in order)

### Backend — controller
1. **New `core/bess/<inverter>_controller.py`** — subclass `InverterController`
   (`core/bess/inverter_controller.py`). Model on the closest existing
   controller for your paradigm (see the table above). Implement the abstract
   methods:
   - `create_schedule`, `write_schedule_to_hardware`, `compare_schedules`
   - `read_and_initialize_from_hardware`, `sync_soc_limits`
   - `active_tou_intervals`, `get_all_tou_segments`, `get_daily_TOU_settings`
   - `log_current_TOU_schedule`, `log_detailed_schedule`, `check_health`
   - **No silent fallbacks** — raise on missing entities/services
     (`docs/agents/rules.md`). For monitoring-only, raise a clear
     "control not implemented" error from the write path.

### Backend — wiring
2. **`core/bess/battery_system_manager.py`**:
   - `_create_inverter_controller()` (~line 235) — add a
     `self.inverter_platform == "<platform_id>"` branch returning the new
     controller.
   - `VALID_PLATFORMS` ClassVar (line 187) — add `"<platform_id>"`.
   - `_INVERTER_TYPE_TO_PLATFORM` (line 195) — add `"<platform_id>": "<platform_id>"`
     plus any legacy alias.
3. **`backend/settings_store.py`** → `VALID_PLATFORMS` — **defined twice
   (lines 35 and 58); update BOTH occurrences.** (Known wart — the tuple is
   duplicated.) Add new keys to `SHARED_SENSOR_KEYS` only if they are platform-
   independent.

### Backend — detection + sensor map
4. **`core/bess/ha_api_controller.py`**:
   - Add `<INVERTER>_SUFFIX_MAP` ClassVar (entity suffix → BESS sensor key) —
     model on `GROWATT_MIN_SUFFIX_MAP` (line 428) / `SOLAX_NATIVE_SUFFIX_MAP`
     (line 653). Sizes/keys come from the **verified** unique_id suffixes.
   - Add a `_<INVERTER>_MARKER_SUFFIX` ClassVar — model on
     `_GROWATT_TOU_MARKER_SUFFIX` (line 2653) — a suffix unique to this platform
     used to disambiguate detection.
   - Add the platform → integration domains entry to `_INVERTER_PLATFORMS`
     (line 2600).
   - Add a detection branch in `detect_inverter_integrations()` (line 2685) /
     `_detect_platforms()` matching on the **`unique_id`** marker suffix, and a
     branch that selects `<INVERTER>_SUFFIX_MAP` in the per-platform sensor
     resolution (the block around lines 2765–2802).
5. **`core/bess/debug_data_exporter.py`** — include the new inverter's entities
   so beta debug reports capture them.

### Frontend
6. **`frontend/src/pages/SetupWizardPage.tsx`** — add the platform to form state,
   auto-select on discovery, include in the save payload + the summary screen.
7. **`frontend/src/pages/SettingsPage.tsx`** — add the platform to the inverter
   platform selector (Integrations & Sensors → Inverter Platform).
8. **`frontend/src/components/settings/SensorConfigSection.tsx`** and
   **`frontend/src/lib/sensorDefinitions.ts`** — add the per-platform sensor
   definitions (which BESS sensor keys this platform requires).

### Tests (all must pass before commit)
9. **`core/bess/tests/unit/test_<inverter>_controller.py`** — controller
   behaviour (schedule build, write path, SOC sync, missing-entity failure).
   Model on the closest existing controller test:
   `test_solax_controller.py`, `test_growatt_tou_scheduling.py`, or
   `test_solax_modbus_growatt_single_segment.py` (pick by paradigm).
10. **Discovery regression test** — add a `<platform>` case to
    `core/bess/tests/unit/test_registry_discovery.py` and
    `test_scenario_discovery.py`. Use a **source-derived** fixture now (built from
    the integration's verified `unique_id` shapes); the **real** beta-tester
    registry replaces/augments it later — see "Regression fixtures" below.

### Frontend E2E (Playwright wizard — don't skip this)

The discovery regression test above is backend-only. The **full frontend flow**
(auto-select platform, show platform-specific sensors, complete + save) is
covered by the Playwright wizard E2E, parameterised by the `SCENARIO` env var:
11a. **`scripts/mock_ha/scenarios/ci-wizard-<inverter>.json`** — the mock-HA
    scenario (the same file created as the regression fixture above drives both
    the backend discovery test and this E2E). Existing inverter scenarios to
    model on: `ci-wizard-growatt-modbus.json`,
    `ci-wizard-growatt-modbus-gen3.json`, `ci-wizard-nordpool-solax.json`,
    `ci-wizard-nordpool-sph.json`.
11b. **`e2e/tests/wizard-expectations.ts`** — add a `ci-wizard-<inverter>`
    expectation (auto-selected platform, expected sensors).
11c. **`e2e/tests/setup-wizard.spec.ts`** — add the platform branch; if the
    inverter page surfaces it, also **`e2e/tests/inverter-page.spec.ts`**.
11d. **`e2e/run-e2e.sh`** `WIZARD_SCENARIOS` **and** `.github/workflows/ci.yml`
    (per-scenario step) — run `SCENARIO=ci-wizard-<inverter>`.
    Verify locally: bring up `docker-compose.ci.yml` with the scenario, confirm
    `POST /api/setup/discover` reports the platform, then
    `cd e2e && BESS_PORT=8080 SCENARIO=ci-wizard-<inverter> npx playwright test --project=wizard`.

### Docs
12. **`docs/INVERTER_PLATFORMS.md`** — add a "How BESS Controls" section for the
    new platform, a "Required Entities" table (BESS sensor key → entity type →
    integration suffix), and an "Auto-Detection" entry. This is the canonical
    per-platform reference.
13. **`README.md`** — add the inverter to the supported-platforms list.
14. **`CHANGELOG.md`** — add an entry (project rule: never skip).
15. **Maturity memory** (`docs/agents/memory/`) — mark the platform
    **experimental / not real-world tested** until a beta tester confirms.

## Regression fixtures: source-derived now, real-config later

Validation happens in **two phases** — you do **not** wait for a real user config
to implement, and you do **not** claim real-world validation until the user
confirms.

**Phase 1 — now (this skill, Stage 1).** With no real registry yet (the user
typically hasn't installed), build a **source-derived** fixture from the
integration's **verified** `unique_id`/attribute shapes (the ones you read from
the integration source per the discovery rule). This drives the discovery
regression test and the wizard E2E so the implementation can ship experimental.
*(If the issue already contains the user's real entity IDs — as some do — use
those directly and you have effectively done Phase 2 early.)*

**Phase 2 — when the beta log arrives (`feature-lifecycle` Stage 2–3).** The user
installs the experimental build and exports a debug report
(`docs/bess-debug-*.md`) with their real registry + the inverter's monitoring
**and** control entities. Then:

1. Build the **real** fixture from that registry (not hand-invented):
   ```
   python scripts/mock_ha/scenarios/from_debug_log.py docs/bess-debug-<ts>.md
   ```
   and replace/augment the Phase-1 fixture in
   `core/bess/tests/unit/test_registry_discovery.py` /
   `test_scenario_discovery.py`.
2. Ensure the inverter's entities are captured by the **debug export**
   (`core/bess/debug_data_exporter.py`) so future reports include them.
3. Any bug surfaced by the real config loops back through this skill for a
   minimal fix, batched into a consolidated beta (lifecycle Stage 4).

## Gate before commit / PR

```bash
pytest -m "not slow"                       # incl. discovery regression tests
black . && ruff check --fix .
cd frontend && npm run lint:fix && npm run build && npx tsc --noEmit
```

Open the PR as a **draft against `main`**, reference the originating issue, and
mark the new platform **experimental / not real-world tested** until a beta
tester confirms (per `docs/agents/memory/` maturity conventions).

## Reference: files this skill touches

| Concern | File |
|---------|------|
| Controller ABC | `core/bess/inverter_controller.py` (`InverterController`) |
| Model: numbered TOU (cloud) | `core/bess/growatt_min_controller.py` (`GrowattMinController`) |
| Model: charge/discharge period lists | `core/bess/growatt_sph_controller.py` (`GrowattSphController`) |
| Model: local-Modbus TOU slots | `core/bess/solax_modbus_growatt_controller.py` (`SolaxModbusGrowattController`) |
| Model: ephemeral VPP commands | `core/bess/solax_controller.py` (`SolaxController`) |
| Controller factory + platform maps | `core/bess/battery_system_manager.py` (`_create_inverter_controller`, `VALID_PLATFORMS`, `_INVERTER_TYPE_TO_PLATFORM`, `switch_inverter_platform`) |
| Settings platform list (×2) | `backend/settings_store.py` (`VALID_PLATFORMS` at L35 and L58, `SHARED_SENSOR_KEYS`) |
| Detection + sensor suffix maps | `core/bess/ha_api_controller.py` (`*_SUFFIX_MAP`, `_*_MARKER_SUFFIX`, `_INVERTER_PLATFORMS`, `detect_inverter_integrations`) |
| Debug export | `core/bess/debug_data_exporter.py` |
| Frontend wizard | `frontend/src/pages/SetupWizardPage.tsx` |
| Frontend settings | `frontend/src/pages/SettingsPage.tsx`, `frontend/src/components/settings/SensorConfigSection.tsx`, `frontend/src/lib/sensorDefinitions.ts` |
| Controller tests | `core/bess/tests/unit/test_solax_controller.py`, `test_growatt_tou_scheduling.py`, `test_solax_modbus_growatt_single_segment.py` |
| Discovery tests | `core/bess/tests/unit/test_registry_discovery.py`, `test_scenario_discovery.py` |
| Debug log → scenario | `scripts/mock_ha/scenarios/from_debug_log.py` |
| Mock-HA scenario | `scripts/mock_ha/scenarios/ci-wizard-<inverter>.json` |
| Frontend E2E | `e2e/tests/wizard-expectations.ts`, `e2e/tests/setup-wizard.spec.ts`, `e2e/tests/inverter-page.spec.ts`, `e2e/run-e2e.sh`, `.github/workflows/ci.yml` |
| User docs | `docs/INVERTER_PLATFORMS.md`, `README.md`, `CHANGELOG.md` |
| Maturity record | `docs/agents/memory/` |
