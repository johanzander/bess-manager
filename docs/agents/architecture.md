# Architecture Reference (Agent Summary)

> **Canonical source**: `docs/SOFTWARE_DESIGN.md` — read that for full component
> details, algorithms, quarterly resolution design, and configuration reference.
> This file is a compact agent-oriented summary for quick context loading.

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
  dp_battery_algorithm.py    ← Optimization engine (dynamic programming)
  ha_api_controller.py       ← HA sensor/device interface + METHOD_SENSOR_MAP
  sensor_collector.py        ← Data aggregation from InfluxDB + HA
  price_manager.py           ← Electricity pricing (Nordpool / Octopus)
  dp_schedule.py             ← Schedule data structures for DP optimization
  health_check.py            ← System validation utilities
  exceptions.py              ← All custom exception types (add new ones here)
        ↓
Home Assistant API + Growatt Inverter
```

## Hourly Update Cycle

1. Scheduler triggers `BatterySystemManager.update_battery_schedule()`
2. `SensorCollector` reads current energy data from InfluxDB + HA
3. `PriceManager` fetches/caches electricity spot prices
4. `optimize_battery_schedule()` generates optimal schedule for remaining horizon
5. `InverterController` subclass converts schedule to hardware-specific commands
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
| `GET /api/debug` | Full debug data export (used for mock HA scenarios) |

## Key Data Models (`backend/api_dataclasses.py`)

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
    is_required=True,            # True → failure = ERROR, False → failure = WARNING
    controller=self.ha_controller,
    all_methods=battery_methods,
)
```

Severity is derived from `is_required` — no separate `required_methods` parameter.
Never implement custom health check logic — always use `perform_health_check()`.

## Settings

Stored in `/data/bess_settings.json`, managed via the settings API.
`config.yaml` (root) controls only the InfluxDB connection and add-on schema.
Current version is the `version:` field in `config.yaml`.

## Bug Reproduction

When a user provides a debug log, bugs can be reproduced exactly using mock HA.
See `docs/agents/testing.md` for the full workflow.
