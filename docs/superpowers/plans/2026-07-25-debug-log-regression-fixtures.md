# Debug-Log Regression Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a maintainer generate a committed, lean, plan-faithfulness-ready regression fixture directly from a user's debug bundle (tagged with the issue/PR it pins), instead of hand-building synthetic arrays or hardcoding real values as giant inline Python literals.

**Architecture:** Extend the existing `scripts/mock_ha/scenarios/from_debug_log.py` generator with an optional `--issue`/`--pr` flag that, using data it already parses, additionally writes a lean numeric-only fixture into the existing `core/bess/tests/unit/data/` convention. Extend the shared scenario-loading helper (`core/bess/tests/helpers.py::_scenario_inputs`) to accept direct final `buy_price`/`sell_price` (what a debug log actually recorded) as an alternative to the existing `base_prices` + markup-config path, and to pass through `initial_cost_basis`. Fix `core/bess/tests/unit/test_scenarios.py`'s separate, duplicated scenario-loading logic to delegate to the same shared helper instead of reimplementing it, so both code paths gain the new capability at once and stop drifting apart (they already had one real divergence: `spot_multiplier`/`export_spot_multiplier` support existed only in the test_scenarios.py copy).

**Tech Stack:** Python, pytest, argparse, existing `core.bess.tests.debug_log_parser.parse_debug_log`.

## Global Constraints

- `buy_price`/`sell_price` in the new fixture format are **final** prices (from `log.input_data`), not `base_prices` — exact replay of what the optimizer saw, immune to future markup-formula drift. (Spec §2)
- Fully backward compatible: every existing `data/*.json` file has no `buy_price`/`sell_price` keys and no `initial_cost_basis`, so it must take the unchanged `base_prices` path with identical output. (Spec §3)
- No new parsing logic in the generator — the regression-fixture writer reuses `log.input_data`/`log.battery_settings`, already produced by the existing `parse_debug_log()` call. (Spec §1)
- Do not retrofit PR #391's test, do not touch `scripts/mock_ha/scenarios/` `.gitignore` rules, do not clean up the orphaned `unit/fixtures/issue_231_real_debug_export.json`. (Spec "Out of scope")
- New fixture filenames: `regression_YYYY_MM_DD_HHMMSS.json`, timestamp derived from the debug log filename, same convention as existing `realworld_*.json`. (Spec §2)

---

### Task 1: Extend `_scenario_inputs` for direct prices, cost basis, and spot-multiplier parity

**Files:**
- Modify: `core/bess/tests/helpers.py:23-70` (`_scenario_inputs`)
- Test: `core/bess/tests/unit/test_scenario_helpers.py` (new file)

**Interfaces:**
- Consumes: nothing new — `core.bess.settings.BatterySettings`, `core.bess.price_manager.{PriceManager, MockSource}` already imported in `helpers.py`.
- Produces: `_scenario_inputs(scenario: dict) -> dict` gains support for `scenario["buy_price"]`/`scenario["sell_price"]` (used verbatim when present), `scenario["battery"]["initial_cost_basis"]` (passed through as the new `"initial_cost_basis"` key in the returned dict, `None` if absent), and `scenario["price_data"]["spot_multiplier"]`/`["export_spot_multiplier"]` (applied via `PriceManager` when using the `base_prices` path). Every existing key in the returned dict (`buy_price`, `sell_price`, `home_consumption`, `solar_production`, `initial_soe`, `battery_settings`, `period_duration_hours`) keeps its exact current meaning. This is what Task 2 and Task 3 both build on.

- [ ] **Step 1: Write the failing tests**

Create `core/bess/tests/unit/test_scenario_helpers.py`:

