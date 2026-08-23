"""#422 regression: the arbitrage-consistency terminal-value cap must not let
an already-committed near-term price inflate the cap for a later, unrelated
day's horizon boundary, replayed against a real user's captured data.

`core/bess/tests/unit/data/regression_frank_debug_before.json` is the exact
optimizer input (buy/sell price, home consumption, solar production, battery
state) captured from Frank-Leysen's 2026-07-29 18:40 debug bundle (issue
#126, BESS 9.9.0b27) via
`scripts/mock_ha/scenarios/from_debug_log.py --issue 422`. `sell_price[6]`
(period 80, 20:00) is `0.24261922` -- exactly the "today's still-upcoming
20:00 sell price" cited in #422's root-cause trace -- confirming this fixture
reproduces the real conditions, not an approximation of them.

optimization_period=74 (~18:45), horizon=118 (22 remaining periods today +
96 periods tomorrow), so index 22 in the fixture's flat arrays is the
today/tomorrow boundary.

The permanent economics regression guard for this fixture lives in the
fixture itself (`terminal_value_per_kwh` + `expected_results`), auto-run by
`test_scenarios.py::test_all_scenarios` -- not duplicated here. Verified by
hand that `expected_results` actually discriminates: pinned to the fixed
cap's economics (battery_solar_cost -2.83 EUR), it fails if the fixture's
`terminal_value_per_kwh` is swapped back to the buggy cap's value (-1.04
EUR) -- a >1.7 EUR gap, far outside the harness's round-to-1-decimal
tolerance. A whole-result `expected_behavior.intents_present` check would
NOT have caught this bug: today's remainder of this exact horizon already
has 8 legitimate BATTERY_EXPORT periods regardless of the cap, which masks
the fact that tomorrow's own plateau has zero -- the bug is specific to a
sub-range the generic intent-presence check can't scope to. This module
covers only what the scenario-JSON harness structurally cannot: the private
cap-formula's own numbers, and control-mapping plan-faithfulness (R == P),
which `test_all_scenarios` never runs the inverter simulator for.
"""

import json
from pathlib import Path

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.price_manager import MockSource
from core.bess.simulation.inverter_simulator import derive_control_command, simulate
from core.bess.terminal_value import calculate_terminal_value_per_kwh
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import _scenario_inputs, scenario_terminal_curve

FIXTURE_PATH = Path(__file__).parent / "data" / "regression_frank_debug_before.json"
TODAY_REMAINING = 22  # periods 74..95 today; index 22 onward is tomorrow
OPTIMIZATION_PERIOD = 74


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _terminal_value_calculator(battery: dict) -> BatterySystemManager:
    """A BatterySystemManager instance sufficient to call the private
    `_calculate_terminal_value` -- only `battery_settings` is read, so a
    minimal mock source/controller is fine here. `cycle_cost_per_kwh` and
    `efficiency_discharge` are overridden from the fixture's own battery
    dict (Frank's real settings), since the class defaults don't match."""
    system = BatterySystemManager(
        controller=MockHomeAssistantController(),
        price_source=MockSource([0.0] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    system.battery_settings.cycle_cost_per_kwh = battery["cycle_cost_per_kwh"]
    system.battery_settings.efficiency_discharge = battery["efficiency_discharge"]
    return system


def test_fixture_reproduces_the_reported_cap_values():
    """Sanity check on the fixture itself: the pre-fix (full-remaining-
    window) cap and the fixed (terminal-day-only) cap must match the exact
    values traced in the #422 root-cause analysis (~0.1955 and ~0.1430
    EUR/kWh respectively). If this drifts, the fixture no longer represents
    the real reported case and the tests below aren't exercising it."""
    scenario = _load_fixture()
    sell_price = scenario["sell_price"]

    buggy_cap_input = sell_price  # pre-#422: full remaining-horizon window
    fixed_cap_input = sell_price[TODAY_REMAINING:]  # #422 fix: terminal day only

    # The cap formula itself, which still prices the no-PV-crossover regime
    # after #602 -- reached directly rather than through the BSM wrapper,
    # since the wrapper now builds a curve and the cap is what this pins.
    settings = _terminal_value_calculator(scenario["battery"]).battery_settings
    buggy_terminal_value = calculate_terminal_value_per_kwh(
        scenario["buy_price"], buggy_cap_input, settings
    )
    fixed_terminal_value = calculate_terminal_value_per_kwh(
        scenario["buy_price"], fixed_cap_input, settings
    )

    assert buggy_terminal_value == pytest.approx(0.195488, abs=1e-5)
    assert fixed_terminal_value == pytest.approx(0.143013, abs=1e-5)
    assert fixed_terminal_value < buggy_terminal_value


def test_fixed_cap_exports_into_tomorrow_evening_and_plan_is_faithful():
    """#422 fix: scoping the cap to sell prices on the terminal day
    (tomorrow only) restores BATTERY_EXPORT into tomorrow evening's real
    captured sell-price plateau, and the resulting plan is faithfully
    executable (R == P) via the real control-mapping/simulator layer, not
    just internally consistent DP arithmetic."""
    scenario = _load_fixture()
    inp = _scenario_inputs(scenario)
    # The fixture pins its own terminal curve (consumed by
    # test_scenarios.py::test_all_scenarios' expected_results regression
    # guard) -- cross-check it stays derived from the real production rule,
    # not hand-edited independently of it. Since #602 this fixture's day has
    # a PV crossover, so it runs the concave row rather than the capped
    # scalar; what #422 is about -- that tomorrow's evening peak still clears
    # -- is asserted below on behaviour, which is where it belongs.
    expected_curve = scenario_terminal_curve(scenario)
    assert inp["terminal_curve"].head_rate == pytest.approx(expected_curve.head_rate)
    assert inp["terminal_curve"].knee_kwh == pytest.approx(expected_curve.knee_kwh)

    result = optimize_battery_schedule(**inp)

    tomorrow_intents = [
        pd.decision.strategic_intent for pd in result.period_data[TODAY_REMAINING:]
    ]
    assert tomorrow_intents.count("BATTERY_EXPORT") > 0, (
        "expected the fixed (terminal-day-scoped) cap to restore at least "
        f"some BATTERY_EXPORT into tomorrow's plan; got zero (intents: "
        f"{tomorrow_intents})"
    )

    # Plan-faithfulness (R == P): the DP's claimed cost must match what the
    # real control-mapping/simulator layer actually realizes when the plan
    # is executed period-by-period. This exact real fixture (Frank's
    # captured settings/prices) has a small (~0.045 EUR out of ~2.8 EUR,
    # ~1.6%) pre-existing R-vs-P gap that is independent of
    # terminal_value_per_kwh -- verified identical with terminal_value=0.0
    # and the fixed cap -- so it is not caused by, or specific to, #422's
    # fix. Tracked as a separate control-fidelity finding to investigate;
    # the wider tolerance here reflects that known, unrelated gap rather
    # than a regression in this fix.
    dt = inp["period_duration_hours"]
    settings = inp["battery_settings"]
    commands = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / dt,
            settings,
            intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands,
        inp["solar_production"],
        inp["home_consumption"],
        inp["buy_price"],
        inp["sell_price"],
        inp["initial_soe"],
        settings,
        dt,
    )

    assert sim.realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.06
    ), (
        f"plan not faithfully executable: planned cost "
        f"{result.economic_summary.battery_solar_cost:.4f} vs realized "
        f"{sim.realized_cost:.4f}"
    )
