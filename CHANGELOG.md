# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [6.3.6] - 2026-03-02

### Changed

- `SensorCollector`, `EnergyFlowCalculator`, and `HistoricalDataStore` now receive a shared `BatterySettings` reference instead of a bare `float` capacity. Components always read the live value from the shared settings object, eliminating the need for manual capacity propagation in `update_settings()`. This matches the pattern already used by `DailyViewBuilder` and `GrowattScheduleManager`.

## [6.3.5] - 2026-03-01

### Fixed

- Historical data no longer lost after restart. A sensor name prefix mismatch in the InfluxDB batch query parser caused initial-value lookups to always create duplicate entries under non-prefixed keys, which then overwrote correct per-period values during normalization. Every period received yesterday's stale values instead of today's actual readings — producing flat SOC (stuck at previous day's last value) and zero energy deltas across the entire day. The fix aligns the prefix convention so initial values are correctly merged into existing sensor data.

## [6.3.3] - 2026-03-01

### Fixed

- Grid charging now uses 100% charge power rate. Previously the charge rate was derived from the optimizer's planned power level, causing the battery to charge slowly during cheap grid periods instead of at full speed. The optimizer controls *which* periods to charge (strategic intent), while the power monitor handles fuse protection — there was no need to additionally throttle the rate.

## [6.3.0] - 2026-02-28

### Added

- Historical data now persists across restarts. Dashboard energy flow chart and Hourly Battery Actions & Savings page retain their data when BESS restarts instead of showing empty charts. Data is saved to `/config/bess_historical_data.json` after each 15-minute recording period and loaded on startup if from today, following the same persistence pattern used by `ScheduleStore`.

## [6.2.2] - 2026-02-28

### Fixed

- Battery SOC no longer shows impossible values (e.g. 168%) on the Savings page and Dashboard chart for historical periods. The `SensorCollector`, `EnergyFlowCalculator`, and `HistoricalDataStore` were initialized with the default 30 kWh battery capacity, but `update_settings()` only updated `BatterySettings` without propagating the new capacity to these components. State-of-energy was stored using 30 kWh and later displayed using the configured 10 kWh, inflating SOC by 3×. Capacity is now propagated to all dependent components when battery settings are updated.

## [6.2.1] - 2026-02-28

### Fixed

- Octopus Energy prices no longer display at ~1.33 GBP/kWh. The `PriceManager` retained Swedish default pricing parameters (markup=0.08, VAT=1.25, additional=1.03) because `update_settings()` updated the settings dataclass but never propagated the new values to the running `PriceManager`. Settings are now forwarded and the price cache is cleared on update.
- Octopus Energy 30-minute rates are now expanded to 96 quarterly (15-minute) periods at the source level, ensuring correct timestamps and consistent resolution across all code paths. The previous normalization at the BSM level duplicated price-entry dicts which carried wrong timestamps.

## [6.2.0] - 2026-02-28

### Fixed

- InfluxDB queries now work with both 1.x and 2.x data models. In 1.x, `_measurement` holds the unit of measurement (e.g. `%`, `W`) and the entity ID is stored in an `entity_id` tag; in 2.x, `_measurement` holds the entity ID directly. Query filters now match on either field.
- CSV response parsers now detect column positions from the header row instead of using hardcoded indices, preventing silent data loss when InfluxDB returns columns in a different order depending on version and tag configuration.
- Diagnostic logging in batch queries uses header-aware column detection and logs raw response lines when zero sensors are found, making InfluxDB version mismatches immediately visible in logs.

## [6.1.3] - 2026-02-27

### Fixed

- Octopus Energy prices (48 half-hourly) are now normalized to 15-minute quarterly resolution before entering the optimization pipeline. The system internally uses 96 periods/day (15-min each) for period indices, historical store, and Growatt schedules. Passing 48-element price arrays caused `list assignment index out of range` when the 15-min period index (e.g. 90) exceeded the array size, preventing any optimization from running.

## [6.1.2] - 2026-02-27

### Fixed

- Inverter page no longer shows blank/zero data when the dashboard endpoint fails. Changed `Promise.all` to `Promise.allSettled` so each API fetch succeeds or fails independently. A failing `/api/dashboard` (e.g. when no optimization schedule exists) no longer discards successful results from inverter status, schedule, and battery settings endpoints.

## [6.1.1] - 2026-02-27

### Fixed

- `get_tomorrow_prices()` now catches `PriceDataUnavailableError` in addition to `ValueError`, so the "return empty list if not yet available" fallback actually works for Octopus Energy.
- Octopus Energy rate validation accepts 46-48 rates instead of requiring exactly 48. Octopus publishes rates incrementally and the last couple of half-hours may arrive slightly later.

## [6.1.0] - 2026-02-27

### Added

- Octopus Energy Agile tariff support as a new price source alongside Nordpool. Fetches import and export rates from HA event entities at 30-minute resolution with VAT-inclusive GBP/kWh prices.
- `price_provider` configuration field to select between `nordpool`, `nordpool_official`, and `octopus` price sources.
- Separate import and export rate entities for Octopus Energy, allowing direct sell price data instead of calculated fallback.
- `period_duration_hours` on `PriceSource` to support different rate resolutions (15-min Nordpool, 30-min Octopus).
- `get_sell_prices_for_date()` on `PriceSource` for sources that provide direct export/sell rates.
- Documentation for Octopus Energy setup in README, Installation Guide, and User Guide.

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