```python
"""Tests for core.bess.tests.helpers._scenario_inputs's price/battery
derivation -- covering the buy_price/sell_price direct-input path and
initial_cost_basis pass-through added for debug-log-derived regression
fixtures, and confirming spot_multiplier/export_spot_multiplier support
(previously only present in test_scenarios.py's separate, now-removed
duplicate of this logic) still works after unification. See
docs/superpowers/specs/2026-07-25-debug-log-regression-fixtures-design.md.
"""

import pytest

from core.bess.tests.helpers import _scenario_inputs


def _battery(**overrides):
    battery = {
        "max_soe_kwh": 15.0,
        "min_soe_kwh": 1.8,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.035,
        "initial_soe": 1.65,
    }
    battery.update(overrides)
    return battery


def test_direct_buy_sell_price_used_verbatim_without_price_manager():
    """A scenario with buy_price/sell_price keys must use them exactly as
    given, bypassing PriceManager/base_prices entirely -- this is what lets
    a fixture carry the exact final prices an optimizer run actually saw."""
    scenario = {
        "buy_price": [0.5, 0.6],
        "sell_price": [-0.01, -0.02],
        "home_consumption": [0.2, 0.2],
        "solar_production": [0.5, 0.5],
        "battery": _battery(),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["buy_price"] == [0.5, 0.6]
    assert inputs["sell_price"] == [-0.01, -0.02]


def test_base_prices_path_unaffected_when_no_direct_prices_given():
    """Existing base_prices + PriceManager derivation must be unchanged for
    scenarios that don't set buy_price/sell_price."""
    scenario = {
        "base_prices": [0.3, 0.3],
        "home_consumption": [0.2, 0.2],
        "solar_production": [0.0, 0.0],
        "battery": _battery(),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["buy_price"][0] > scenario["base_prices"][0]  # markup applied
    assert len(inputs["buy_price"]) == 2


def test_initial_cost_basis_passed_through_when_present():
    scenario = {
        "buy_price": [0.5],
        "sell_price": [0.1],
        "home_consumption": [0.2],
        "solar_production": [0.0],
        "battery": _battery(initial_cost_basis=0.035),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["initial_cost_basis"] == 0.035


def test_initial_cost_basis_defaults_to_none_when_absent():
    scenario = {
        "buy_price": [0.5],
        "sell_price": [0.1],
        "home_consumption": [0.2],
        "solar_production": [0.0],
        "battery": _battery(),
    }

    inputs = _scenario_inputs(scenario)

    assert inputs["initial_cost_basis"] is None


def test_spot_multiplier_still_applied_via_base_prices_path():
    """Regression: before this change, helpers._scenario_inputs silently
    dropped price_data's spot_multiplier/export_spot_multiplier -- only
    test_scenarios.py's separate build_scenario_inputs applied them.
    core/bess/tests/unit/data/realworld_2026_07_13_155212.json relies on
    spot_multiplier. Task 2 makes test_scenarios.py delegate to this same
    function, so this must hold here too."""
    base_price_data = {
        "markup_rate": 0.0,
        "vat_multiplier": 1.0,
        "additional_costs": 0.0,
        "tax_reduction": 0.0,
    }
    scenario_without = {
        "base_prices": [1.0],
        "home_consumption": [0.2],
        "solar_production": [0.0],
        "battery": _battery(),
        "price_data": base_price_data,
    }
    scenario_with = {
        **scenario_without,
        "price_data": {**base_price_data, "spot_multiplier": 2.0},
    }

    buy_without = _scenario_inputs(scenario_without)["buy_price"][0]
    buy_with = _scenario_inputs(scenario_with)["buy_price"][0]

    assert buy_with == pytest.approx(buy_without * 2.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenario_helpers.py -v`
Expected: `test_direct_buy_sell_price_used_verbatim_without_price_manager` and the two `initial_cost_basis` tests FAIL with `KeyError: 'base_prices'` (the current code unconditionally reads `scenario["base_prices"]`); `test_spot_multiplier_still_applied_via_base_prices_path` FAILS with an assertion mismatch (spot_multiplier not applied); `test_base_prices_path_unaffected_when_no_direct_prices_given` PASSES already (that's fine — it's the safety-net test for the untouched path).

- [ ] **Step 3: Implement the minimal change**

Replace `_scenario_inputs` in `core/bess/tests/helpers.py:23-70` with:

```python
def _scenario_inputs(scenario: dict):
    """Build optimizer inputs from a scenario dict. Shared by run_scenario and
    run_scenario_realized so plan (P) and realized (R) use identical inputs.

    Two price inputs are supported: a scenario with `buy_price`/`sell_price`
    keys uses those directly -- the exact final prices an optimizer run saw
    (e.g. from a debug log's input_data) -- otherwise `base_prices` is run
    through PriceManager as before, using `price_data` markup config
    (including optional spot_multiplier/export_spot_multiplier) if present.
    """
    battery = scenario["battery"]

    battery_settings = BatterySettings(
        total_capacity=battery["max_soe_kwh"],
        min_soc=(battery["min_soe_kwh"] / battery["max_soe_kwh"]) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=battery["max_charge_power_kw"],
        max_discharge_power_kw=battery["max_discharge_power_kw"],
        efficiency_charge=battery["efficiency_charge"],
        efficiency_discharge=battery["efficiency_discharge"],
        cycle_cost_per_kwh=battery["cycle_cost_per_kwh"],
        inverter_max_ac_power_kw=battery.get("inverter_max_ac_power_kw", 0.0),
        inverter_ac_power_margin=battery.get("inverter_ac_power_margin", 0.0),
    )

    if "buy_price" in scenario and "sell_price" in scenario:
        buy_price = scenario["buy_price"]
        sell_price = scenario["sell_price"]
    else:
        base_prices = scenario["base_prices"]
        price_data = scenario.get("price_data")

        if price_data:
            markup_rate = price_data["markup_rate"]
            vat_multiplier = price_data["vat_multiplier"]
            additional_costs = price_data["additional_costs"]
            tax_reduction = price_data["tax_reduction"]
            # Optional -- default to PriceManager's own default (1.0, no
            # adjustment) so existing fixtures that don't set these are
            # unaffected.
            spot_multiplier = price_data.get("spot_multiplier", 1.0)
            export_spot_multiplier = price_data.get("export_spot_multiplier", 1.0)
        else:
            markup_rate = MARKUP_RATE
            vat_multiplier = VAT_MULTIPLIER
            additional_costs = ADDITIONAL_COSTS
            tax_reduction = TAX_REDUCTION
            spot_multiplier = 1.0
            export_spot_multiplier = 1.0

        price_manager = PriceManager(
            MockSource(base_prices),
            markup_rate=markup_rate,
            vat_multiplier=vat_multiplier,
            additional_costs=additional_costs,
            tax_reduction=tax_reduction,
            area="SE4",
            spot_multiplier=spot_multiplier,
            export_spot_multiplier=export_spot_multiplier,
        )
        buy_price = price_manager.get_buy_prices(raw_prices=base_prices)
        sell_price = price_manager.get_sell_prices(raw_prices=base_prices)

    return {
        "buy_price": buy_price,
        "sell_price": sell_price,
        "home_consumption": scenario["home_consumption"],
        "solar_production": scenario["solar_production"],
        "initial_soe": battery["initial_soe"],
        "initial_cost_basis": battery.get("initial_cost_basis"),
        "battery_settings": battery_settings,
        "period_duration_hours": scenario.get("period_duration_hours", 1.0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenario_helpers.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Run the full fast suite to confirm no regression**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: same pass count as before this change, plus the 5 new tests (no failures — `run_scenario`/`run_scenario_realized` both call `_scenario_inputs` and spread its return dict into `optimize_battery_schedule(**inp)`, which already accepts `initial_cost_basis=None`, so the new key is harmless for every existing caller).

- [ ] **Step 6: Commit**

```bash
git add core/bess/tests/helpers.py core/bess/tests/unit/test_scenario_helpers.py
git commit -m "feat: support direct buy/sell prices and cost basis in scenario helper

