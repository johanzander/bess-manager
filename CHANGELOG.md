# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [7.5.1] - 2026-03-12

### Fixed

- TOU segments now include `is_expired` flag in the backend so the frontend's expired-slot rendering actually works. Previously the flag was only handled in the UI but never set by the API.

## [7.5.0] - 2026-03-12

### Changed

- TOU schedule generation now uses a rolling window: only future periods (from the current optimization period onwards) are converted to TOU segments. Past segments no longer consume hardware slots, making the 9-segment limit much less likely to be hit during mid-day re-optimizations.
- TOU segment IDs are now stable across re-optimizations: when a segment's time range and mode haven't changed, its ID is reused from the previous run, minimizing unnecessary inverter writes.
- Removed past-interval copying loop from schedule creation — the rolling window approach makes it unnecessary.
## [7.4.0] - 2026-03-09

### Added

- Configurable single/three-phase electricity support via `home.phase_count` setting (1 or 3, default 3). Single-phase systems (common in the UK) no longer incorrectly divide battery power by 3, which was underestimating phase load and reducing fuse protection effectiveness.
- Pass through `max_fuse_current`, `voltage`, and `safety_margin_factor` from config.yaml to the settings system — these were previously defined in config but stayed at defaults.

### Changed

- Power monitor health check adapts to phase count: single-phase systems only require L1 current sensor, not L2/L3.
- Power monitor logging adapts to show one or three phases depending on configuration.

## [7.3.1] - 2026-03-08

### Fixed

- Battery Mode Schedule tooltip showing incorrect times for sub-hour slot boundaries (e.g. 22:30 displayed as 22:00) because `formatHour` always appended `:00`.
- Current-time marker on Battery Mode Schedule snapping to the start of the hour instead of reflecting the actual minutes elapsed.

## [7.3.0] - 2026-03-08

### Added

- Temperature-based charge power derating for outdoor batteries. The optimizer now uses weather forecast temperatures to reduce max charge power in cold conditions, matching real-world LFP battery BMS behavior. Configurable derating curve with sensible defaults. Disabled by default (opt-in via `battery.temperature_derating.enabled`).
- Shared weather forecast utility (`core/bess/weather.py`) extracted from ML module for reuse across optimizer and ML prediction.

## [7.2.0] - 2026-03-07

### Added

- Battery Mode Schedule timeline on Dashboard page. Shows a color-coded horizontal bar of strategic intents (Grid Charging, Solar Storage, Load Support, Export Arbitrage, Idle) across the 24-hour schedule, including tomorrow's plan when available. Supports hover tooltips, current-hour marker, and both hourly and quarter-hourly resolution.

## [7.1.1] - 2026-03-07

### Fixed

- ML predictions missing from ML Report page. The 23:00 cron job generated predictions but the 23:55 next-day preparation wiped them without regenerating. Moved ML prediction generation from 23:00 to 23:55 so predictions survive into the new day.

## [7.1.0] - 2026-03-07

### Changed

- Timezone is now read automatically from Home Assistant at startup instead of being hardcoded to `Europe/Stockholm`. Falls back to the default if HA is unreachable.
- Docker Compose `TZ` is now a per-developer setting via `.env` instead of hardcoded.

## [7.0.13] - 2026-03-06

### Fixed

- Startup data collection for the last completed period used live sensors instead of InfluxDB, causing it to include energy from the in-progress period. This inflated the last completed period (e.g. ~2x values) and left the next period nearly empty on the chart. Now forces InfluxDB for all periods during startup when no sensor cache exists.

## [7.0.12] - 2026-03-06

### Fixed

- Terminal value calculation now uses the median of remaining buy prices instead of the last known non-zero price. The previous approach was provider-specific (worked for Octopus Agile by accident but not Nordpool). The median is outlier-resistant, works across all price providers, and correctly handles negative prices which the `p > 0` filter incorrectly skipped.

## [7.0.11] - 2026-03-06

### Removed

- Remove disk persistence from HistoricalDataStore. This was a workaround for InfluxDB data-fetching bugs that have since been fixed. On startup, `_fetch_and_initialize_historical_data()` rebuilds all periods from InfluxDB, making the JSON persistence file redundant. Strategic intent persistence (ScheduleStore) is unaffected.

