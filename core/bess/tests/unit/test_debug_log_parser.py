"""Regression test for debug_log_parser.py's `## Raw Schedule JSON (deep
debugging)` section, discovered while investigating issue #313: this
section (present in real "compact" debug exports) holds the exact real
`input_data` (buy_price/sell_price/home_consumption/solar_production/
initial_soe/initial_cost_basis/horizon) an optimization run actually used --
the same data `DebugLogData.input_data`'s docstring already promises -- but
the parser only recognized `## Optimization Schedules` as a schedules
section, so `last_schedule`/`input_data` silently came back empty for any
log using this header instead, with no error raised."""

from core.bess.tests.debug_log_parser import parse_debug_log

_RAW_SCHEDULE_LOG = """### Battery Settings

```json
{"total_capacity": 15.0, "min_soc": 47.0}
```

## Raw Schedule JSON (deep debugging)

<details>
<summary>Full Schedule JSON (all runs)</summary>

```json
[
  {
    "timestamp": "2026-07-13 15:45:00.587585+02:00",
    "optimization_period": 63,
    "optimization_result": {
      "input_data": {
        "buy_price": [0.3, 0.31],
        "sell_price": [0.08, 0.09],
        "home_consumption": [0.5, 0.4],
        "solar_production": [0.9, 0.7],
        "initial_soe": 15.0,
        "initial_cost_basis": 0.035,
        "horizon": 2
      }
    }
  }
]
```

</details>
"""


def test_raw_schedule_json_section_populates_input_data(tmp_path):
    log_path = tmp_path / "debug.md"
    log_path.write_text(_RAW_SCHEDULE_LOG)

    log = parse_debug_log(str(log_path))

    assert (
        log.input_data
    ), "Expected input_data to be populated from the Raw Schedule JSON section"
    assert log.input_data["initial_soe"] == 15.0
    assert log.input_data["initial_cost_basis"] == 0.035
    assert log.input_data["horizon"] == 2
    assert log.input_data["buy_price"] == [0.3, 0.31]
    assert log.optimization_period == 63


_HA_STATISTICS_LOG = """### Battery Settings

```json
{"total_capacity": 15.0, "min_soc": 47.0}
```

## HA Statistics (recorder replay data)

**Statistic ID**: sensor.pv_growatt_total_load_energy

**Entries**: 2

```json
{
  "statistic_id": "sensor.pv_growatt_total_load_energy",
  "stats": [
    {"start": "2026-07-10T08:00:00+02:00", "change": 1.2},
    {"start": "2026-07-10T09:00:00+02:00", "change": 0.8}
  ]
}
```
"""


def test_ha_statistics_section_populates_raw_recorder_data(tmp_path):
    log_path = tmp_path / "debug.md"
    log_path.write_text(_HA_STATISTICS_LOG)

    log = parse_debug_log(str(log_path))

    assert log.ha_statistics, "Expected ha_statistics to be populated"
    assert log.ha_statistics["statistic_id"] == "sensor.pv_growatt_total_load_energy"
    assert len(log.ha_statistics["stats"]) == 2
    assert log.ha_statistics["stats"][0]["change"] == 1.2


# Regression test: the real "## System Health Status (point-in-time snapshot
# at export)" header (debug_report_formatter.py) has a parenthetical suffix
# that _SECTION_HEALTH_STATUS's exact-string match didn't account for, so the
# section-header scan never advanced past "## System Information" and the
# Health Status JSON block that follows got silently captured as if it were
# System Information -- overwriting the real system_info dict, and with it
# the timezone field every debug log actually carries. Found while replaying
# a real production debug log: from_debug_log.py reported "No timezone in
# log" even though the log's own "## System Information" section plainly had
# one, and the mock replay's day-boundary/price-lookup logic misbehaved as a
# result of falling back to local server time instead.
_SYSTEM_INFO_THEN_HEALTH_STATUS_LOG = """## System Information

```json
{"bess_version": "9.9.0", "timezone": "Europe/Stockholm"}
```

## System Health Status (point-in-time snapshot at export)

```json
{"timestamp": "2026-07-18T01:03:15", "system_mode": "demo", "checks": []}
```

### Battery Settings

```json
{"total_capacity": 15.0, "min_soc": 47.0}
```
"""


def test_health_status_header_does_not_overwrite_system_info(tmp_path):
    log_path = tmp_path / "debug.md"
    log_path.write_text(_SYSTEM_INFO_THEN_HEALTH_STATUS_LOG)

    log = parse_debug_log(str(log_path))

    assert log.timezone == "Europe/Stockholm"
    assert log.system_info == {"bess_version": "9.9.0", "timezone": "Europe/Stockholm"}