Lets a scenario fixture carry the exact final prices a debug-log-derived
optimizer run saw (buy_price/sell_price), instead of only pre-markup
base_prices + markup config. Also passes through battery.initial_cost_basis
(previously dropped) and applies price_data's spot_multiplier/
export_spot_multiplier on the base_prices path (previously only handled by
test_scenarios.py's separate copy of this logic, fixed by Task 2)."
```

---

### Task 2: Fix `test_scenarios.py`'s duplicated scenario-loading logic

**Files:**
- Modify: `core/bess/tests/unit/test_scenarios.py:1-134` (imports, `build_scenario_inputs`, `test_all_scenarios`'s horizon derivation)

**Interfaces:**
- Consumes: `core.bess.tests.helpers._scenario_inputs` (Task 1).
- Produces: `build_scenario_inputs(scenario_name)` keeps its exact current return signature — `(scenario, battery_settings, buy_prices, sell_prices, period_duration_hours)` — unchanged, so its 4 existing callers (`test_all_scenarios`, `test_gate_never_substitutes_a_worse_fallback` in this file; `test_dp_breakpoint_search.py`; `test_dp_no_guardrails.py`) need no changes. This is what makes any future `regression_*.json` fixture (using `buy_price`/`sell_price` instead of `base_prices`) work with `test_scenarios.py`'s existing generic `test_all_scenarios` loop without it crashing on a missing `base_prices` key.

- [ ] **Step 1: Write the failing test**

This is a refactor of existing logic (not new behavior on its own — new behavior is covered by Task 1's tests), so the test here is a safety net proving the refactor doesn't change output for a real existing fixture. Add to `core/bess/tests/unit/test_scenarios.py`, near `build_scenario_inputs`:

```python
def test_build_scenario_inputs_matches_shared_scenario_inputs_directly():
    """Safety net for delegating build_scenario_inputs to the shared
    helpers._scenario_inputs (#269 follow-up, avoids the two copies of this
    logic drifting apart again -- see
    docs/superpowers/specs/2026-07-25-debug-log-regression-fixtures-design.md):
    output must be identical to calling the shared helper directly, for a
    real existing fixture."""
    from core.bess.tests.helpers import _scenario_inputs

    scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(
        "realworld_2026_03_24_225535"
    )
    expected = _scenario_inputs(scenario)

    assert buy_prices == expected["buy_price"]
    assert sell_prices == expected["sell_price"]
    assert dt == expected["period_duration_hours"]
    assert battery_settings.max_soe_kwh == expected["battery_settings"].max_soe_kwh
    assert battery_settings.min_soe_kwh == expected["battery_settings"].min_soe_kwh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py::test_build_scenario_inputs_matches_shared_scenario_inputs_directly -v`
Expected: FAIL — `test_scenarios.py`'s current `build_scenario_inputs` doesn't call `_scenario_inputs` at all, but since it currently implements the *same* math, this specific assertion may actually already pass by coincidence for this one fixture (it has no `spot_multiplier`). If it passes, that's fine — the important verification is Step 4 after the refactor, and Step 5's full-file run. Proceed to Step 3 either way; the goal is the delegation itself, not a red/green cycle on this particular fixture.

- [ ] **Step 3: Implement the minimal change**

In `core/bess/tests/unit/test_scenarios.py`, replace the imports block (lines 9-35) with:

```python
import json
import logging
import os
from pathlib import Path

import pytest

from core.bess.dp_battery_algorithm import (
    optimize_battery_schedule,
    print_optimization_results,
)
from core.bess.models import EconomicSummary, PeriodData
from core.bess.tests.helpers import (
    _scenario_inputs,
    assert_intent_absent,
    assert_intent_present,
    assert_physical_constraints,
    assert_savings_positive,
    get_intent_distribution,
)
```

(Drops the now-unused `price_manager`/`settings` imports — `PriceManager`, `MockSource`, `ADDITIONAL_COSTS`, `MARKUP_RATE`, `TAX_REDUCTION`, `VAT_MULTIPLIER`, `BatterySettings` — since `build_scenario_inputs` no longer implements that logic itself.)

Replace `build_scenario_inputs` (lines 64-120) with:

```python
def build_scenario_inputs(scenario_name):
    """Load a scenario file and derive battery settings + buy/sell prices.

    Thin wrapper around helpers._scenario_inputs so every consumer of
    scenario files (this module and its several importers) shares one
    derivation path -- including the buy_price/sell_price direct-input and
    spot_multiplier handling added for debug-log-derived regression
    fixtures.
    """
    scenario = load_test_scenario(scenario_name)
    inputs = _scenario_inputs(scenario)
    return (
        scenario,
        inputs["battery_settings"],
        inputs["buy_price"],
        inputs["sell_price"],
        inputs["period_duration_hours"],
    )
```

In `test_all_scenarios` (originally lines 123-159), replace the horizon derivation:

```python
    # Determine the actual horizon from the scenario data
    horizon = len(scenario["base_prices"])
```

with:

```python
    # Determine the actual horizon from the scenario data -- use the
    # derived buy_prices (always present) rather than base_prices (only
    # present for non-regression fixtures using the markup-config path).
    horizon = len(buy_prices)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py::test_build_scenario_inputs_matches_shared_scenario_inputs_directly -v`
Expected: PASS.

- [ ] **Step 5: Run the full scenario test file and fast suite**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -m slow -v`
Expected: every `test_all_scenarios[*]` and `test_gate_never_substitutes_a_worse_fallback[*]` case still PASSES (same set as before the refactor — this file is `pytestmark = pytest.mark.slow`).

Run: `.venv/bin/pytest core/bess/tests/unit/test_dp_breakpoint_search.py core/bess/tests/unit/test_dp_no_guardrails.py -m slow -q`
Expected: all PASS (these import `build_scenario_inputs` directly; confirms its unchanged tuple contract still works for them).

Run: `.venv/bin/ruff check core/bess/tests/unit/test_scenarios.py`
Expected: clean (confirms the dropped imports are fully unused, no lint errors).

- [ ] **Step 6: Commit**

```bash
git add core/bess/tests/unit/test_scenarios.py
git commit -m "refactor: delegate test_scenarios.py's scenario loading to the shared helper

build_scenario_inputs duplicated helpers._scenario_inputs's battery/price
derivation logic, and had already drifted (spot_multiplier support existed
only here). Delegating to the shared helper fixes the drift and means any
new regression_*.json fixture using buy_price/sell_price (Task 1) works
with the existing test_all_scenarios loop without a KeyError on the
now-optional base_prices key."
```

---

### Task 3: Add `--issue`/`--pr` flag to the debug-log scenario generator

**Files:**
- Modify: `scripts/mock_ha/scenarios/from_debug_log.py`
- Test: `core/bess/tests/unit/test_from_debug_log_regression_fixture.py` (new file)

**Interfaces:**
- Consumes: `core.bess.tests.debug_log_parser.parse_debug_log` (already imported), specifically `log.input_data` (dict with `buy_price`, `sell_price`, `home_consumption`, `solar_production`, `initial_soe`, `initial_cost_basis`, `horizon`) and `log.battery_settings` (dict with `max_soe_kwh`, `min_soe_kwh`, `max_charge_power_kw`, `max_discharge_power_kw`, `efficiency_charge`, `efficiency_discharge`, `cycle_cost_per_kwh`, `inverter_max_ac_power_kw`, `inverter_ac_power_margin`).
- Produces: `generate_scenario(log_path: str, issue: int | None = None, pr: int | None = None) -> None` (signature gains two optional kwargs, default `None` preserves current behavior exactly). CLI gains `--issue N [--pr M]`.

- [ ] **Step 1: Write the failing test**

Create `core/bess/tests/unit/test_from_debug_log_regression_fixture.py`:

```python
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

_MINIMAL_DEBUG_LOG = f"""### Battery Settings

```json
{{"total_capacity": 15.0, "min_soc": 12.0, "max_soc": 100.0, "max_charge_power_kw": 5.0, "max_discharge_power_kw": 5.0, "efficiency_charge": 0.97, "efficiency_discharge": 0.95, "cycle_cost_per_kwh": 0.035, "min_soe_kwh": 1.8, "max_soe_kwh": 15.0}}
```

## Raw Schedule JSON (deep debugging)

<details>
<summary>Full Schedule JSON (all runs)</summary>

```json
[
  {{
    "timestamp": "9999-01-01 00:00:00.000000+02:00",
    "optimization_period": 36,
    "optimization_result": {{
      "input_data": {{
        "buy_price": [0.22, 0.21],
        "sell_price": [-0.0014, -0.0128],
        "home_consumption": [0.135, 0.2],
        "solar_production": [0.52, 0.65],
        "initial_soe": 1.65,
        "initial_cost_basis": 0.035,
        "horizon": 2
      }}
    }}
  }}
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
    fixture_path = REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json"

    try:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), str(log_path), "--issue", "269", "--pr", "391"],
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
    fixture_path = REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json"

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
    fixture_path = REGRESSION_DATA_DIR / f"regression_{output_name.replace('-', '_')}.json"

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_from_debug_log_regression_fixture.py -v`
Expected: `test_issue_flag_writes_lean_regression_fixture` and `test_pr_flag_optional_defaults_to_null` FAIL — the script currently exits with an argparse-unrecognized-argument error (or, since it doesn't use argparse yet, `sys.argv[1]` usage means `--issue`/`269`/`--pr`/`391` are simply ignored as extra unused argv entries today, so the fixture file is never written and `fixture_path.exists()` is `False`). `test_without_issue_flag_no_regression_fixture_written` PASSES already (no flag support means no fixture is written today either way) — that's fine, it's the backward-compatibility safety net.

- [ ] **Step 3: Implement the minimal change**

In `scripts/mock_ha/scenarios/from_debug_log.py`, add `import argparse` to the top imports (alongside `import json`), then change the `generate_scenario` signature and add the new writer function. Change:

```python
def generate_scenario(log_path: str) -> None:
```

to:

```python
def generate_scenario(log_path: str, issue: int | None = None, pr: int | None = None) -> None:
```

Add a new function above `generate_scenario` (after `_quarterly_to_hourly_detail`):

```python
def _write_regression_fixture(
    log, log_path: str, output_name: str, issue: int, pr: int | None
) -> None:
    """Write the lean, committed plan-faithfulness regression fixture
    derived from a debug log's input_data -- a numeric-only sibling of the
    full E2E scenario this script also writes, consumed by
    core/bess/tests/unit/test_scenarios.py's generic loop and any dedicated
    regression test. See
    docs/superpowers/specs/2026-07-25-debug-log-regression-fixtures-design.md.
    """
    d = log.input_data
    if not d:
        print(
            "Error: --issue requires input_data in the debug log (buy_price/"
            "sell_price/home_consumption/solar_production/initial_soe) -- "
            "this log doesn't have it."
        )
        sys.exit(1)

    bs = log.battery_settings
    fixture_name = f"regression_{output_name.replace('-', '_')}"
    fixture = {
        "name": fixture_name,
        "description": f"Issue #{issue}",
        "issue": issue,
        "pr": pr,
        "source": f"debug_log/{Path(log_path).name}",
        "resolution": "quarterly",
        "period_duration_hours": 0.25,
        "buy_price": d["buy_price"],
        "sell_price": d["sell_price"],
        "home_consumption": d["home_consumption"],
        "solar_production": d["solar_production"],
        "battery": {
            "max_soe_kwh": bs["max_soe_kwh"],
            "min_soe_kwh": bs["min_soe_kwh"],
            "max_charge_power_kw": bs["max_charge_power_kw"],
            "max_discharge_power_kw": bs["max_discharge_power_kw"],
            "efficiency_charge": bs["efficiency_charge"],
            "efficiency_discharge": bs["efficiency_discharge"],
            "cycle_cost_per_kwh": bs["cycle_cost_per_kwh"],
            "inverter_max_ac_power_kw": bs.get("inverter_max_ac_power_kw", 0.0),
            "inverter_ac_power_margin": bs.get("inverter_ac_power_margin", 0.0),
            "initial_soe": d["initial_soe"],
            "initial_cost_basis": d.get("initial_cost_basis"),
        },
    }

    # Reuses the module-level `repo_root` already computed at the top of this
    # file (for the `sys.path.insert` import of `core.bess.tests...`).
    data_dir = repo_root / "core" / "bess" / "tests" / "unit" / "data"
    fixture_path = data_dir / f"{fixture_name}.json"
    with open(fixture_path, "w") as f:
        json.dump(fixture, f, indent=2)
    print(f"Wrote regression fixture: {fixture_path}")
