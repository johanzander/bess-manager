# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [9.0.0b26] - 2026-05-31

### Fixed

- **CI required checks skip when no relevant files changed** — GitHub Actions jobs with job-level `if: false` report "skipped" which doesn't satisfy required status checks, blocking PR merge. Moved conditions to step-level so Fast tests, Frontend checks, and E2E jobs always run and report success.

## [9.0.0b25] - 2026-05-31

### Fixed

- **Grid charge control broken on solax_modbus** — `set_grid_charge()` called `switch.turn_on/turn_off` which silently did nothing on `select` entities (solax_modbus uses `select.allow_grid_charge`). `grid_charge_enabled()` checked `state == "on"` but select entities use `"Enabled"`/`"Disabled"`, so it always returned False. Now detects entity domain and uses the correct HA service and state values.
- **Debug report always shows "Overall Status: UNKNOWN"** — `_format_health_status()` read `overall_status`, `critical_count`, etc. from the health check dict, but `run_system_health_checks()` never included those keys. Now derives status summary from the component checks array.

### Changed

- **Positive detection for solax_modbus_native platform** — replaced the fallback-based detection ("not Growatt TOU, not GEN3, therefore native SolaX") with a positive VPP marker check (`remotecontrol_power_control` suffix). Only platforms that can be positively identified are reported.
- **Debug report discovery shows detected_platforms** — the "Resolved by BESS" section now includes `detected_platforms` (all positively identified platforms) alongside the legacy `growatt_inverter_type`, so it's clear what was detected vs what the user selected.
- **CI skipped tests when non-code files changed** — `predicate-quantifier: 'every'` in paths-filter required ALL changed files to match, so PRs with `.claude/` or `CHANGELOG.md` changes alongside `core/bess/` changes skipped backend/frontend/E2E tests. Removed to use default `'some'` (trigger if ANY file matches).

## [9.0.0b24] - 2026-05-30

### Fixed

- **Wizard fails to detect Nordpool price area** — bare tuple unpacking in `_parse_ha_metadata` crashed on HA devices with non-2-element identifiers (`too many values to unpack`), silently losing nordpool_area, growatt_device_id, and all other WS-derived metadata. Now uses safe iteration with length checks.
- **Sensor discovery fails for non-default solax_modbus device names** — suffix maps hardcoded `solax_` prefix (e.g. `solax_battery_soc`) which only matched users who named their device "solax". The prefix is user-configurable (`CONF_NAME` in solax_modbus). Maps now use only the fixed register key (e.g. `battery_soc`), matching any device name via `endswith()`.

### Changed

- **Return `detected_platforms` list from discovery** — backend no longer silently auto-selects `inverter_type` when multiple platforms are detected. Returns all detected platforms; frontend picks the first. `inverter_type` is only set when exactly one platform is found.
- **Add diagnostic logging to discovery endpoint** — logs nordpool_area, currency, config_entry_id after `discover_integrations()` for easier debugging.

## [9.0.0b23] - 2026-05-30

### Fixed

- **Dashboard hangs after wizard when using `influxdb_7d_avg` strategy** — `_get_influxdb_7d_avg_forecast()` read `local_load_power` from a stale startup options dict (`_addon_options`) that was never updated when the wizard saved sensors. The schedule build failed every cycle, leaving the dashboard stuck in "initializing" state forever. Now reads from the live `controller.sensors` dict.

### Changed

- **Remove `_addon_options` from BatterySystemManager** — eliminated a stale startup snapshot dict that duplicated state already owned by `controller.sensors`, `inverter_platform`, and the settings dataclasses. Inverter platform resolution extracted into `_resolve_initial_platform()` static method. Debug exporter now reads from the settings store instead.
- **Pass `BESS_VERSION` to Docker container** — `BUILD_VERSION` build arg is now set as `BESS_VERSION` env var so the running container can report its version.

## [9.0.0b22] - 2026-05-29

### Fixed

- **Runtime failure banners not showing under HA ingress** — `useRuntimeFailures` hook used raw `fetch()` instead of the `api` axios instance, so requests missed the ingress base URL prefix and silently failed. Banners now appear when battery control errors occur.
- **Algorithm tests triggering on every PR** — `dorny/paths-filter` with default `predicate-quantifier: some` caused negation patterns (e.g. `!core/bess/ha_api_controller.py`) to match all non-excluded files, including unrelated frontend files. Set `predicate-quantifier: every` so files must match all patterns.

## [9.0.0b21] - 2026-05-29

### Changed

- **Per-platform sensor storage** — sensor configuration is now stored per-platform (like `energy_provider`), so switching platforms preserves previously entered sensor values instead of discarding them.
- **Split entity suffix maps** — `SOLAX_ENTITY_SUFFIX_MAP` split into 3 per-platform maps (`GROWATT_CLOUD_SUFFIX_MAP`, `GROWATT_MODBUS_SUFFIX_MAP`, `SOLAX_NATIVE_SUFFIX_MAP`), fixing the `total_yield` suffix collision between native SolaX (production) and GEN4 Growatt (load consumption).
- **Tabs UI for platform selection** — wizard platform selector now uses tabs with pill buttons instead of radio buttons, with sensors rendered inline within tab content.

## [9.0.0b20] - 2026-05-27

### Fixed

- **Intent classification used flawed heuristic** — `classify_strategic_intent()` and `infer_intent_from_flows()` compared `grid_imported` vs `home_consumption` to distinguish GRID_CHARGING from SOLAR_STORAGE. This misclassified periods as SOLAR_STORAGE when solar partially covered home load but the battery charged entirely from grid. Now checks `grid_to_battery > 0.01` which directly maps to the hardware question: does `grid_charge` need to be ON?

## [9.0.0b19] - 2026-05-26

### Fixed

- **Export power sensor mismatch** — SolaX entity suffix map now uses full `solax_` prefixed suffixes (e.g. `solax_grid_export` instead of `grid_export`) to prevent ambiguous `endswith` matching. Previously `grid_export` matched the `select.limit_grid_export` config entity instead of the actual export power sensor.
- **SE4 hardcoded as default area** — `DEFAULT_AREA` changed from `"SE4"` to `""` so non-Swedish users aren't silently assigned a wrong price area.
- **WebSocket double-connection in discovery** — `discover_integrations()` now sends all three WS queries (entity registry, config entries, device registry) over a single connection. Previously the second connection could fail during HA startup, silently losing `nordpool_config_entry_id` and area.
- **Energy balance ignored battery flows** — derived `load_consumption` formula corrected from `solar + import - export` to `solar + import + battery_out - battery_in - export` for platforms lacking a native load register.
- **Stale empty InfluxDB cache** — empty batch cache for today is now invalidated on the next check so transient InfluxDB failures don't permanently return zero values.
- **Removed `_reconcile_discovered_config()` workaround** — band-aid removed now that root causes (WebSocket race, suffix ambiguity) are fixed.
- **Inverter command failures now visible in dashboard** — `GrowattSphController.write_schedule_to_hardware()` and `InverterController._write_period_to_hardware()` now record failures to `RuntimeFailureTracker`, surfacing them in the dashboard banner instead of only in logs.

### Changed

- **CI algorithm test filter** — switched from brittle allowlist to exclusion-based pattern (`core/bess/**` minus I/O-only files). New files trigger the suite by default; only explicitly excluded I/O files skip it.
- **Removed WebSocket fallback in discovery** — if the single WS connection fails, the error propagates instead of silently producing incomplete configuration.
- **E2E wizard settings** — `ci-wizard-settings.json` now contains a full Nordpool + Growatt MIN fixture instead of empty `{}`.

## [9.0.0b18] - 2026-05-25

### Fixed

