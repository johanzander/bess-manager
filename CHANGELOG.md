# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