```

In `generate_scenario`, after the existing block that writes the E2E scenario (the `with open(scenario_path, "w") as f: json.dump(...)` / `print(f"Wrote scenario: {scenario_path}")` lines near the end of the function, before the final `print(f"\nRun:  ./mock-run.sh {output_name}")` block), add:

```python
    if issue is not None:
        _write_regression_fixture(log, log_path, output_name, issue, pr)
```

Replace the `if __name__ == "__main__":` block at the bottom with:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a mock_ha scenario JSON (and optionally a lean "
        "plan-faithfulness regression fixture) from a BESS debug log file."
    )
    parser.add_argument("log_path", help="Path to the debug log .md file")
    parser.add_argument(
        "--issue",
        type=int,
        default=None,
        help="GitHub issue number this debug log diagnoses -- when given, "
        "also writes a lean regression fixture to core/bess/tests/unit/data/",
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help="GitHub PR number that fixes --issue (optional, can be added "
        "later by re-running with both flags)",
    )
    args = parser.parse_args()

    generate_scenario(args.log_path, issue=args.issue, pr=args.pr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_from_debug_log_regression_fixture.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Confirm existing manual usage still works**

Run: `python scripts/mock_ha/scenarios/from_debug_log.py --help`
Expected: usage text shows `log_path`, `--issue`, `--pr`; exits 0.

Run: `.venv/bin/ruff check scripts/mock_ha/scenarios/from_debug_log.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/mock_ha/scenarios/from_debug_log.py core/bess/tests/unit/test_from_debug_log_regression_fixture.py
git commit -m "feat: --issue/--pr flag writes a lean regression fixture from a debug log

