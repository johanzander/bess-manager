# Epic plan: remove the InfluxDB dependency (#722)

> Coordination doc for the multi-PR removal of BESS's InfluxDB read path.
> Each PR below is a separate `implement-issue` run against #722. This file is
> the shared design; per-PR TDD detail lives in each PR.

## Why

BESS's only remaining InfluxDB dependency is the archived community
**InfluxDB Home Assistant add-on** (`hassio-addons/addon-influxdb`). HA core's
`influxdb:` write integration is separate and unaffected. InfluxDB's read role
has already been displaced everywhere except cold-start / long-downtime
backfill and the `influxdb_7d_avg` consumption strategy — both of which move to
HA Recorder, which every install already has (default 10-day retention; the old
code needed <= 7 days).

Keeping InfluxDB as an optional "bring your own external instance" path was
considered and rejected: BESS's historical needs are <= 10 days, so retention
depth (InfluxDB's only real edge) buys nothing; a power user who wants more
sets `recorder: purge_keep_days`. Keeping it would mean two code paths for one
job and ~940 lines of fragile 1.x/2.x CSV parsing on the maintenance books.
Git history keeps `influxdb_helper.py` recoverable.

## Shared design

`core/bess/ha_recorder_helper.py` mirrors the two functions `sensor_collector`
imports from `influxdb_helper`, with the same return contract
(`{"status": "success" | "error", "data": {period_int: {sensor_key: float}}}`,
`sensor.`-prefixed keys, 96 fifteen-minute periods):

| Function | Source | Output |
|---|---|---|
| `get_sensor_data_batch(controller, sensors, date)` | `GET /api/history/period/<start>` (raw state changes) | last cumulative value at each of the 96 period boundaries |
| `get_power_sensor_data_batch(controller, power_sensors, date)` | same endpoint | mean W per period -> kWh (`mean * 0.25 / 1000`) |

- Reads go through `HAApiController.get_history_period()`, a thin wrapper over
  `_api_request` (reuses retry / failure-tracking). The helper takes the
  controller as its first argument — unlike `influxdb_helper`'s module-level
  config reads.
- `/api/history/period` returns `[[{entity_id, state, last_changed}, ...], ...]`
  — one list per entity, `minimal_response` so only the first entry per list
  carries `entity_id`. Single clean shape: the InfluxDB 1.x/2.x
  `_measurement`/`entity_id` dual-parsing disappears. Non-numeric states
  (`unknown` / `unavailable`) are skipped.
- HA prepends the state as of the window start, so the "fetch the value from
  before day start" second query that `_parse_batch_response` needed is gone.
- No `is_*_configured` gate — Recorder is assumed present. Empty response ->
  `{"status": "error", ...}` and callers degrade exactly as they did on an
  InfluxDB miss.

Mock HA gains a `GET /api/history/period/{start_time}` route
(`scripts/mock_ha/server.py`) returning the same `list[list[dict]]` shape, so
PR 2's E2E exercises the real path.

## PRs

Dependency-ordered. Each references `#722`; only PR 6 carries `Closes #722`.

### PR 1 — `ha_recorder_helper` + mock endpoint + this plan  *(current)*

- New: `core/bess/ha_recorder_helper.py`,
  `core/bess/tests/unit/test_ha_recorder_helper.py`, this file.
- Modify: `core/bess/ha_api_controller.py` (+`get_history_period`),
  `scripts/mock_ha/server.py` (+route).
- Not imported by any production path. Pure add — no behaviour change.

### PR 2 — switch cold-start backfill to Recorder

- `core/bess/sensor_collector.py`: swap the `influxdb_helper` import for
  `ha_recorder_helper`; thread the controller through (`SensorCollector`
  already holds `ha_controller`).
- `core/bess/battery_system_manager.py`: delete the
  `if not is_influxdb_configured(): return` guard in
  `_fetch_and_initialize_historical_data` — backfill always attempts.
- `influxdb_helper.py` stays on disk, now unused by `sensor_collector`.
- Verify: mock-HA E2E — fresh-start-mid-day scenario fills periods
  `0..current` from Recorder.

### PR 3 — port the 7-day load-power average to Recorder

- `battery_system_manager._get_influxdb_7d_avg_forecast` uses
  `ha_recorder_helper.get_power_sensor_data_batch` over `days_back in 1..7`.
- This is a net upgrade: `ha_statistics` cannot run on platforms where
  `lifetime_load_consumption` is derived rather than a real entity (SolaX
  Native, Solis); the Recorder-backed `local_load_power` average gives those
  installs a history-based forecast for the first time.
- Decided: renamed `influxdb_7d_avg` → `load_power_7d_avg`, with
  `canonicalize_consumption_strategy()` in `core/bess/settings.py` accepting
  the old id on load and in the API validator so existing installs keep
  working with no migration.
- Touched `backend/api.py` `_CONSUMPTION_STRATEGIES` + validator, the strategy
  lists in `battery_system_manager` (2 sites) + `_DATE_CACHED_...` set + the
  renamed `_get_load_power_7d_avg_forecast`, the frontend dropdown /
  comparison chart / types, and `USER_GUIDE.md` / `INSTALLATION.md` (strategy
  section only — the InfluxDB *setup* section is PR 4/6) / `SOFTWARE_DESIGN.md`
  / `bess-knowledge.md`.

### PR 4 — deprecation banner + migration note  *(starts the clock)*

- Backend: `/api/settings` now returns `influxdbConfigPresent` (= the
  existing `is_influxdb_configured()`).
- Frontend: `DeprecationBanner.tsx` — a dismissible (per-browser localStorage)
  amber banner on the Dashboard when the flag is set. Links to the
  `INSTALLATION.md` migration section. Component test + a `dashboard.spec.ts`
  E2E case (`ci-options.json` still carries an `influxdb` block).
- Docs: `INSTALLATION.md` Step 2 rewritten to "Historical Data (Automatic)"
  with a "Migrating from the InfluxDB add-on" subsection; the
  "Troubleshooting InfluxDB" section flagged legacy.
- **PRs 5-6 must not merge until a stable release carrying PR 4 has been out
  >= 1 month.**

### PR 5 — delete the InfluxDB client + health check  *(after the window)*

- Delete `core/bess/influxdb_helper.py`,
  `core/bess/tests/unit/test_influxdb_helper.py`.
- `core/bess/health_check.py`: remove `check_historical_data_access` + its
  registration. `backend/app.py`: remove the 5-minute
  `test_influxdb_connection` cron job.
- `core/bess/debug_findings.py` (drop / retarget the "No InfluxDB data"
  regex), `core/bess/debug_data_exporter.py` (remove the `influxdb`
  cred-stripping block), `core/bess/exceptions.py` (reword
  `HistoricalDataUnavailableError`). (`sensor_collector.py`'s log/comment
  strings were already swept in PR 2, when the file was rewired.)
- `.claude/agents/bess-analyst.md`: replace the InfluxQL/Chronograf section
  with `/api/history` + `statistics_during_period` guidance.

### PR 6 — remove the config option + rename + drop the banner  *(after the window)*

- `bess_manager/config.yaml`: delete the `influxdb` schema block and its
  `options` default -> **zero add-on options** (call this out in the PR body).
- `backend/app.py` (`_load_influxdb_options` + merge),
  `core/bess/settings_store.py` (the options.json note), drop the
  `HA_DB_URL/BUCKET/USER_NAME/PASSWORD` env handling.
- Rename `resolve_sensor_for_influxdb` -> `resolve_entity_id` across
  `ha_api_controller.py`, `sensor_collector.py`, `energy_flow_calculator.py`
  + tests.
- Remove the PR 4 banner + `influxdb_config_present` flag.
- Docs sweep: `README.md`, `DOCS.md`, remaining `INSTALLATION.md` /
  `USER_GUIDE.md` / `SOFTWARE_DESIGN.md` references.

## Sequencing

`1 -> 2 -> 3` back-to-back. `4` any time after `2`. `5` and `6` gated on `4`
shipping stable + 1 month; `5` before `6` (code before schema). Each PR:
`./scripts/quality-check.sh` green, references `#722`, no `Closes` until PR 6.