## [7.0.10] - 2026-03-06

### Fixed

- ML weather forecast fetch failing inside HA add-on container. The ML config used `HA_TOKEN` env var but the HA supervisor sets `HASSIO_TOKEN`. Now checks `HASSIO_TOKEN` first (matching `app.py` controller pattern), falling back to `HA_TOKEN` for local dev.

## [7.0.9] - 2026-03-06

### Fixed

- ML predictions now generated proactively on boot and daily after retrain, so the ML Report tab shows data regardless of `consumption_strategy` (previously only populated on-demand for `ml_prediction`)
- System crash when `ml` config section is missing and `consumption_strategy` is set to `ml_prediction` or `influxdb_profile`. Now falls back to `fixed` strategy with a clear error log
- ML config `load_config()` now raises a descriptive `KeyError` when the `ml` section is missing, instead of a cryptic error from inside the config builder
- ML training failure on boot no longer crashes the entire system — errors are logged and startup continues

## [7.0.8] - 2026-03-06

### Fixed

- ML Report forecast chart missing the ML predictions line when using `influxdb_profile` strategy. The predictions cache was only populated when `ml_prediction` was the active strategy. Now generates predictions on demand when the report tab is opened.

## [7.0.7] - 2026-03-06

### Fixed

- Startup crash (`KeyError: 'HA_DB_URL'`) when ML model trains on boot in production. The ML config builder required InfluxDB credentials as environment variables, but in the HA add-on they come from options.json. Now falls back to the `influxdb` section in app options when env vars are not set.

## [7.0.6] - 2026-03-06

### Changed

- ML model now trains on boot and daily at 23:00 whenever the `ml` config section is present, regardless of `consumption_strategy`. This ensures the ML Report page always has data even when using `influxdb_profile` or other strategies.

## [7.0.5] - 2026-03-06

### Added

- Weekly average (influxdb_profile) line on the ML Report forecast chart, shown alongside ML predictions and yesterday's actual consumption
- ML Report page now visible when `consumption_strategy` is set to `influxdb_profile`, not just `ml_prediction`
- Active strategy indicator in the ML Report API response and chart title

## [7.0.4] - 2026-03-06

### Fixed

- Dashboard returning 500 errors because real-time power sensors (pv_power, local_load_power, import_power, export_power, output_power, self_power, system_power) were missing from the config.yaml schema. HA strips options not in the schema, so all power sensor values were None.

## [7.0.3] - 2026-03-06

### Fixed

- Add-on failing to start due to stray sensor fields (`pv_power`, `import_power`, etc.) in the `ml` schema section of config.yaml. HA schema validation rejected configs missing these non-existent ML options.

## [7.0.2] - 2026-03-06

### Changed

- Switched Docker base image from Alpine to Debian (bookworm). Alpine uses musl libc which has no prebuilt wheels for xgboost, scikit-learn, or pandas — forcing compilation from source on every install (~15+ minutes on typical hardware, longer on low-spec machines). Debian's glibc base uses prebuilt manylinux wheels, reducing pip install from 15+ minutes to under 1 minute.

## [7.0.1] - 2026-03-06

### Fixed

- Docker image build failing because the `ml/` module was not copied into the production container and Alpine build dependencies for xgboost compilation (g++, cmake, make, libgomp) were missing.

## [7.0.0] - 2026-03-06

### Added

- ML energy consumption predictor (`ml/` module). XGBoost model trained on historical InfluxDB sensor data produces 96 quarter-hourly forecasts using cyclical time encoding, daylight hours, weather data, and historical consumption context. Integrates with the battery optimizer via `consumption_strategy: ml_prediction` with daily retrain at 23:00 and cached predictions.
- Configurable consumption forecasting via `consumption_strategy` setting in the `home` config section. Four strategies available:
  - `sensor` (default): Reads the existing 48h-average HA sensor. Backwards-compatible, no changes needed for existing users.
  - `fixed`: Uses the `home.consumption` config value as a flat forecast. No sensors required.
  - `influxdb_profile`: Queries InfluxDB for a 7-day weekly average profile, producing a shaped 96-value forecast that reflects actual daily usage patterns.
  - `ml_prediction`: Runs a trained XGBoost ML model with weather forecast data for weather-aware consumption predictions.