Reuses the log.input_data/log.battery_settings the script already parses
to also write a numeric-only fixture into core/bess/tests/unit/data/,
tagged with the issue/PR it pins -- consumed by test_scenarios.py's
generic loop and any dedicated regression test via helpers._scenario_inputs
(Task 1)."
```

---

### Task 4: Document the new fixture category and generator usage

**Files:**
- Modify: `core/bess/tests/unit/data/README.md`
- Modify: `docs/agents/testing.md` (the existing "Bug Reproduction with Mock HA" section)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Update `core/bess/tests/unit/data/README.md`**

Insert a new section after "### Sample Scenarios" and before "## File Structure":

```markdown
### Realworld Scenarios

- **Naming Convention**: `realworld_YYYY_MM_DD_HHMMSS.json`
- **Purpose**: Real debug-log-derived data for general algorithm testing (not tied to a specific bug fix)
- **Content**: `source` field records the originating debug log; `base_prices` reconstructed from the log's real prices

### Regression Scenarios

- **Naming Convention**: `regression_YYYY_MM_DD_HHMMSS.json`, timestamp matching the source debug log's filename
- **Purpose**: Pin a specific bug fix's real-world reproduction as a permanent regression fixture, generated directly from the reporter's debug bundle
- **Content**: `issue`/`pr` fields identify what this fixture pins; `buy_price`/`sell_price` are the *final* prices the optimizer actually saw that day (not `base_prices` + markup config) — exact replay, immune to a later markup-formula change silently altering what the fixture means
- **Generated by**: `python scripts/mock_ha/scenarios/from_debug_log.py <debug-log.md> --issue <N> [--pr <M>]` — see `docs/agents/testing.md`
- **Note**: covered automatically by `test_scenarios.py`'s generic `test_all_scenarios` loop (physical-constraint/savings-positive checks); the bug's *specific* fixed behavior still needs its own dedicated test loading this fixture by name
```

Update the "## File Structure" section's field list to add the two new optional fields:

```markdown
- `name`: Scenario identifier (same as filename without extension)
- `description`: Brief description of the scenario
- `base_prices`: 24 hourly Nordpool electricity prices (SEK/kWh excl. VAT) -- OR `buy_price`/`sell_price` directly (regression scenarios; see above)
- `home_consumption`: 24 hourly home consumption values (kWh)
- `solar_production`: 24 hourly solar production values (kWh)
- `battery`: Battery parameters (capacity, efficiency, etc.) -- optionally `initial_cost_basis`
- `expected_results`: Expected optimization results
- `issue`/`pr`: GitHub issue/PR numbers this fixture pins (regression scenarios only)
```

- [ ] **Step 2: Update `docs/agents/testing.md`**

Find the existing "Bug Reproduction with Mock HA" code block (starting `# 1. Generate a scenario from the debug log the user provided`) and add a line after it noting the new flag:

