# Add Price Provider Skill

Add support for a new Home Assistant electricity-price integration as a BESS
price provider (e.g. Nordpool, Octopus, ENTSO-e/Belpex). This is a recurring
pattern — every new provider touches the same files in the same order. Follow
the steps exactly; **never guess entity names, `unique_id` formats, or
attribute keys** (see `CLAUDE.md` → "Verification Before Action").

## The non-negotiable discovery rule

Entity discovery in this codebase keys off the **immutable `unique_id`** from
the HA entity registry, filtered by the integration's `platform` field — this
survives entity renaming (`ha_api_controller.py` → `discover_octopus_entities`).
You MUST derive the real `unique_id` pattern from the **integration's source
code**, not from a sample entity_id and not from inference:

1. Find the integration's GitHub repo (`gh api "search/repositories?q=..."`).
2. Read `custom_components/<domain>/sensor.py` (and `const.py`, `coordinator.py`).
   Locate `DOMAIN` (= the registry `platform`), the `_attr_unique_id`
   construction, and the `extra_state_attributes` that expose the price arrays.
   Quote the exact lines in the PR description / code comments.
3. Note the **price resolution** (hourly = 24/day, 30-min = 48, quarterly = 96)
   and whether prices are **VAT-inclusive retail** or **VAT-exclusive spot** —
   these drive `period_duration_hours` / expansion and `prices_are_final`.

## Validate against a real beta-tester config

We have beta testers who export their config + entity registry. The flow:

1. Ask the beta tester to export config / provide a debug report
   (`docs/bess-debug-*.md`) containing their real entity registry + the price
   sensor's attributes.
2. Build a **regression test fixture** from that real registry (not a
   hand-invented one) so discovery is verified against production data and
   cannot regress. Mirror `core/bess/tests/unit/test_registry_discovery.py`
   and `test_scenario_discovery.py`.
3. Add the price sensor (and its `prices_today`/equivalent attribute) to the
   **debug export** so future reports capture it
   (`core/bess/debug_data_exporter.py` + `debug_report_formatter.py`).

## Implementation checklist (in order)