- **Sensor discovery used hallucinated unique_id suffixes** — verified all SOLAX_ENTITY_SUFFIX_MAP entries against the real `wills106/homeassistant-solax-modbus` plugin_growatt.py source code and real user debug logs. Removed `total_import_power`, `total_export_power`, `total_load_energy` (don't exist in the integration); added correct suffixes `ac_power_to_user`/`ac_power_to_grid` (GEN3), `pv_power_total` (all generations), `total_power_generation` (GEN4 system production).
- **`total_yield` mapped to wrong BESS key** — was `lifetime_system_production` but register 3077 is actually "Total Load Energy" (confirmed from integration source and Niklas's debug log showing `unique_id_suffix: solax_total_yield` on entity named "Total Load Energy"). Now correctly maps to `lifetime_load_consumption`. Added `total_power_generation` (register 3051) for `lifetime_system_production`.
- **Discovery could map to disabled entities** — `_map_registry_entities` now prefers enabled entities; only falls back to disabled ones (with a warning log) when no enabled match exists. Fixes PV power discovery mapping to the disabled `total_pv_power` entity instead of the enabled `pv_power_total`.
- **Fixed comments** — `total_forward_power`/`total_reverse_power` are GEN4 (register 3041/3043), not "GEN2/3" as previously documented.

## [9.0.0b17] - 2026-05-24

### Fixed

- **TOU entity auto-discovery for dual-platform installations** — when both Growatt Cloud and SolaX Modbus integrations are present, discovery now correctly prefers the modbus platform (which provides TOU control entities). Previously, the cloud platform was auto-selected, causing TOU entities to be missing from the wizard.
- **Hardware write retry** — when `write_schedule_to_hardware` fails (e.g. Modbus timeout, missing entity mappings), the system now retries the write on the next quarterly cycle instead of silently running with stale inverter settings.

### Changed

- **Platform identifiers renamed** — all inverter platform strings now follow a consistent `<plugin>_<inverter>` convention used at every layer (backend, frontend, API, discovery):
  - `growatt_min` → `growatt_server_min`
  - `growatt_sph` → `growatt_server_sph`
  - `growatt_solax_modbus` → `solax_modbus_growatt_min`
  - `growatt_solax_modbus_gen3` → `solax_modbus_growatt_sph`
  - `solax` → `solax_modbus_native`
- **Controller file renamed** — `growatt_solax_modbus_controller.py` → `solax_modbus_growatt_controller.py`
- **Mock server simplified** — only accepts the 5 canonical platform names, no legacy aliases

## [9.0.0b16] - 2026-05-24

### Fixed

- **SOLAR_STORAGE batt_mode mapping** — `_calculate_hourly_settings()` mapped SOLAR_STORAGE to `battery_first` instead of `load_first`, disagreeing with `INTENT_TO_MODE`. Moot because the entire hourly settings abstraction was dead code (API uses period-level settings), so removed it entirely.
- **Double entity registry fetch** — `discover_integrations` fetched the entity registry via `fetch_entity_registry()`, then `discover_ha_metadata()` fetched it again via WebSocket. Now passes the already-fetched registry, saving one full WS round-trip.
- **Unused `get_services` WebSocket query** — `discover_ha_metadata` queried HA for all service definitions but never used the result. Removed.

### Changed

- **Dead code removed** — deleted 3 uncalled methods from `GrowattMinController` (`_calculate_power_rates_from_action`, `_strategic_intent_to_battery_mode`, `_consolidate_and_convert_fallback`) and the unused `_calculate_hourly_settings` / `get_hourly_settings` / `hourly_settings` abstraction from `InverterController`.
- **Duplicate overrides removed** — `get_strategic_intent_summary()`, `_get_intent_description()`, `INTENT_TO_MODE`, `log_detailed_schedule()`, and `_write_period_to_hardware()` were overridden with identical implementations in subclasses. Removed overrides; `_write_period_to_hardware` promoted from abstract to concrete default on `InverterController`.

## [9.0.0b15] - 2026-05-23

### Fixed

- **TOU schedule entities not saved to config** — setup wizard filtered out `tou_time_1_*` sensor keys because they weren't in the frontend `INTEGRATIONS` definition. The Growatt Modbus (GEN4) controller then failed at schedule application with "No entity ID configured for sensor 'tou_time_1_enabled'". TOU Schedule sensor group now included in the wizard UI.
- **TOU health check added** — Growatt Modbus controller now verifies TOU schedule entities are configured during health check, surfacing "Not configured — re-run setup wizard" instead of failing silently at schedule time.
- **Derived sensors removed from InfluxDB collection** — `lifetime_load_consumption`, `lifetime_system_production`, and `lifetime_self_consumption` are always derived from the 5 core energy sensors by `EnergyFlowCalculator`. Removed from InfluxDB collection and critical-sensor validation to eliminate false "Missing critical sensors" warnings.
- **Energy flow derivation unified across platforms** — `EnergyFlowCalculator` now derives `load_consumption` (solar + import - export), `system_production` (fallback to solar), and `self_consumption` (load - import) from core sensors. Platforms without native registers (GEN4 Modbus, SolaX Native) no longer show zero values.
- **Discovery preselection restored** — Growatt Server is preselected when both cloud and local Modbus integrations are present, matching the original behavior. Local Modbus remains available as an option in the wizard.
- **Nordpool area no longer overwritten by stale settings** — wizard settings load excluded `area` from restoration, ensuring discovery-detected area (e.g. SE3) is not clobbered by a previously saved value (e.g. SE4).

### Added

- TOU Schedule sensor group visible in setup wizard sensor config UI for Growatt Modbus platform.
- `total_yield` entity added to growatt-modbus mock scenario for correct wizard display.

## [9.0.0b14] - 2026-05-22

### Added

- **Nordpool HACS provider support** — setup wizard and settings page now properly handle three distinct pricing providers: `nordpool_official` (HA integration), `nordpool_hacs` (HACS custom sensor), and `octopus`. The HACS entity is auto-detected from discovery and persisted in settings.
- **Scenario-driven wizard tests** — setup wizard completion tests now load from JSON scenario files (`scripts/mock_ha/scenarios/ci-*.json`), matching the pattern used for algorithm tests. Adding a new wizard regression test is now just adding a variant to the scenario JSON.
- **CI scenario: Growatt Modbus** (`ci-wizard-growatt-modbus.json`) — tracked scenario with Growatt MIN + SolaX Modbus (GEN4 TOU) + official Nordpool SE3. Tests both local Modbus and cloud control paths.
- **CI scenario: Growatt Cloud + Octopus Energy** (`ci-wizard-growatt-cloud-octopus.json`) — UK user with Growatt SPH cloud-only + Octopus Energy pricing. Based on issue #60 debug log.
- **Scenario-driven discovery tests** (`test_scenario_discovery.py`) — auto-discovers scenarios with `expected_discovery` sections and validates integration flags, platform detection, and sensor entity IDs.
- Nordpool area detection now uses device registry identifiers (`[["nordpool", "SE3"]]`) instead of parsing entity unique_ids — more robust against HA naming changes.
- `EnergyFlowCalculator.rebuild_sensor_mapping()` public method replaces external access to private `_build_sensor_flow_mapping()`.

### Fixed

- **Growatt MIN/SPH detection was broken** — the HA `growatt_server` integration registers all services unconditionally (both MIN and SPH), so service-based detection always returned MIN. Now uses entity registry: MIN creates `switch.*_ac_charge`, SPH does not.
- **GEN4 SolaX Modbus sensor discovery** — four sensor suffixes missing from `SOLAX_ENTITY_SUFFIX_MAP`: `total_import_power` (import), `total_export_power` (export), `total_pv_power` (solar), `total_load_energy` (lifetime load). These are the actual GEN4 unique_id suffixes from real installations.
- **GEN4 `total_yield` mapped to wrong BESS key** — was mapped to `lifetime_load_consumption` instead of `lifetime_system_production` (Total Yield). This caused the sensor to not appear in the setup wizard.

### Changed

- **Renamed `nordpool` provider to `nordpool_hacs`** throughout codebase to avoid confusion with the official HA Nordpool integration. Includes automatic migration of legacy settings.
- Debug data exporter now includes device registry and entity registry in scrubbed output for better issue diagnostics.
- Inverter type detection comment updated to reflect entity-registry-based approach.

## [9.0.0b13] - 2026-05-20

### Added

- **Single-segment TOU for Growatt Modbus (GEN4)** — replaces the 9-slot TOU approach with a single TOU segment (slot 1) updated per-period. Reduces required HA entities from 45 to 5, removing the need to manually enable slots 4-9 in Home Assistant.
- Auto-migration: on startup, any enabled legacy TOU slots 2-9 are automatically disabled.
- GEN3/GEN4 platform split for Growatt Local Modbus — MIX/SPA/SPH (GEN3) and MIN/MOD/MID (GEN4) are now separate platforms with generation-specific sensor definitions, matching the existing MIN/SPH split for Growatt Cloud.
- GEN3 auto-detection via `load_first_battery_minimum_soc` entity marker in solax_modbus registry.
- SPH/MIX Connection selector — SPH sub-type now offers Cloud/Local Modbus connection choice (previously only MIN had this).
- GEN3 EMS suffix mappings (`battery_first_charge_rate`, `grid_first_discharge_rate`, `battery_first_maximum_soc`, `load_first_battery_minimum_soc`).
- Derived lifetime sensor fallbacks: GEN4 derives `lifetime_load_consumption` from solar + grid_import − grid_export; GEN3 derives `lifetime_system_production` from `lifetime_solar_energy`.
- 23 unit tests for single-segment TOU controller (mode tracking, migration, schedule comparison).

### Fixed

- Growatt MIN (Local/GEN4) no longer shows "Home Consumption Energy" as "Not detected" — the sensor was SPF-only in solax_modbus and never existed on MIN hardware. Removed from GEN4 UI; value is derived internally.
- Setup wizard no longer reports slots 2-9 as missing sensors for Growatt Modbus GEN4 platform.

### Changed

- `GrowattSolaxModbusController` rewritten from thin I/O subclass (55 lines) to full single-segment controller (~450 lines) with its own schedule creation, per-period mode management, and intent-based schedule comparison.
- Refactored `_has_growatt_tou_entities()` into shared `_has_solax_entity_suffix()` helper for DRY generation detection.
- Updated INVERTER_PLATFORMS.md with single-segment TOU documentation and migration notes.

## [9.0.0b11] - 2026-05-18

### Fixed

- Settings page now clears stale inverter sensor entity IDs when switching platform — previously only the wizard handled this, leaving old Growatt sensors active after switching to SolaX on the settings page.
- Advanced battery settings (efficiency, charging rate, temperature derating) hidden in wizard mode to reduce setup complexity.

### Changed

- Consolidated three duplicated inverter platform maps (wizard, settings page, backend) into shared `sensorDefinitions.ts` and `api_conversion.py` — single source of truth for UI type ↔ platform mapping.

### Added

- 29 unit tests for `POST /api/setup/complete` covering persistence, live system updates, sensor handling, scheduler lifecycle, and validation.

## [9.0.0b10] - 2026-05-17

### Fixed

- Switching inverter platform in wizard now replaces all inverter sensor fields with the new platform's discovered values instead of only filling empty fields — fixes stale Growatt Server entity IDs persisting after switching to SolaX Modbus (Local).

## [9.0.0b9] - 2026-05-17

### Added

- Debug export now includes HA entity registry (entity_id, unique_id, platform, device_id, original_name, disabled_by, hidden_by, capabilities) for diagnosing Growatt-via-SolaX-Modbus detection failures.
- Debug export captures solax_modbus/solax config entries, devices, and services (previously only growatt/nordpool).
- Keyword fallback matching in debug export — entities are captured even if registered under unexpected platform names.

### Fixed

- Documentation corrected: solax_modbus Growatt plugin entity_id contains `time_N_active` (from display name) while unique_id contains `time_N_enabled` (from plugin key); BESS matches on unique_id.
- Documented that TOU slots 4-9 are disabled by default in HA entity registry and must be manually enabled.

## [9.0.0b8] - 2026-05-15

### Fixed

- Growatt TOU detection skipped when both growatt_server (cloud) and solax_modbus (local) integrations are installed — `discover_integrations` used `if/elif` so the TOU entity check was never reached, locking out the "SolaX Modbus (Local)" connection option in the wizard.
- Wizard no longer locks out SolaX Modbus (Local) when TOU auto-detection is inconclusive — both connection options are selectable when solax_modbus is detected, auto-detection pre-selects but does not lock out.
- Top-level "SolaX Modbus" inverter platform renamed to "SolaX (Native)" with clarified description to prevent confusion with Growatt-via-solax_modbus.

### Added

- `solaxHasGrowattTou` field in discovery API response — frontend can distinguish native SolaX from Growatt-via-solax even when growatt_server is also present.
- Logging in `_has_growatt_tou_entities` to diagnose detection failures.

## [9.0.0b6] - 2026-05-10

### Added

- Growatt MIN inverter support via solax_modbus HACS integration (local Modbus, TOU entity writes).

### Fixed

- Wizard sensors merged instead of replaced after setup, leaving stale entities active until restart.
- Discovery config_entry_id/device_id blocked by stale values from previous runs.
- Energy provider not applied live after wizard completion.
- Price cache not cleared after Nordpool area update in discovery path.

## [9.0.0b5] - 2026-05-03

### Changed

- Entity discovery now exclusively uses HA entity registry (unique_id + platform fields, both immutable) — removes fragile states-based fallback that broke when users renamed entities.
- SolaX suffix map extended with Growatt-plugin EMS control entities (charging/discharging rate, stop SOC, charger switch).
- Growatt device_id lookup improved: matches by device identifiers first (immutable), falls back to config_entry, then name.

### Removed

- States-based discovery methods (`discover_growatt_sensors`, `discover_solax_sensors`, `_extract_solax_device_prefix`) — replaced by registry-based discovery.
- `solaxDevicePrefix` field from discovery API response (no longer needed).

## [9.0.0b4] - 2026-04-26

### Added

- Fresh install support — system starts in unconfigured mode when no inverter platform is configured, serving the web UI and setup wizard without crashing.
- Regression tests for fresh install startup scenarios (empty options, missing sections, unconfigured platform).
- Docker multi-worktree support — unique container names and stable port derivation per worktree directory.

### Fixed

- Startup crash on fresh install (`AssertionError: Unknown inverter_type ''`) — `_create_inverter_controller()` now returns `None` gracefully.
- SolaX spurious `Failed to adjust charging power` errors — `adjust_charging_power()` is now a no-op for SolaX (VPP controls power directly).
- Noisy WARNING for unconfigured optional sensors (e.g. `lifetime_self_consumption` on SolaX) downgraded to DEBUG.
- Default `additional_costs` updated to 0.773 SEK/kWh and `tax_reduction` to 0.1988 SEK/kWh matching E.ON example rates.
- `dev-run.sh` and `mock-run.sh` now print the access URL after startup completes (after Uvicorn ready), not before logs flood the terminal.
- Operational API endpoints return HTTP 503 (not 500) when system is unconfigured, guiding users to the setup wizard.

### Changed

- Scenario test data files now include explicit `price_data` so expected results are independent of global default changes.

## [9.0.0b3] - 2025-04-25

### Added

- Runtime inverter platform switching via `switch_inverter_platform()` — no restart required when changing between Growatt MIN, Growatt SPH, and SolaX.
- Entity-registry-based auto-discovery with states-based fallback for older HA versions without WebSocket support.
- Setup wizard returns all detected platform sensors (`platformSensors`), allowing sensor fields to auto-fill when switching inverter platform.
- Cross-platform integration test suite validates optimization, hardware writes, SOC limits, and health checks across all three inverter platforms.
- Mock HA server now supports WebSocket API (entity registry, config entries, device registry, services) for end-to-end setup wizard testing.

### Fixed

- Health check returned OK when required methods were specified but none were configured (now correctly returns ERROR).
- Setup wizard confirm button was enabled even when required sensor fields were empty.
- Growatt subtype radio buttons (MIN/SPH) no longer allow selecting a type that contradicts auto-detection results.
- Settings page detection of available platforms now derives from configured sensors instead of requiring a fresh discovery scan.

## [9.0.0b2] - 2026-04-24

### Fixed

- SolaX auto-detection now anchors on the `solax_` prefix across all HA domains (`sensor`, `select`, `number`, `button`) instead of generic battery suffixes, eliminating false positives from other integrations.
- SolaX entity suffix map expanded to cover all sensors required for feature parity with Growatt: grid export power, lifetime energy counters, load consumption, and correct VPP control entity names (`remotecontrol_*`).
- SolaX sensor settings UI now includes all entity fields: power monitoring (including grid export), lifetime energy counters, and charger use mode.
- SolaX VPP disable command sent wrong option value (`"Disabled Battery Control"` → `"Disabled"`).
- SolaX health check now verifies all 5 VPP control entities, not just power control mode.
- Self-consumption energy flow is now derived from `load - grid_import` when no dedicated sensor exists, removing the requirement for a `lifetime_self_consumption` sensor on platforms that don't provide one.

## [9.0.0b1] - 2026-04-18

### Added

- SolaX inverter support via homeassistant-solax-modbus integration (VPP active-power commands).
- Setup wizard auto-detects SolaX entities and shows platform-specific sensor configuration.
- Dashboard shows platform-aware hardware schedule section (TOU intervals for Growatt, VPP control info for SolaX).

### Changed

- Inverter scheduling refactored into an `InverterController` base class with `GrowattMinController`, `GrowattSphController`, and `SolaxController` subclasses.
- Inverter platform configuration moved from `growatt.inverter_type` to `inverter.platform` (existing settings are migrated automatically).
- API endpoints `/api/inverter/status` and `/api/inverter/schedule` added as canonical paths (legacy `/api/growatt/*` aliases preserved).

### Fixed

- Inverter status endpoint returned hardcoded `charge_stop_soc: 100%` instead of the configured `max_soc` from battery settings.
- SOLAR_STORAGE intent now uses `load_first` mode instead of `battery_first` on Growatt MIN and SPH inverters. The previous `battery_first` mode routed solar to the battery first, causing unnecessary grid imports to serve the home even when excess solar was available for both.
- DP optimizer no longer cycles charge/discharge during solar hours. The profitability check now accounts for the opportunity cost of stored energy: when sell > buy, discharge-for-export is blocked (round-trip losses make it unprofitable); when excess solar is available, the sell price is used as the cost basis floor (solar could have been exported instead). ([#73](https://github.com/johanzander/bess-manager/issues/73))
- IDLE periods now correctly model passive solar charging with charge rate clamping, and are classified as SOLAR_STORAGE when the battery absorbs excess solar.
- Setup wizard failed to auto-detect `battery_discharge_soc_limit_on_grid` entity on Growatt models that expose separate on-grid/off-grid SOC limit entities.
- MIN inverter returned 500 errors when the TOU schedule exceeded 9 slots on price-volatile days. Hardware writes now use only the active (capped) intervals with content-aware slot assignment to avoid evicting still-needed segments. (thanks [@pookey](https://github.com/pookey))

## [8.7.0] - 2026-05-22

### Fixed

- **Octopus Energy setup wizard** — entity IDs for import/export rates (today/tomorrow) are now persisted when completing the setup wizard. Previously these were collected in the form but never saved, forcing Octopus users (Flux, Agile, etc.) to re-enter them on the Settings page. ([#60](https://github.com/johanzander/bess-manager/issues/60))
- **Analysis agent** — restructured the `@claude-bot analyze` pipeline to focus on the user's current problem instead of stale issue reports. The bot now triages the latest debug bundle before reading code, and performs a sanity check against recent comments before posting.

### Added

- Setup wizard E2E test coverage for `POST /api/setup/complete` endpoint (3 new tests).
- Agent documentation sync from beta: verification guidelines, release workflow, scope discipline, worktree conventions, 7-scenario wizard E2E matrix docs, project-level agent memory files.
- Ruff auto-lint hook for edited Python files (`.claude/settings.json`).

## [8.6.0] - 2026-05-14

### Added

- **HA Statistics consumption forecast strategy** — new `ha_statistics` option that builds a time-of-day consumption profile from the past 7 days of Home Assistant Recorder long-term statistics. Captures daily patterns (morning/evening peaks, overnight baseline) using a trimmed mean that filters out outlier spikes like EV charging. No extra integrations needed — works with the built-in HA Recorder.
- **Consumption Forecast Comparison** view on the Insights page — collapsible chart comparing all available forecast strategies (sensor, fixed, InfluxDB, HA Statistics) against actual consumption, with MAE accuracy metrics to show which strategy performs best.
- HA Recorder WebSocket API methods (`get_statistics_during_period`, `list_statistic_ids`, `find_statistic_id`) for querying long-term energy statistics.

## [8.5.1] - 2026-05-12

### Fixed

- Schedule deviation charts Y-axis now always includes zero, fixing missing zero reference on battery charge/discharge chart and duplicate tick labels on small-range charts like grid export.

## [8.5.0] - 2026-05-09

### Added

- "Report a Problem" button in the header that downloads the debug bundle and opens a pre-filled GitHub issue, with inline shortcuts on runtime failure alerts and the global alert banner. ([#94](https://github.com/johanzander/bess-manager/pull/94))
- Raw HA WebSocket discovery dump (nordpool and growatt config entries, scrubbed for secrets and identifiers) in the debug export. ([#94](https://github.com/johanzander/bess-manager/pull/94))

### Fixed

- Nordpool area discovery now extracts the area from entity registry unique_ids (e.g. `SE4-current_price`) instead of config entry data, which HA's WebSocket API does not return. Removes broken attribute-guessing fallbacks for HACS nordpool sensors. ([#91](https://github.com/johanzander/bess-manager/issues/91))

## [8.4.3] - 2026-05-07

### Fixed

- Nordpool area discovery now reads `data.areas` (list) matching the official HA integration format; previous `options.area`/`data.area` lookup never matched real config entries. ([#91](https://github.com/johanzander/bess-manager/issues/91))

## [8.4.2] - 2026-05-03

### Fixed

- Nordpool price area now correctly detected for the official HA core integration (`nordpool_official`); bootstrap default `SE4` placeholder no longer blocks discovery from setting the real area. ([#78](https://github.com/johanzander/bess-manager/issues/78), [#85](https://github.com/johanzander/bess-manager/pull/85))
- Stale TOU segments on the inverter are now detectable after optimization cycles where schedules matched; TOU interval state is carried forward when the schedule manager is replaced, preventing stale segments from becoming invisible to BESS. ([#88](https://github.com/johanzander/bess-manager/pull/88))
- `SOLAR_STORAGE` intent now correctly derives `batt_mode` from the `INTENT_TO_MODE` mapping (`load_first`) instead of the hardcoded `battery_first`. ([#88](https://github.com/johanzander/bess-manager/pull/88))

## [8.4.1] - 2026-04-29

### Fixed

- Stale TOU segments left on inverter causing uncontrolled grid export after 24h+ uptime. Past TOU intervals were not cleaned up from hardware when the schedule transitioned to no future intervals. (thanks [@ehrw](https://github.com/ehrw))

## [8.4.0] - 2026-04-29

### Added

- Redesigned Forecast Accuracy page with uniform card grid showing solar accuracy, consumption accuracy, savings comparison, and battery/grid deviations
- Forecast comparison charts (predicted vs actual) for solar, consumption, battery, grid import, and grid export
- Hourly deviation bar chart showing how each energy flow deviated from plan
- Full-day savings breakdown (snapshot vs current) in comparison API
- Grid import/export tracking in prediction analyzer
- Prediction snapshots now persist to disk and survive add-on restarts

## [8.3.1] - 2026-04-23

### Fixed

- SOLAR_STORAGE intent now uses `load_first` mode instead of `battery_first` on Growatt MIN and SPH inverters. The previous `battery_first` mode routed solar to the battery first, causing unnecessary grid imports to serve the home even when excess solar was available for both.

### Added

- Mock run time override: `./mock-run.sh <scenario> HH:MM` replays a scenario from a specific time of day.

## [8.3.0] - 2026-04-19

### Fixed

- DP optimizer no longer cycles charge/discharge during solar hours. The profitability check now accounts for the opportunity cost of stored energy: when sell > buy, discharge-for-export is blocked (round-trip losses make it unprofitable); when excess solar is available, the sell price is used as the cost basis floor (solar could have been exported instead). ([#73](https://github.com/johanzander/bess-manager/issues/73))
- IDLE periods now correctly model passive solar charging with charge rate clamping, and are classified as SOLAR_STORAGE when the battery absorbs excess solar.

## [8.2.3] - 2026-04-18

### Fixed

- Setup wizard failed to auto-detect `battery_discharge_soc_limit_on_grid` entity on Growatt models that expose separate on-grid/off-grid SOC limit entities.

## [8.2.2] - 2026-04-18

### Fixed

- MIN inverter returned 500 errors when the TOU schedule exceeded 9 slots on price-volatile days. Hardware writes now use only the active (capped) intervals with content-aware slot assignment to avoid evicting still-needed segments. (thanks [@pookey](https://github.com/pookey))

## [8.2.1] - 2026-04-17

### Fixed

- SOLAR_STORAGE and GRID_CHARGING periods now correctly write charge rate 100% to the inverter register when power monitoring is disabled. Previously, a stale 0% rate left by a preceding LOAD_SUPPORT or EXPORT_ARBITRAGE period caused the inverter to export excess solar instead of storing it.
- Nordpool service contract tests now pass when run in isolation, not just as part of the full suite. Backend test path setup no longer implicitly depends on core tests running first.
- InfluxDB health check now shows actionable error messages (e.g. "Wrong username or password" for HTTP 401) instead of raw status codes.
- Removed hardcoded fallback values and `hasattr` guards in API endpoints that masked configuration errors with fabricated data. The system now fails explicitly when misconfigured.
- Detailed schedule endpoint no longer sends `batterySocEnd` and `soc` fields that were hardcoded placeholders (50%) and never actually displayed — dashboard data always owns those values.

### Changed

- Removed redundant local imports throughout the codebase. All imports are now at module level.
- Added `_get_intent_description()` to `SphScheduleManager` for consistent interface with `GrowattScheduleManager`.

## [8.2.0] - 2026-04-17

### Changed

- Nord Pool HACS custom sensor integration now uses a single sensor entity (which exposes both `raw_today` and `raw_tomorrow` attributes) instead of two separate sensor fields. Existing settings are migrated automatically on first boot.
- Setup wizard pre-fills current Swedish default values for additional costs (0.77 SEK/kWh) and export compensation (0.20 SEK/kWh) for E.ON in SE4.
- User Guide substantially expanded: full documentation for all three price providers, all three consumption forecast strategies, and the EV charging discharge inhibit feature.
- Installation guide updated with corrected InfluxDB v2 connectivity test command.

### Fixed

- Nord Pool official integration now passes the configured area code to the `nordpool.get_prices_for_date` service call and looks up the response by that key. Previously the first list in the response was used regardless of area, which could return wrong-area prices on multi-area installations.
- Octopus Energy prices are no longer incorrectly inflated by the markup/VAT/additional-costs formula. The backend now detects that Octopus rates are already all-in and uses them as-is for buy prices.
- Switching price provider to Octopus Energy in the Settings UI now auto-resets markup rate, VAT multiplier, and additional costs to neutral values, preventing stale Nord Pool values from being saved.
- Partial settings PATCH requests now use deep merge: updating a single nested field (e.g. `config_entry_id`) no longer silently erases sibling fields in the same section.

## [8.1.1] - 2026-04-13

### Added

- Dashboard shows a dedicated "initializing" state immediately after wizard completion while the historical backfill and first schedule build run in the background (instead of a blank or error screen).
- Wizard re-run no longer clears previously configured values — existing sensor entity IDs, Nordpool config entry ID, and Growatt device ID all survive a re-scan.

### Changed

- Settings API consolidated into a single `GET /api/settings` and `PATCH /api/settings` endpoint, replacing the previous per-section endpoints. Existing installs are migrated automatically on first boot. Frontend updated throughout.
- Disabled power monitoring now reports `OK` in system health instead of `WARNING`.

### Fixed

- Growatt entity ID discovery now handles both the current SOC sensor name ("State of charge (SoC)") and the legacy name ("Statement of Charge SOC"), covering more installation variants.
- InfluxDB query skipped cleanly when no sensors are configured, avoiding a crash during first-boot before the wizard completes.

## [8.0.7] - 2026-04-12

### Fixed

- Dashboard banner not cleared after saving any settings change. Health check is now re-run after every settings mutation (battery, electricity, home, energy provider, inverter, sensors) so the banner always reflects the current state.

## [8.0.6] - 2026-04-12

### Fixed

- Dashboard banner showed stale "Electricity Price Data: Critical sensor configuration issue" after wizard completion because `_critical_sensor_failures` was only populated at startup and never cleared. Health check now re-runs at the end of wizard completion.
- Saving Home settings from the Settings page returned 422 because `currency` (stored in the Pricing form) was not included in the request payload.

## [8.0.5] - 2026-04-12

### Fixed

- `settings_store.py` missing from the root `Dockerfile` used by GitHub/HA Supervisor builds (the `backend/Dockerfile` used for local packaging was already fixed in 8.0.1).

## [8.0.4] - 2026-04-12

### Fixed

- Nordpool `config_entry_id` discovered by the setup wizard was saved to disk but not applied to the running price source, causing the health check to report "No config entry ID configured" until restart.
- Power monitoring remained disabled after the setup wizard enabled it: `HomePowerMonitor` was only created at startup, so enabling it via the wizard had no effect until restart.
- Setup wizard completion could corrupt numeric settings with `None` values for fields not included in the payload; live updates now only overwrite fields that were explicitly provided.
- `settings_store.py` added to `package-addon.sh` build context (missing from local installation packaging).

## [8.0.1] - 2026-04-12

### Fixed

- `settings_store.py` was missing from the Docker image `COPY` step, causing startup to fail with `ModuleNotFoundError`.

## [8.0.0] - 2026-04-12

### Changed

- **Settings storage moved out of `config.yaml`** — all operational settings (battery, home, electricity price, energy provider, Growatt, sensors) are now stored in `/data/bess_settings.json`, owned and managed by the add-on. On first boot, existing settings are automatically migrated from `options.json` — no manual action required. `config.yaml` now only holds InfluxDB credentials.

### Added

- Full-featured Settings page: all configuration (battery parameters, home settings, pricing, sensor entity IDs) is now editable directly in the UI — no more manual `config.yaml` editing for day-to-day configuration.
- First-time setup wizard with automatic detection of Home Assistant integrations (Growatt, Nordpool, Solcast, phase current sensors) — maps sensor entity IDs automatically so most users need zero manual configuration.

### Removed

- EV charging energy meter support removed (the feature was never wired up to the optimizer and had no effect on battery scheduling).

## [7.17.2] - 2026-04-11

### Added

- Compact debug export now serves three distinct use cases from a single endpoint: exact scenario replay, AI behaviour analysis via bess-analyst + MCP server, and prediction drift analysis throughout the day.
- Log filtering in compact mode: key events (errors, hardware commands, decisions, intent transitions) from the full day plus the last 50 lines, replacing the previous 2000-line tail that only covered ~2 hours.
- Entity snapshot rendered as a flat table in compact mode (state + unit per entity) with the full JSON in a collapsible for mock HA replay.
- Historical periods rendered as a compact markdown table (intent, observed intent, SOE, solar, import, savings) with full JSON collapsible for replay.
- Schedule section now includes economic summary and a period-decisions table in compact mode.
- Snapshot section now shows a full-day evolution table (all hourly optimization runs with total savings, actual count, predicted count) for drift analysis, instead of only the latest snapshot.
- `BESS_VERSION` environment variable set at Docker image build time; `_get_version()` reads it first before falling back to `config.yaml` (local dev).
- HA metadata fields (`last_changed`, `last_updated`, `last_reported`, `context`) stripped from entity snapshots — not used in any of the three debug use cases.
- `BESS_URL` added to `.env.example` for MCP server direct port access.

### Fixed

- Log formatter no longer suppresses log content when log lines contain the word "error" — now correctly checks for "error reading" to detect actual read failures.
- Debug log parser correctly identifies schedule JSON blocks in compact format by requiring the `optimization_period` key, ignoring the economic summary and input metadata blocks that precede the full schedule collapsible.
- `from_debug_log.py` scenario generator handles compact logs without `input_data` gracefully.
- Empty entity ID configured in sensor map now raises an explicit `ValueError` immediately instead of producing a confusing downstream failure.

## [7.16.1] - 2026-04-05

### Fixed

- Fixed solar-only charging not applying the configured charging power rate. The power monitor was returning early when grid charging was disabled, leaving the inverter at whatever rate was previously set. It now correctly applies 100% charging power for solar scenarios (no fuse risk).

## [7.16.0] - 2026-04-05

### Added

- Discharge inhibit: optional binary sensor (`discharge_inhibit`) that suppresses BESS discharge when active (e.g. EV charger on, Tibber grid award). Discharge resumes automatically within ~1 minute once the sensor clears. Leave the field empty to disable.

## [7.15.0] - 2026-04-03

### Added

- Dashboard alert banner now has two tiers: red (critical) for required sensor failures and amber (warning) for optional sensors that are configured but not responding.
- TOU segment write failures are now recorded in the runtime failure tracker and shown in the dashboard instead of being silently swallowed.
- Health checks treat `not_configured` sensors as SKIPPED rather than ERROR, preventing false warnings for optional sensors the user has not set up.

### Fixed

- Fixed timezone bug where `datetime.now()` returned UTC in the HA add-on container, causing off-by-one hour errors in period and date calculations for users in non-UTC timezones during the window around local midnight.
- Fixed spurious +0.1 kWh battery charge appearing in all predicted evening hours due to floating-point accumulation in `np.arange()` producing near-zero IDLE power that bypassed direction checks in `_compute_reward()`.
- Fixed Octopus Energy price source rejecting rates on DST spring-forward days (23-hour days now correctly require 46 periods instead of 48). (thanks [@pookey](https://github.com/pookey))

## [7.14.0] - 2026-04-02

### Added

- Debug export captures a full entity snapshot (raw HA state for every sensor BESS reads), enabling verbatim scenario replay in `mock-run.sh` without reconstructing values from processed data.
- Mock HA server handles `nordpool.get_prices_for_date` service calls and exposes `/api/config` for timezone, enabling correct `nordpool_official` replay.
- Mock HA replay seeds historical data directly from the scenario file, removing the InfluxDB dependency. Falls through to InfluxDB when the seed file is absent or all entries are invalid.

### Fixed

- Fixed `regex=` → `pattern=` in FastAPI `Query()` (Pydantic v2 compatibility).
- Container timezone is now propagated from the host in `dev-run.sh` and `mock-run.sh`.

## [7.13.0] - 2026-03-25

### Added

- Experimental SPH inverter support (`inverter_type: "SPH"` in config). MIN remains the default; SPH is opt-in. (thanks [@GraemeDBlue](https://github.com/GraemeDBlue))
- `power_monitoring_enabled` config option to disable phase current monitoring when current sensors are unavailable.

## [7.12.0] - 2026-03-25

### Added

- Mock HA development environment (`./mock-run.sh`) — runs the full BESS stack against a local FastAPI mock server. Scenarios are generated from debug logs; no real HA or inverter needed.
- Debug export now includes raw electricity prices, full addon options (entity IDs, inverter config), and active inverter TOU segments for exact scenario replay.

### Fixed

- Fixed `initial_soe` in debug log export being recorded as a percentage instead of kWh when the midnight SOC snapshot was used.

## [7.11.5] - 2026-03-25

### Fixed

- Fixed DP optimizer charging at a more expensive price window when a cheaper overnight window was available. The backward pass was not propagating future export value at max-SOE states, making early and late charging opportunities appear equally attractive.

## [7.11.4] - 2026-03-24

### Changed

- Refactored DP optimizer hot path to eliminate per-action dataclass allocation, reducing memory pressure during optimization.

### Fixed

- Fixed weather test helper generating invalid `hour=24` datetime strings when forecast spans midnight.

## [7.11.3] - 2026-03-24

### Fixed

- InfluxDB health check no longer reports OK when the bucket is misconfigured — it now tests connectivity with a sensor-agnostic query and reports a clear warning with the current bucket name and correct format.
- Fixed a variable name collision in the health check that caused a spurious "Critical System Issues Detected" error on startup.

### Changed

- `tax_reduction` default set to `0.0` — Swedish skattereduktion was removed as of Jan 1 2026.

### Documentation

- Added complete InfluxDB setup guide (Steps 2a–2f): two-user setup, `configuration.yaml` snippet, bucket naming (`homeassistant/autogen`), and connection verification.
- Added Nordpool electricity price section explaining VAT-exclusive pricing, the buy price formula, per-country VAT table, and Swedish cost breakdown (överföringsavgift, energiskatt, moms).
- Added InfluxDB troubleshooting section with InfluxDB UI navigation steps and a `curl` command to verify BESS read access.

## [7.11.2] - 2026-03-21

### Fixed

- Force Docker cache bust on every version bump so HA always builds frontend from latest source.

## [7.11.0] - 2026-03-21

### Changed

- Dashboard status cards redesigned: removed duplicate status badges, added inline colored pills for Grid/Battery direction and Strategic Intent.
- Battery card now shows Strategic Intent as the main KPI and Battery Mode as a sub-KPI.
- Status card labels renamed for clarity: "Power Flow"→"Home Power", "Solar Production"→"Solar Generation", "Home Load"→"Home Usage", "Grid Flow"→"Grid", "Energy & Power"→"Battery".
- Energy Flow chart switched from step bars to smooth monotone lines with midpoint positioning for clearer period visualisation.
- Battery Mode Schedule and Energy Flow chart horizontal axes now align exactly.
- Schedule intent labels updated to plain-language names: "Charging from Grid", "Storing Solar", "Powering Home", "Selling to Grid", "Standby".

## [7.10.0] - 2026-03-16

### Changed

- Dashboard chart layout: Schedule moved to top, followed by Energy Flow and Battery SOC charts. (thanks [@pookey](https://github.com/pookey))
- Consistent external section headings across all dashboard charts (Schedule, Energy Flow, Battery SOC and Energy Flow). (thanks [@pookey](https://github.com/pookey))
- Removed electricity price line from Battery SOC chart to reduce right-axis clutter. (thanks [@pookey](https://github.com/pookey))
- Removed "Battery" label and internal title from Battery Mode Timeline for cleaner layout. (thanks [@pookey](https://github.com/pookey))
- Removed "Actual hours" / "Predicted hours" legend labels from both charts (shading is self-explanatory). (thanks [@pookey](https://github.com/pookey))

## [7.9.5] - 2026-03-14

### Added

- Configurable consumption forecast strategy via `home.consumption_strategy`: `sensor` (default, HA 48h average), `fixed` (flat rate from config), or `influxdb_7d_avg` (7-day rolling average from InfluxDB power sensor data at 15-minute resolution). (thanks [@pookey](https://github.com/pookey))

## [7.9.4] - 2026-03-14

### Changed

- HA API retries now use exponential backoff (2s, 4s, 8s) instead of a fixed 4-second delay. (thanks [@pookey](https://github.com/pookey))
- TOU segment write failures now include a descriptive operation string and the HTTP response body for actionable diagnostics. (thanks [@pookey](https://github.com/pookey))

### Fixed

- Unavailable or unknown HA sensors now return `None` instead of 0.0, preventing zero values from corrupting optimization. (thanks [@pookey](https://github.com/pookey))
- Inverter page no longer blanks when a single API endpoint fails on startup. (thanks [@pookey](https://github.com/pookey))

## [7.9.3] - 2026-03-13

### Added

- Expired TOU intervals shown with reduced opacity, strikethrough times, and an "Expired" badge in the inverter schedule view. (thanks [@pookey](https://github.com/pookey))
- "Pending Write" amber badge on the inverter page for TOU segments queued but not yet written to hardware. (thanks [@pookey](https://github.com/pookey))

### Changed

- TOU schedule now uses a rolling window: only future periods generate segments, freeing hardware slots during mid-day re-optimizations. (thanks [@pookey](https://github.com/pookey))
- TOU segment IDs are stable across re-optimizations, preventing hardware slot divergence and overlap warnings. (thanks [@pookey](https://github.com/pookey))
- When >9 TOU segments are generated, all are kept in memory and the next 9 non-expired are written to hardware; pending segments cascade into freed slots on the next cycle. (thanks [@pookey](https://github.com/pookey))

### Fixed

- Schedule creation crash when optimization produces more than 9 TOU segments. (thanks [@pookey](https://github.com/pookey))
- KeyError when building stable segment IDs from intervals that had not yet been written to hardware. (thanks [@pookey](https://github.com/pookey))

## [7.8.1] - 2026-03-12

### Fixed

- Battery Mode Schedule tooltip showing incorrect times for sub-hour slot boundaries (e.g. 22:30 displayed as 22:00). (thanks [@pookey](https://github.com/pookey))
- Current-time marker on Battery Mode Schedule positioned at start of hour regardless of minutes elapsed. (thanks [@pookey](https://github.com/pookey))

## [7.8.0] - 2026-03-10

### Added

- Configurable single/three-phase electricity support via `home.phase_count` (1 or 3, default 3); fixes fuse protection for single-phase systems (common in the UK). (thanks [@pookey](https://github.com/pookey))

### Fixed

- `max_fuse_current`, `voltage`, and `safety_margin_factor` from config.yaml were not being applied — power monitor always ran on hardcoded defaults. (thanks [@pookey](https://github.com/pookey))

## [7.7.1] - 2026-03-10

### Fixed

- Add-on no longer discoverable from GitHub due to invalid `list?` schema type in `config.yaml`. Removed `derating_curve` from schema validation (HA Supervisor does not support nested list types).

## [7.7.0] - 2026-03-09

### Added

- Temperature-based charge power derating for outdoor batteries, using HA weather forecast to apply per-period charge limits via a configurable LFP derating curve. Opt-in via `battery.temperature_derating.enabled` in config.yaml. (thanks [@pookey](https://github.com/pookey))

## [7.6.2] - 2026-03-07

### Changed

- Profitability gate threshold now scales with remaining horizon (`max(15%, remaining/total)`) so mid-day optimizer runs are not held to a full-day savings bar.

## [7.6.1] - 2026-03-07

### Fixed

- Chart dark mode detection now tracks the `dark` CSS class on `<html>` via MutationObserver instead of OS `prefers-color-scheme`, correctly following Tailwind's `class` strategy.
- Axis tick label colors, grid lines, and price line now render correctly in dark mode.

### Changed

- Vite dev proxy target can be overridden via `VITE_API_TARGET` environment variable.

## [7.6.0] - 2026-03-07

### Added

- Battery Mode Schedule timeline on the Dashboard page, showing a color-coded horizontal bar of strategic intents (Grid Charging, Solar Storage, Load Support, Export Arbitrage, Idle) with hover tooltips, current-hour marker, and tomorrow's plan faded when available. (thanks [@pookey](https://github.com/pookey))

## [7.5.0] - 2026-03-07

### Added

- Timezone is now read automatically from Home Assistant's `/api/config` at startup instead of being hardcoded to `Europe/Stockholm`. Falls back to `Europe/Stockholm` with a warning if HA is unreachable. (thanks [@pookey](https://github.com/pookey))

## [7.4.5] - 2026-03-07

### Fixed

- Startup data collection for the last completed period used live sensors instead of InfluxDB, causing inflated values (e.g. ~2x) and leaving the next period nearly empty on the chart. (thanks [@pookey](https://github.com/pookey))
- Chart price line now shows visual gaps instead of dropping to zero when price data is unavailable.
- BatteryLevelChart SOC line no longer shows a flat 0% line for predicted hours with no data.

## [7.4.4] - 2026-03-07

### Fixed

- Chart grid lines now use `prefers-color-scheme` media query for dark mode detection, matching Tailwind's `media` strategy. Previously, charts used a DOM class check that detected Home Assistant's dark mode theme even when BESS UI was rendering in light mode, causing dark grid lines on a white background.

## [7.4.3] - 2026-03-07

### Fixed

- Visual improvements and alignment across EnergyFlowChart and BatteryLevelChart: predicted hours grey overlay added to BatteryLevelChart to match EnergyFlowChart, both charts now show a subtle grey background for tomorrow's data with a solid divider line at midnight.
- BatteryLevelChart tooltip now handles N/A values correctly and suppresses hover on the zero-anchor phantom point.
- Fixed `-0` display in battery action tooltip (now shows `0`).

## [7.4.2] - 2026-03-07

### Fixed

- EnergyFlowChart and BatteryLevelChart data now aligned to period start, eliminating one-period misalignment caused by a fake zero-point offset. (thanks [@pookey](https://github.com/pookey))
- Electricity price line now renders as a step function instead of smooth interpolation.
- Predicted hours shading now uses Recharts ReferenceArea instead of a raw SVG rect that rendered at incorrect coordinates.
- Tomorrow period numbers normalised correctly when API returns them as 96-191 continuation.
- X-axis tick labels use modulo 24 for clean hour display across the day boundary.

## [7.4.1] - 2026-03-07

### Fixed

- Terminal value calculation now uses the median of remaining buy prices instead of the average, preventing peak prices from inflating the estimate and causing the optimizer to hold charge instead of discharging during high-price periods. (thanks [@pookey](https://github.com/pookey))

## [7.4.0] - 2026-03-06

### Changed

- Currency is now configurable throughout the optimization pipeline and UI; removed hardcoded SEK/Swedish locale references. (thanks [@pookey](https://github.com/pookey))

## [7.3.0] - 2026-03-04

### Added

- Extended optimization horizon to 2 days when tomorrow's prices are available, enabling true cross-day arbitrage decisions. Only today's schedule is deployed to the inverter. (thanks [@pookey](https://github.com/pookey))
- Terminal value fallback when tomorrow's prices aren't yet published, preventing the optimizer from treating stored battery energy as worthless at end of day.
- Tomorrow's solar forecast support via Solcast `solar_forecast_tomorrow` sensor.
- Dashboard, Inverter, and Savings pages show tomorrow's planned schedule when available.
- DST-safe period-to-timestamp conversion throughout.

### Fixed

- Economic summary and profitability gate now scoped to today-only periods, preventing inflated savings figures when the horizon extends into tomorrow.

## [7.2.0] - 2026-03-02

### Changed

- DP optimizer assigns terminal value to stored battery energy at end of horizon, preventing premature end-of-day export.

## [7.1.1] - 2026-03-02

### Fixed

- Battery SOC no longer shows impossible values (e.g. 168%) when battery capacity differs from the 30 kWh default. `SensorCollector`, `EnergyFlowCalculator`, and `HistoricalDataStore` were initialised with the default capacity and only received the configured value via manual propagation in `update_settings()`. They now hold a shared `BatterySettings` reference so the configured capacity is always used for SOC-to-SOE conversion.

## [7.1.0] - 2026-03-01

Thanks to [@pookey](https://github.com/pookey) for contributing this fix (PR #20).

### Fixed

- InfluxDB CSV parsing now uses header-aware column detection instead of hardcoded indices, supporting both InfluxDB 1.x and 2.x where columns appear at different positions depending on version and tag configuration. Queries also match on both `_measurement` and `entity_id` tag to handle both data models.
- Historical data no longer lost after restart. A sensor name prefix mismatch in the batch query parser caused initial-value lookups to create duplicate entries that overwrote correct per-period values during normalization, producing flat SOC and zero energy deltas across the entire day.

## [7.0.0] - 2026-03-01

Thanks to [@pookey](https://github.com/pookey) for contributing Octopus Energy support (PR #19).

### Added

- Octopus Energy Agile tariff support as a new price source alongside Nordpool. Fetches import and export rates from Home Assistant event entities at 30-minute resolution with VAT-inclusive GBP/kWh prices.
- Separate import and export rate entities for Octopus Energy, allowing direct sell price data instead of calculated fallback.
- `get_sell_prices_for_date()` on `PriceSource` for sources that provide direct export/sell rates.
- `PriceManager.clear_cache()` to propagate settings changes at runtime without restart.
- Documentation for Octopus Energy setup in README, Installation Guide, and User Guide.
- UPGRADE.md with step-by-step migration instructions for the breaking config change.

### Changed

- **Breaking:** Unified energy provider configuration into a single `energy_provider:` section. The previous `nordpool:` top-level section and `nordpool_kwh_today`/`nordpool_kwh_tomorrow` sensor entries have been replaced. See [UPGRADE.md](UPGRADE.md) for migration instructions.
- Price logging now uses currency-neutral column headers instead of hardcoded "SEK".
- `HomeAssistantSource` now takes entity IDs directly via constructor instead of looking them up from the sensor map.
- Pricing parameters (markup, VAT, additional costs) now propagate immediately when updated via settings without requiring a restart.

### Removed

- `use_official_integration` boolean from config (replaced by `energy_provider.provider` field).
- `nordpool_kwh_today`/`nordpool_kwh_tomorrow` from `sensors:` section (moved to `energy_provider.nordpool`).
- Dead code: `LegacyNordpoolSource` class and unused Nordpool price methods from `ha_api_controller.py`.

### Fixed

- Grid charging now always charges at full power (100%) instead of being throttled to the DP algorithm's planned kW. The DP power level is an energy model artifact, not a hardware rate limit — the power monitor already handles fuse protection correctly. Previously, `hourly_settings` stored a proportional rate (e.g. 25% when the DP planned 1.5 kW out of 6 kW max), causing the inverter to charge far slower than it should during cheap price periods.
- Removed dead `charge_rate` local variable from `_apply_period_schedule` which was computed but never applied to hardware, eliminating the misleading split-brain between two code paths.

## [6.0.7] - 2026-03-01

### Fixed

- Grid charging now always charges at full power (100%) instead of being throttled to the DP algorithm's planned kW. The DP power level is an energy model artifact, not a hardware rate limit — the power monitor already handles fuse protection correctly. Previously, `hourly_settings` stored a proportional rate (e.g. 25% when the DP planned 1.5 kW out of 6 kW max), causing the inverter to charge far slower than it should during cheap price periods.
- Removed dead `charge_rate` local variable from `_apply_period_schedule` which was computed but never applied to hardware, eliminating the misleading split-brain between two code paths.

## [6.0.6] - 2026-02-26

### Fixed

- Historical data no longer shows as missing all day when InfluxDB is configured with InfluxDB 1.x (accessed via v2 compatibility API). The Flux query previously included a `domain == "sensor"` tag filter that is absent in 1.x setups, causing the batch query to silently return zero rows. The `_measurement` filter already uniquely identifies sensors, making the domain filter redundant.
- Batch sensor data that loads successfully but returns no periods is no longer cached, allowing the system to retry on the next 15-minute period rather than remaining stuck with an empty cache for the entire day.

## [6.0.5] - 2026-02-18

### Fixed

- System no longer crashes at startup if the inverter is temporarily unreachable when syncing SOC limits. A warning is logged and startup continues normally; the inverter retains its previous limits.

## [6.0.4] - 2026-02-08

### Added

- Compact mode for debug data export - reduces export size by including only latest schedule/snapshot and last 2000 log lines
- `compact` query parameter on `/api/export-debug-data` endpoint (defaults to `true`)

### Changed

- MCP server `fetch_live_debug` now uses `compact` parameter instead of `save_locally`
- Increased MCP server fetch timeout from 60s to 90s for large exports
- Raised `min_action_profit_threshold` default from 5.0 to 8.0 SEK

### Fixed

- Corrected `lifetime_load_consumption` sensor name in config.yaml (was pointing to daily sensor instead of lifetime)

## [6.0.0] - 2026-02-01

### Changed

- TOU scheduling now uses 15-minute resolution instead of hourly aggregation
- Eliminates "charging gaps" where minority intents were lost due to hourly majority voting
- Each 15-minute strategic intent period now directly maps to TOU segments
- Schedule comparison uses minute-level precision for accurate differential updates

### Added

- `_group_periods_by_mode()` groups consecutive 15-min periods by battery mode
- `_groups_to_tou_intervals()` converts period groups to Growatt TOU intervals
- `_enforce_segment_limit()` handles 9-segment hardware limit using duration-based priority
- DST handling for fall-back scenarios (100 periods) with proper time capping

### Fixed

- Single strategic period (e.g., 15-min GRID_CHARGING) now creates TOU segment instead of being outvoted
- Overlap detection uses minute-level precision instead of hour-level

## [5.7.0] - 2026-01-31

### Added

- MCP server for BESS debug log analysis - enables Claude Code to fetch and analyze debug logs directly
- Token-based authentication for debug export API endpoint (for external/programmatic access)
- `.bess-logs/` directory for cached debug logs (gitignored)

### Changed

- SSL certificate verification enabled by default for MCP server connections (security improvement)
- Optional `BESS_SKIP_SSL_VERIFY=true` environment variable for local self-signed certificates

## [5.6.0] - 2026-01-27

General release consolidating recent fixes.

## [5.5.0] - 2026-01-27

### Fixed

- Cost basis calculation now correctly accounts for pre-existing battery energy

## [5.4.0] - 2026-01-26

### Added

- InfluxDB bucket now configurable by end user in config.yaml

## [5.3.1] - 2026-01-23

### Fixed

- Improved sensor value handling in EnergyFlowCalculator

## [5.3.0] - 2026-01-22

### Changed

- Updated safety margin to 100%
- Removed "60 öringen" threshold
- Removed step-wise power adjustments

## [5.2.0] - 2026-01-22

General release consolidating v5.1.x fixes.

## [5.1.7] - 2026-01-18

### Fixed

- Missing period handling when HA sensors unavailable
- DailyViewBuilder now creates placeholder periods instead of skipping them when sensor data is unavailable (e.g., HA restart)
- Snapshot comparison API no longer crashes with IndexError

### Added

- `_create_missing_period()` to create placeholders with `data_source="missing"`
- Recovery of planned intent from persisted storage when available
- `missing_count` field in DailyView for transparency

## [5.1.6] - 2026-01-18

### Changed

- Refactored strategic intent to use economics-based decisions
- Strategic intent now derived from economic analysis rather than inferred from energy flows
- Prevents feedback loop where observed exports were incorrectly classified as EXPORT_ARBITRAGE

## [5.1.5] - 2026-01-17

### Fixed

- Fixed floating-point precision issue in DP algorithm where near-zero power levels (e.g., 2.2e-16) were incorrectly classified as charging/discharging instead of IDLE
- Fixed edge case in optimization where no valid action at boundary states (e.g., max SOE with unprofitable discharge) would leave period data undefined, now creates proper IDLE state
- Fixed `grid_to_battery` energy flow calculation to be correctly constrained by actual battery charging amount, preventing impossible energy flows

## [2.5.7] - 2025-11-10

### Fixed

- Fixed critical bug where invalid estimatedConsumption field in battery settings prevented all settings from being applied
- Fixed settings failures silently continuing with defaults instead of failing explicitly
- Currency and other user configuration now properly applied on startup

### Changed

- Settings application now fails fast with clear error message when configuration is invalid
- Removed estimatedConsumption from internal battery settings (now computed on-demand for API responses only)

## [2.5.5] - 2025-11-07

### Fixed

- Fixed initial_cost_basis returning 0.0 when battery at reserved capacity, causing irrational grid charging at high prices
- Fixed settings not updating from config.yaml due to camelCase/snake_case mismatch in update() methods
- Fixed dict-ordering bug where max_discharge_power_kw would be overwritten by max_charge_power_kw depending on key order
- Added explicit AttributeError for invalid setting keys instead of silent failures

### Changed

- Settings classes now convert camelCase API keys to snake_case attributes automatically
- Removed silent hasattr() checks in favor of explicit error handling
- Added Git Commit Policy to CLAUDE.md documentation

## [2.5.4] - 2025-11-07

### Fixed

- Fixed test mode to properly block all hardware write operations using "deny by default" pattern
- Fixed duplicate config.yaml files - now single source of truth in repository root
- Removed unused ac_power sensor configuration

### Changed

- Test mode now controlled via HA_TEST_MODE environment variable instead of hardcoded
- Updated docker-compose.yml to mount root config.yaml for development
- Updated deploy.sh and package-addon.sh to use root config.yaml

## [2.5.3] - 2025-11-06

### Fixed

- Fixed HACS/GitHub repository installation by restructuring to single add-on layout
- Moved add-on configuration files (config.yaml, Dockerfile, build.json, DOCS.md) to repository root
- Removed unnecessary bess_manager/ subdirectory (proper for single add-on repositories)
- Dockerfile now correctly references backend/, core/, and frontend/ from repository root
- Build context is now repository root, allowing direct access to all source directories

## [2.5.2] - 2024-11-06

### Added

- Home Assistant add-on repository support for direct GitHub installation
- Multi-architecture build configuration (aarch64, amd64, armhf, armv7, i386)
- repository.json for Home Assistant repository validation

### Fixed

- Removed duplicate config.yaml and run.sh files (now using symlinks)
- Removed duplicate CHANGELOG.md from bess_manager directory
- Fixed deploy.sh to work with symlinked configuration files

### Changed

- Restructured repository to comply with Home Assistant add-on store requirements

## [2.5.0] - 2024-10

- Quarterly resolution support for Nordpool integration
- Improved price data handling and metadata architecture

## [2.4.0] - 2024-10

- Added warning banner for missing historical data
- Added optimization start from below minimum SOC with warning
- Fixed savings and grid import columns in savings view

## [2.3.0] and Earlier

For earlier version history, see the [commit history](https://github.com/johanzander/bess-manager/commits/main/).