```markdown
# For a DP/control-mapping fix that needs a fast, no-container plan-faithfulness
# regression test (see .claude/skills/implement-issue/SKILL.md's TDD step),
# also tag the log with the issue it diagnoses -- this additionally writes a
# lean fixture to core/bess/tests/unit/data/regression_<timestamp>.json:
python scripts/mock_ha/scenarios/from_debug_log.py <debug-log-file.md> --issue <N>
```

- [ ] **Step 3: Commit**

```bash
git add core/bess/tests/unit/data/README.md docs/agents/testing.md
git commit -m "docs: document regression_*.json fixture category and --issue flag"
```

---

### Task 5: Dogfood against issue #269's real debug bundle

**Files:**
- Create: `core/bess/tests/unit/data/regression_2026_07_25_090230.json` (generated, not hand-written)

**Interfaces:**
- Consumes: Task 3's `--issue`/`--pr` flag; a copy of Frank-Leysen's debug bundle from issue #269 (`bess-debug-2026-07-25-090230.md`, fetchable via `gh gist view 499ff1b50749ef6f73cfe1a2272d4dd1 -f bess-debug-2026-07-25-090230.md`, the same one used to diagnose and verify PR #391).
- Produces: a real, committed regression fixture proving the whole chain (generator → `core/bess/tests/unit/data/` → `test_scenarios.py`'s generic loop) works end-to-end on real data, not just the synthetic log from Task 3's tests. This is verification, not a new dedicated regression test for #269's specific bug (that already exists in PR #391 with its own inline data — do not duplicate it here, per the Global Constraints).

- [ ] **Step 1: Fetch the real debug bundle**

```bash
mkdir -p /tmp/issue-269-bundle
gh gist view 499ff1b50749ef6f73cfe1a2272d4dd1 -f bess-debug-2026-07-25-090230.md > /tmp/issue-269-bundle/bess-debug-2026-07-25-090230.md
```

- [ ] **Step 2: Run the generator with --issue/--pr**

```bash
python scripts/mock_ha/scenarios/from_debug_log.py /tmp/issue-269-bundle/bess-debug-2026-07-25-090230.md --issue 269 --pr 391
```

Expected output includes `Wrote regression fixture: .../core/bess/tests/unit/data/regression_2026_07_25_090230.json` in addition to the existing `Wrote scenario: .../scripts/mock_ha/scenarios/2026-07-25-090230.json` line.

- [ ] **Step 3: Inspect the generated fixture**

```bash
python3 -c "
import json
d = json.load(open('core/bess/tests/unit/data/regression_2026_07_25_090230.json'))
print('issue', d['issue'], 'pr', d['pr'])
print('horizon', len(d['buy_price']))
print('initial_soe', d['battery']['initial_soe'], 'min_soe_kwh', d['battery']['min_soe_kwh'])
print('sell_price[0]', d['sell_price'][0])
"
```

Expected: `issue 269 pr 391`, `horizon 60`, `initial_soe 1.65 min_soe_kwh 1.8`, `sell_price[0]` ≈ `-0.0014` (matches the values already verified in PR #391's own test and this session's earlier manual inspection).

- [ ] **Step 4: Confirm it's picked up by the generic scenario loop**

```bash
.venv/bin/pytest "core/bess/tests/unit/test_scenarios.py::test_all_scenarios[regression_2026_07_25_090230]" -v -m slow
```

**Correction, discovered during execution:** Step 4 does NOT pass as originally
predicted here. `initial_soe=1.65 < min_soe_kwh=1.8` for this fixture is not a
data error — it's the exact below-floor-start condition issue #269/#391 is
about, and it's documented as an intentional, valid state by
`_soe_floor()`'s docstring (#233). `test_scenarios.py`'s generic SOE-bounds
check (lines ~200-218) has a static `min_soe_kwh` lower bound that no
existing fixture had ever violated, because none started below the floor
before this one. Steps 4-6 below are superseded by Task 5b, which relaxes
that bound and completes this task's remaining steps together with its own.
Do not execute Steps 4-6 as written — proceed to Task 5b instead.

- [ ] ~~Step 4: Confirm it's picked up by the generic scenario loop~~ — superseded by Task 5b
- [ ] ~~Step 5: Run the full fast + slow suites~~ — superseded by Task 5b
- [ ] ~~Step 6: Commit~~ — superseded by Task 5b

---

### Task 5b: Relax the SOE-bounds invariant for legitimate below-floor starts, commit the #269 fixture

**Files:**
- Modify: `core/bess/tests/unit/test_scenarios.py:200-218` (the SOE-bounds assertions in `test_all_scenarios`)
- Create: `core/bess/tests/unit/data/regression_2026_07_25_090230.json` (already generated on disk by Task 5's Steps 1-3, currently untracked — commit it here)

**Interfaces:**
- Consumes: `battery["min_soe_kwh"]`, `battery["initial_soe"]` (both already available as local variables in `test_all_scenarios` at the point of the assertion — `battery = scenario["battery"]` is set earlier in the function).
- Produces: the SOE-bounds lower bound becomes `min(battery["min_soe_kwh"], battery["initial_soe"])` instead of the static `battery["min_soe_kwh"]` — i.e., SOE must never drop *below its own starting point*, but is no longer required to always meet the configured floor. This is what lets `regression_2026_07_25_090230.json` (and any future fixture with a legitimately below-floor `initial_soe`) pass the existing generic loop without weakening the check for every other fixture (which all start at/above their floor today, so `min(min_soe_kwh, initial_soe) == min_soe_kwh` for them — zero behavior change).

- [ ] **Step 1: Confirm the failing test**

`core/bess/tests/unit/data/regression_2026_07_25_090230.json` already exists on disk in this worktree (generated by Task 5's Steps 1-3, currently untracked) — it is itself the RED test's fixture data; no new test function is needed, since `test_scenarios.py`'s existing `test_all_scenarios` is already parametrized over every file in `core/bess/tests/unit/data/` (`get_all_scenario_files()` globs `*.json`).

Run: `.venv/bin/pytest "core/bess/tests/unit/test_scenarios.py::test_all_scenarios[regression_2026_07_25_090230]" -v -m slow`

Expected: FAILS with `AssertionError: SOE start 1.65 kWh outside bounds [1.8, 15.0]`. This is the RED half of this task's TDD cycle; Step 4 below is the GREEN half, on the same test.

- [ ] **Step 2: Implement the minimal change**

In `core/bess/tests/unit/test_scenarios.py`, in `test_all_scenarios`, replace:

```python
    # Battery usage should be within physical constraints
    # Small tolerance for floating-point precision errors (e.g., np.arange producing 30.000000000000025)
    soe_tolerance = 1e-6
    for hour_data in result.period_data:
        # Access SOE directly - these are already in kWh
        soe_start_kwh = hour_data.energy.battery_soe_start  # Already in kWh
        soe_end_kwh = hour_data.energy.battery_soe_end  # Already in kWh

        # Validate SOE bounds in kWh (with tolerance for floating-point precision)
        assert (
            battery["min_soe_kwh"] - soe_tolerance
            <= soe_start_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE start {soe_start_kwh:.2f} kWh outside bounds [{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"
        assert (
            battery["min_soe_kwh"] - soe_tolerance
            <= soe_end_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE end {soe_end_kwh:.2f} kWh outside bounds [{battery['min_soe_kwh']}, {battery['max_soe_kwh']}]"
```

with:

```python
    # Battery usage should be within physical constraints
    # Small tolerance for floating-point precision errors (e.g., np.arange producing 30.000000000000025)
    soe_tolerance = 1e-6
    # A scenario may legitimately start below min_soe_kwh (e.g. a live sensor
    # reading under Min SOC, see dp_battery_algorithm.py's _soe_floor()
    # docstring, #233) -- the effective lower bound is the fixture's own
    # starting point in that case, not the configured floor. For every
    # fixture that starts at/above its floor (all of them until #269's
    # regression_2026_07_25_090230), this is identical to min_soe_kwh --
    # zero behavior change.
    effective_min_soe_kwh = min(battery["min_soe_kwh"], battery["initial_soe"])
    for hour_data in result.period_data:
        # Access SOE directly - these are already in kWh
        soe_start_kwh = hour_data.energy.battery_soe_start  # Already in kWh
        soe_end_kwh = hour_data.energy.battery_soe_end  # Already in kWh

        # Validate SOE bounds in kWh (with tolerance for floating-point precision)
        assert (
            effective_min_soe_kwh - soe_tolerance
            <= soe_start_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE start {soe_start_kwh:.2f} kWh outside bounds [{effective_min_soe_kwh}, {battery['max_soe_kwh']}]"
        assert (
            effective_min_soe_kwh - soe_tolerance
            <= soe_end_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE end {soe_end_kwh:.2f} kWh outside bounds [{effective_min_soe_kwh}, {battery['max_soe_kwh']}]"
```

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv/bin/pytest "core/bess/tests/unit/test_scenarios.py::test_all_scenarios[regression_2026_07_25_090230]" -v -m slow`

Expected: PASSES.

- [ ] **Step 4: Run the full scenario file and full suites to confirm no regression for existing fixtures**

Run: `.venv/bin/pytest core/bess/tests/unit/test_scenarios.py -m slow -v`
Expected: every `test_all_scenarios[*]` case still PASSES, including all pre-existing fixtures (confirms `effective_min_soe_kwh == min_soe_kwh` for them, i.e. zero behavior change).

Run: `.venv/bin/pytest -m "not slow" -q` then `.venv/bin/pytest -m slow -q`
Expected: both green, no regressions.

- [ ] **Step 5: Commit both the test fix and the fixture together**

```bash
git add core/bess/tests/unit/test_scenarios.py core/bess/tests/unit/data/regression_2026_07_25_090230.json
git commit -m "fix: tolerate a legitimate below-floor initial_soe in the generic SOE-bounds check

test_all_scenarios asserted every fixture's SOE always meets the configured
min_soe_kwh floor -- true for every fixture until issue #269's dogfood
fixture, whose initial_soe=1.65 is legitimately below its 1.8 kWh floor
(see dp_battery_algorithm.py's _soe_floor() docstring, #233). The effective
lower bound is now min(min_soe_kwh, initial_soe): SOE must never drop below
its own starting point, but a below-floor start is no longer rejected as a
data error. Identical behavior for every existing fixture (all start at/
above their floor already). Commits the #269 regression fixture generated
by Task 5, now passing."
```

---

## Final Verification

- [ ] Run `./scripts/quality-check.sh` — must pass (black/ruff clean, fast suite green).
- [ ] Run `.venv/bin/pytest -m slow -q` — must pass.
- [ ] Run `/code-review` on the full diff before opening a PR (per `docs/agents/workflow.md` and this session's established convention).
- [ ] Open a draft PR against `main` (this is a dev-tooling/test-infrastructure change, not a user-facing behavior change — no `CHANGELOG.md` entry needed, consistent with e.g. commit `e57e82c8`'s docs-only precedent).