### Backend — price source
1. **New `core/bess/<provider>_source.py`** — subclass `PriceSource`
   (`core/bess/price_manager.py`). Model on the closest existing source:
   - Reads HA sensor **attributes** → model on `HomeAssistantSource` (Nordpool HACS).
   - Reads HA **event entities** with separate import/export → model on
     `OctopusEnergySource`.
   Implement: `get_prices_for_date`, `perform_health_check`, and as needed
   `get_sell_prices_for_date`, `prices_are_final`, `period_duration_hours`.
   - Expand raw resolution to the system-wide **96 quarterly periods** (size the
     expansion from the **actual count** + `time_utils.get_period_count` for
     DST, as `OctopusEnergySource._fetch_rates` does — don't hardcode 24/48).
   - Return **VAT-exclusive** prices if the source is spot (PriceManager applies
     markup/VAT); set `prices_are_final = True` only for final retail prices.
   - **No silent fallbacks** — raise `PriceDataUnavailableError` on missing data
     (`docs/agents/rules.md`).

### Backend — wiring
2. **`core/bess/battery_system_manager.py`** → `_create_price_source()`: add a
   `provider == "<provider>"` branch reading `config["<provider>"]`.
3. **`backend/settings_store.py`** → add `"<provider>": {}` to the
   `energy_provider` default block. Add a `_migrate_schema` clause only if
   renaming/moving keys.
4. **`backend/api.py`** → setup endpoint (`run_setup_discovery` persistence,
   ~line 3001): persist the new entity when `payload.provider == "<provider>"`.
   The live-apply path (`update_settings({"energy_provider": ...})`) already
   re-creates the source, so no restart is needed.
5. **`backend/api_dataclasses.py`** → add the `<provider>Entity` field(s) to the
   setup payload dataclass.

### Backend — discovery + debug export
6. **`core/bess/ha_api_controller.py`** → `discover_integrations()`: set
   `<provider>_found` + entity by filtering entity registry on
   `platform == "<domain>"` and matching the verified `unique_id` pattern.
   Add an **attribute-shape fallback** (scan `/api/states` for the price-array
   attribute) for robustness across integration versions. Surface results in the
   discovery result dict consumed by the wizard.
7. **`core/bess/debug_data_exporter.py`** → include the new provider entity +
   price attributes in the export so beta reports capture them.

### Frontend
8. **`frontend/src/components/settings/PricingFormSection.tsx`** — add the
   provider option to the `Provider` select + conditional entity input(s).
9. **`frontend/src/pages/SetupWizardPage.tsx`** — add to form state, auto-select
   on discovery, include in the save payload + the summary screen.

### Tests (all must pass before commit)
10. **`core/bess/tests/unit/test_<provider>_source.py`** — resolution expansion,
    VAT handling, date filtering, DST counts, missing-data failure.
11. **Discovery regression test** — add a `<provider>` case to
    `test_registry_discovery.py` / `test_scenario_discovery.py` **using the real
    beta-tester registry fixture**.
12. **`backend/tests/test_settings_contracts.py`** + setup-wizard scenario test
    (`backend/tests/test_setup_wizard_scenarios.py`) for the new provider key.

### Frontend E2E (Playwright wizard — don't skip this)

The discovery regression test above is backend-only. The **full frontend flow**
(auto-select provider, show provider-specific fields, complete + save) is
covered by the Playwright wizard E2E, parameterised by the `SCENARIO` env var.
Wire the new provider in:
13a. **`scripts/mock_ha/scenarios/ci-wizard-<provider>.json`** — the mock-HA
    scenario (already created as the regression fixture above; the same file
    drives both the backend discovery test and this E2E).
13b. **`e2e/tests/wizard-expectations.ts`** — add a `ci-wizard-<provider>`
    expectation and extend the `autoSelectedProvider` union.
13c. **`e2e/tests/setup-wizard.spec.ts`** — add the provider's radio label to
    `PROVIDER_LABEL` and a branch in "provider-specific fields shown correctly".
13d. **`e2e/run-e2e.sh`** `WIZARD_SCENARIOS` **and** `.github/workflows/ci.yml`
    (per-scenario step) — run `SCENARIO=ci-wizard-<provider>`.
    Verify locally: bring up `docker-compose.ci.yml` with the scenario, confirm
    `POST /api/setup/discover` reports the provider, then
    `cd e2e && BESS_PORT=8080 SCENARIO=ci-wizard-<provider> npx playwright test --project=wizard`.

### Docs
14. **`docs/USER_GUIDE.md`** — add a "Provider: <name>" subsection (prereqs,
    entity, how it works) alongside the existing provider sections (~line 258).
15. **`README.md`** — add the provider to the supported-providers list (~line 56).
16. **`CHANGELOG.md`** — add an entry (project rule: never skip).

## Gate before commit / PR

```bash
pytest -m "not slow"                       # incl. discovery regression tests
black . && ruff check --fix .
cd frontend && npm run lint:fix && npm run build && npx tsc --noEmit
```

Open the PR as a **draft against `main`**, reference the originating issue, and
mark new providers **experimental / not real-world tested** until a beta tester
confirms (per `docs/agents/memory/` maturity conventions).

## Reference: files this skill touches

| Concern | File |
|---------|------|
| Source ABC | `core/bess/price_manager.py` (`PriceSource`) |
| Example: attribute-based | `core/bess/price_manager.py` (`HomeAssistantSource`) |
| Example: event-entity / expansion | `core/bess/octopus_energy_source.py` |
| Example: service-call | `core/bess/official_nordpool_source.py` |
| Provider switch | `core/bess/battery_system_manager.py` (`_create_price_source`) |
| Settings default + migration | `backend/settings_store.py` |
| Setup API persistence | `backend/api.py` |
| Setup payload | `backend/api_dataclasses.py` |
| Discovery | `core/bess/ha_api_controller.py` (`discover_integrations`, `discover_octopus_entities`) |
| Debug export | `core/bess/debug_data_exporter.py`, `debug_report_formatter.py` |
| Frontend settings | `frontend/src/components/settings/PricingFormSection.tsx` |
| Frontend wizard | `frontend/src/pages/SetupWizardPage.tsx` |
| Discovery tests | `core/bess/tests/unit/test_registry_discovery.py`, `test_scenario_discovery.py` |
| Settings tests | `backend/tests/test_settings_contracts.py`, `test_setup_wizard_scenarios.py` |
| Mock-HA scenario | `scripts/mock_ha/scenarios/ci-wizard-<provider>.json` |
| Frontend E2E | `e2e/tests/wizard-expectations.ts`, `e2e/tests/setup-wizard.spec.ts`, `e2e/run-e2e.sh`, `.github/workflows/ci.yml` |
| User docs | `docs/USER_GUIDE.md`, `README.md`, `CHANGELOG.md` |
