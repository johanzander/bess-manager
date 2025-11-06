# Changelog

All notable changes to BESS Battery Manager will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
