"""Tests for scripts/mock_ha/scenarios/from_debug_log.py's --issue/--pr
flag, which writes a lean plan-faithfulness regression fixture to
core/bess/tests/unit/data/ alongside the existing mock_ha E2E scenario.
See docs/superpowers/specs/2026-07-25-debug-log-regression-fixtures-design.md.

Runs the generator as a real subprocess (its own CLI contract, exactly as
a maintainer would invoke it) against a minimal synthetic debug log, using
a distinctive sentinel timestamp so the two files it writes into the real
scripts/mock_ha/scenarios/ and core/bess/tests/unit/data/ directories are
always cleaned up afterward, never colliding with real content.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR = REPO_ROOT / "scripts" / "mock_ha" / "scenarios" / "from_debug_log.py"
E2E_SCENARIOS_DIR = REPO_ROOT / "scripts" / "mock_ha" / "scenarios"
REGRESSION_DATA_DIR = REPO_ROOT / "core" / "bess" / "tests" / "unit" / "data"

_SENTINEL_TIMESTAMP = "9999-01-01-000000"

_MINIMAL_DEBUG_LOG = """### Battery Settings

```json
{"total_capacity": 15.0, "min_soc": 12.0, "max_soc": 100.0, "max_charge_power_kw": 5.0, "max_discharge_power_kw": 5.0, "efficiency_charge": 0.97, "efficiency_discharge": 0.95, "cycle_cost_per_kwh": 0.035, "min_soe_kwh": 1.8, "max_soe_kwh": 15.0}
```

## Raw Schedule JSON (deep debugging)

<details>
<summary>Full Schedule JSON (all runs)</summary>

```json
[
  {
    "timestamp": "9999-01-01 00:00:00.000000+02:00",
    "optimization_period": 36,
    "optimization_result": {
      "input_data": {
        "buy_price": [0.22, 0.21],
        "sell_price": [-0.0014, -0.0128],
        "home_consumption": [0.135, 0.2],
        "solar_production": [0.52, 0.65],
        "initial_soe": 1.65,
        "initial_cost_basis": 0.035,
        "horizon": 2
      }
    }
  }
]
```

</details>
"""


def _cleanup(output_name: str):
    (E2E_SCENARIOS_DIR / f"{output_name}.json").unlink(missing_ok=True)
    (REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json").unlink(
        missing_ok=True
    )


def test_issue_flag_writes_lean_regression_fixture(tmp_path):
    log_path = tmp_path / f"bess-debug-{_SENTINEL_TIMESTAMP}.md"
    log_path.write_text(_MINIMAL_DEBUG_LOG)
    output_name = _SENTINEL_TIMESTAMP
    fixture_path = (
        REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json"
    )

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                str(log_path),
                "--issue",
                "269",
                "--pr",
                "391",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        assert fixture_path.exists(), (
            f"--issue should write a regression fixture to {fixture_path}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        fixture = json.loads(fixture_path.read_text())

        assert fixture["issue"] == 269
        assert fixture["pr"] == 391
        assert fixture["source"] == f"debug_log/bess-debug-{_SENTINEL_TIMESTAMP}.md"
        assert fixture["buy_price"] == [0.22, 0.21]
        assert fixture["sell_price"] == [-0.0014, -0.0128]
        assert fixture["home_consumption"] == [0.135, 0.2]
        assert fixture["solar_production"] == [0.52, 0.65]
        assert fixture["battery"]["initial_soe"] == 1.65
        assert fixture["battery"]["initial_cost_basis"] == 0.035
        assert fixture["battery"]["max_soe_kwh"] == 15.0
        assert fixture["battery"]["min_soe_kwh"] == 1.8

        # The existing E2E scenario output must still be written, unaffected.
        assert (E2E_SCENARIOS_DIR / f"{output_name}.json").exists()
    finally:
        _cleanup(output_name)


def test_pr_flag_optional_defaults_to_null(tmp_path):
    log_path = tmp_path / f"bess-debug-{_SENTINEL_TIMESTAMP}.md"
    log_path.write_text(_MINIMAL_DEBUG_LOG)
    output_name = _SENTINEL_TIMESTAMP
    fixture_path = (
        REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json"
    )

    try:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), str(log_path), "--issue", "269"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        fixture = json.loads(fixture_path.read_text())
        assert fixture["issue"] == 269
        assert fixture["pr"] is None
    finally:
        _cleanup(output_name)


def test_without_issue_flag_no_regression_fixture_written(tmp_path):
    """Backward compatibility: omitting --issue must not write a regression
    fixture (existing usage, e.g. from mock-run.sh's own docstring, has no
    such flag)."""
    log_path = tmp_path / f"bess-debug-{_SENTINEL_TIMESTAMP}.md"
    log_path.write_text(_MINIMAL_DEBUG_LOG)
    output_name = _SENTINEL_TIMESTAMP
    fixture_path = (
        REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json"
    )

    try:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), str(log_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert not fixture_path.exists()
        assert (E2E_SCENARIOS_DIR / f"{output_name}.json").exists()
    finally:
        _cleanup(output_name)
