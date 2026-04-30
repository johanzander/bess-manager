# Architecture Reference

## System Overview

BESS Manager is a Home Assistant add-on that optimizes a battery storage unit
for cost savings via price-based arbitrage and solar integration. A dynamic
programming algorithm generates a 24-hour battery schedule at 15-minute resolution.

## Component Map

```
Users / GitHub Issues
        ↓
.github/workflows/          ← GitHub Actions (automation entry points)
scripts/                    ← Agent scripts (triage, fixer, reviewer, MCP server)
        ↓
backend/app.py              ← FastAPI app + hourly scheduler
backend/api.py              ← REST endpoints (all /api/* prefixed)
backend/api_dataclasses.py  ← All API response models (source of truth)
backend/api_conversion.py   ← camelCase conversion + serialization
        ↓
core/bess/                  ← Domain logic (no HA dependencies here)
  battery_system_manager.py  ← Main orchestrator
  dp_battery_algorithm.py    ← Optimization engine (DP)
  ha_api_controller.py       ← HA sensor/device interface + METHOD_SENSOR_MAP
  sensor_collector.py        ← Data aggregation from InfluxDB + HA
  price_manager.py           ← Electricity pricing (Nordpool / Octopus)
  growatt_schedule.py        ← Inverter TOU schedule format
  health_check.py            ← System validation utilities
  exceptions.py              ← All custom exception types
        ↓
Home Assistant API + Growatt Inverter
```

## Hourly Update Cycle

1. Scheduler triggers `BatterySystemManager.update_battery_schedule()`
2. `SensorCollector` reads current energy data from InfluxDB + HA
3. `PriceManager` fetches/caches electricity spot prices
4. `DPBatteryAlgorithm` generates 24h optimal schedule
5. `GrowattScheduleManager` converts schedule to TOU intervals
6. `HomeAssistantAPIController` sends commands to inverter

## API Structure

All endpoints return camelCase JSON via `convert_keys_to_camel_case()`.

| Prefix | Purpose |
|--------|---------|
| `GET/PUT /api/settings/*` | Battery and price configuration |
| `GET /api/dashboard` | Unified real-time + daily data |
| `GET /api/system-health` | Component diagnostics |
| `GET /api/schedule` | Current inverter schedule |
| `GET /api/decisions` | Hourly strategy analysis |
| `GET /api/debug` | Full debug data export |

## Data Models

Defined in `backend/api_dataclasses.py`:

- `APIBatterySettings` — capacity, power limits, SOC bounds
- `APIPriceSettings` — area, VAT, markup, tax reduction
- `APIRealTimePower` — live power readings (use `from_controller()`)
- `APISystemHealth` — component health status

Frontend mirrors these in `frontend/src/types.ts`.

## Health Check Pattern

```python
return perform_health_check(
    component_name="Battery Monitoring",
    description="Real-time battery state monitoring",
    is_required=True,
    controller=self.ha_controller,
    all_methods=battery_methods,
    required_methods=required_battery_methods,
)
```

Never implement custom health check logic — always use `perform_health_check()`.

## Test Structure

```
core/bess/tests/
  unit/              ← Fast, no HA connection required
    data/            ← JSON scenario fixtures
  integration/       ← Full system workflow tests
backend/tests/       ← API endpoint tests
```

Run all tests: `pytest`
Run unit tests only: `pytest core/bess/tests/unit/`

## Version and Release

Current version is the `version:` field in `config.yaml` (root directory).
CHANGELOG is in `CHANGELOG.md`. Follow semantic versioning (PATCH/MINOR/MAJOR).