- ML Report tab in the web UI showing forecast chart (predicted vs yesterday), model metrics comparison table (XGBoost vs baselines), and feature importance visualization. Served by new `/api/ml-report` endpoint reading a training sidecar file.
- ML CLI tools: `train`, `predict`, `evaluate`, `baseline`, `report`, and `fetch-data` commands for standalone model development.
- `consumptionStrategy` field exposed in the battery settings API and frontend TypeScript types.

## [6.10.3] - 2026-03-05

### Fixed

- Terminal value calculation now uses the last known non-zero price in the remaining horizon rather than the average of all remaining prices. Using the average inflated the terminal value when evening peak prices were included, causing the optimizer to incorrectly prefer holding battery charge over discharging during high-price periods. The last known price (typically an overnight off-peak rate) is a more accurate proxy for the expected cost of recharging tomorrow.

## [6.10.2] - 2026-03-05

### Fixed

- Current in-progress period was incorrectly labeled as "Predicted" in chart tooltips. Changed strict less-than to less-than-or-equal when comparing period index to current period, so the active quarter-hour uses actual sensor data when available.

## [6.10.1] - 2026-03-05

### Fixed

- Predicted hours background shading on Energy Flow Chart was invisible because the XAxis used category mode. Added `type="number"` so `ReferenceArea` can render at any coordinate within the domain, not just at data point positions.

## [6.10.0] - 2026-03-05

### Fixed

- Energy flow chart no longer starts with a fake zero-point at x=0 that caused all data lines to ramp from zero to the first real value.
- Data points positioned at start of each period (x=0 for hour 00:00-01:00) instead of offset positions, so chart data aligns correctly with hour grid lines on both charts.

## [6.9.1] - 2026-03-05

### Fixed

- Sensor data corruption when HA sensors are temporarily unavailable. When Growatt cloud went offline, `_get_sensor_value()` silently returned `0.0` for all lifetime cumulative sensors, poisoning the delta cache. The next collection cycle computed deltas against zero, attributing the entire lifetime sensor total (e.g., 4278 kWh) to a single 15-minute period. Now returns `None` on failure so the period is skipped and the cache remains valid.
- Sensor failures no longer abort the optimization cycle. Energy data collection errors in `_update_energy_data()` are now caught and logged, allowing the optimization to proceed even when a sensor is temporarily unavailable.
- `_normalize_sensor_readings()` no longer stores `0.0` for unparseable sensor values, which could also corrupt delta calculations. Invalid values are now skipped.

## [6.9.0] - 2026-03-05

### Fixed

- X-axis labels on dashboard charts no longer show broken `+00` formatting for tomorrow's hours. Both charts now display actual hour of day (00-23) with the "Tomorrow" separator line distinguishing days.
- Predicted hours background shading on the Energy Flow Chart now aligns correctly with chart data using Recharts `ReferenceArea` instead of raw percentage-based `<rect>` elements.
- Zero or missing price data no longer causes chart lines to drop to zero. Prices of 0 are treated as null, creating gaps in the line instead of misleading values.
- Zero SOC on predicted (non-actual) periods in the Battery Level Chart treated as null to avoid false drops to zero at end of day.

### Changed

- Electricity price line on both charts changed from smooth interpolation (`monotone`) to step function (`stepAfter`), accurately representing that prices are flat within each period.
- Removed tomorrow background shading overlay and midnight separator line on both charts. Tomorrow data still plots normally, visually distinguishable by the repeating x-axis hour labels.
- Removed "Tomorrow" legend swatch from Energy Flow Chart legend.
- X-axis now uses explicit tick positions at whole hours with `interval={0}` to prevent duplicate labels and ensure grid alignment.

## [6.8.0] - 2026-03-03

### Fixed

