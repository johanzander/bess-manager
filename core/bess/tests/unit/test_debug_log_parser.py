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
