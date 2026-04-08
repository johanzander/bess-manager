# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [7.17.1] - 2026-04-08

### Fixed

- Updated `vite` from 6.3.5 to 6.4.2 to address two security advisories: arbitrary file read via dev server WebSocket (high) and path traversal in optimised deps `.map` handling (medium).

## [7.17.0] - 2026-04-08

### Added

- **Experimental:** Auto-configuration setup wizard. On first use (no sensors configured), the UI redirects to a wizard that scans Home Assistant for Growatt and Nordpool integrations and maps sensor entity IDs automatically — no manual `config.yaml` editing required. Optional integrations (Solcast, EV metering, phase currents, etc.) are also detected. The "Auto-Configure" button on the System Health page allows re-running discovery at any time.

### Removed

- Removed unused diagnostic sensors `output_power`, `self_power`, `system_power`, and `net_grid_power` (not available on Growatt MIN series).

### Fixed

- Docker dev environment volume mounts and `PYTHONPATH` corrected for updated project layout.

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
