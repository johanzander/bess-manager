# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