- EconomicSummary now scoped to today-only periods. The DP algorithm computes economics over the full extended horizon (up to 192 periods), which inflated the profitability gate threshold and prediction snapshot values. After array truncation, the economic summary is recalculated from only today's period data so that stored schedules, prediction snapshots, and log messages reflect accurate single-day figures.

### Added

- Savings page "Tomorrow's Projected Savings" collapsible section. When tomorrow's optimization data is available, a toggle button appears below the hourly table showing the period count. Expanding reveals three summary cards (Grid-Only Cost, Optimized Cost, Projected Savings) and a full hourly breakdown table with indigo-themed headers and reduced opacity, matching the Inverter page's visual pattern.
- `tomorrowData` field added to the `DashboardResponse` TypeScript interface, aligning the frontend type with the backend API response.

## [6.7.0] - 2026-03-03

### Changed

- Growatt TOU schedule now includes tomorrow's optimized intents for past time slots. Since TOU segments are dateless (HH:MM only), slots before the current hour won't fire again until tomorrow — they now carry tomorrow's plan instead of stale today intents. When tomorrow's prices aren't available, behavior is unchanged.
- Schedule comparison and hardware writes cover all segments (period 0 onwards) when tomorrow's intents are stitched, ensuring the inverter receives the full rolling 24h schedule.
- Removed dead code in `_consolidate_and_convert_with_strategic_intents()`: the `current_period` variable was always 0 and the past-interval-copying loop never executed. All periods are now explicitly processed from period 0.

## [6.6.0] - 2026-03-02

### Added

- Inverter page "Schedule Overview (15-min Resolution)" now shows tomorrow's planned schedule when tomorrow's prices are available. Period groups are rendered below today's table with an indigo separator header and reduced opacity to distinguish predicted from active data.
- `get_detailed_period_groups()` accepts an optional `intents` parameter, allowing it to group any strategic intent list (not just the active schedule).
- `/api/growatt/detailed_schedule` response includes `tomorrowPeriodGroups` extracted from the ScheduleStore optimization result, following the same pattern as the dashboard's `tomorrowData`.

### Fixed

- Unused `charge_power_rate` variable in `GrowattScheduleManager` now prefixed with underscore to satisfy ruff RUF059.

## [6.5.0] - 2026-03-02

### Added

- Dashboard charts now display tomorrow's optimization data when available. Both the Energy Flow Chart and Battery SOC & Actions chart extend past midnight, showing predicted energy flows, SOC trajectory, battery actions, and prices for the next day.
- Vertical midnight separator line with "Tomorrow" label clearly marks the today/tomorrow boundary on both charts.
- Tomorrow's data rendered with reduced opacity overlays and bar opacity to visually distinguish from today's predictions.
- X-axis labels show +00, +01, etc. for tomorrow's hours; tooltips prefix "Tomorrow" when hovering over next-day data.
- New `tomorrowData` field in dashboard API response (`/api/dashboard`) extracts tomorrow's period data from the ScheduleStore optimization result.
- Resolution toggle (15min / 60min) works correctly with the extended horizon data.

### Notes

- Tomorrow's data is display-only. The Growatt inverter schedule deployment remains today-only since TOU segments are date-unaware.
- When tomorrow's prices haven't been published yet (typically before ~13:00), charts display exactly as before.

## [6.4.0] - 2026-03-02

### Added

- Extended DP optimization horizon. When tomorrow's electricity prices are available, the optimizer now considers up to 192 periods (2 days) instead of just today's 96, preventing suboptimal end-of-day battery dumping. Only today's schedule is ever deployed to the Growatt inverter — tomorrow's data is purely an optimization input.
- Terminal value fallback for end-of-horizon energy. When tomorrow's prices aren't published yet, the DP algorithm assigns an estimated value to energy remaining in the battery at the end of the horizon, preventing the optimizer from treating stored energy as worthless and exporting at unfavorable rates.
- Tomorrow's solar forecast support. Added `get_solar_forecast_tomorrow()` to `HomeAssistantAPIController` backed by Solcast's tomorrow forecast sensor, providing the optimizer with next-day solar production data for extended horizon calculations.

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
