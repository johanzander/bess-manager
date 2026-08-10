"""#393 regression: LOAD_SUPPORT must never be pushed past its plan-scaled
discharge cap, replayed against a real user's captured data.

`core/bess/tests/unit/data/regression_2026_07_26_203726.json` is a real
optimizer input (buy/sell price, home consumption, solar production, battery
state) captured from a user's debug bundle via
`scripts/mock_ha/scenarios/from_debug_log.py --issue 393`. Running the actual
DP against it reproduces the finding that motivated reverting #384/#385's
LOAD_SUPPORT extension of `intra_period_discharge_gate`: the DP authorizes
sub-period discharge (`buy_price * eff_d >= shadow_price`) for the large
majority of this run's LOAD_SUPPORT periods -- not the rare "reserve
genuinely not needed elsewhere" case the gate was designed for.

This test replays that same real data through the production control-mapping
path (`derive_control_command`, the simulator's mirror of
`BatterySystemManager._apply_period_schedule`) and asserts LOAD_SUPPORT stays
at its plan-scaled baseline throughout -- so if the gate is ever
re-extended to LOAD_SUPPORT without being validated against this exact
regime, this test catches it.
"""

import json
from pathlib import Path

from core.bess.battery_system_manager import intra_period_discharge_gate
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.simulation.inverter_simulator import derive_control_command
from core.bess.tests.helpers import _scenario_inputs

FIXTURE_PATH = Path(__file__).parent / "data" / "regression_2026_07_26_203726.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_gate_condition_is_favorable_for_most_load_support_periods():
    """Sanity check on the fixture itself: reproduces the empirical finding
    (the large majority) that motivated the #393 revert. If this stops being true
    (e.g. the fixture or DP changes), the regression test below is no longer
    exercising the scenario it's meant to guard -- investigate before
    touching the assertions."""
    scenario = _load_fixture()
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)

    load_support_periods = [
        (i, pd)
        for i, pd in enumerate(result.period_data)
        if pd.decision.strategic_intent == "LOAD_SUPPORT"
    ]
    gate_open_count = sum(
        1
        for _i, pd in load_support_periods
        if intra_period_discharge_gate(pd.decision.intra_period_discharge_allowed)
        == 100
    )

    assert len(load_support_periods) >= 50, (
        f"expected a substantial number of LOAD_SUPPORT periods in this real "
        f"fixture, got {len(load_support_periods)} -- fixture may have changed"
    )
    assert gate_open_count / len(load_support_periods) > 0.5, (
        f"gate-open condition true for only {gate_open_count}/"
        f"{len(load_support_periods)} LOAD_SUPPORT periods -- expected the "
        "majority-open regime this regression test guards against"
    )


def test_load_support_discharge_rate_never_exceeds_plan_scaled_baseline():
    """The actual #393 regression guard: even though the gate condition is
    favorable for most LOAD_SUPPORT periods in this real data (see above),
    `derive_control_command` must never raise discharge_rate_pct above the
    DP's own plan-scaled rate for LOAD_SUPPORT -- the gate must not be
    consulted for this intent at all."""
    scenario = _load_fixture()
    inp = _scenario_inputs(scenario)
    dt = inp["period_duration_hours"]
    settings = inp["battery_settings"]
    result = optimize_battery_schedule(**inp)

    checked = 0
    for i, pd in enumerate(result.period_data):
        if pd.decision.strategic_intent != "LOAD_SUPPORT":
            continue
        action_kw = (
            pd.decision.battery_action / dt if pd.decision.battery_action else 0.0
        )
        expected_baseline = min(
            100, max(0, round(abs(action_kw) / settings.max_discharge_power_kw * 100))
        )

        cmd = derive_control_command(
            pd.decision.strategic_intent,
            action_kw,
            settings,
            intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
        )

        assert cmd.discharge_rate_pct == expected_baseline, (
            f"period {i}: LOAD_SUPPORT discharge_rate_pct="
            f"{cmd.discharge_rate_pct} != plan-scaled baseline "
            f"{expected_baseline} (DP authorization="
            f"{pd.decision.intra_period_discharge_allowed}) -- the intra-period "
            "discharge gate must not raise LOAD_SUPPORT's ceiling (#393)"
        )
        checked += 1

    assert (
        checked >= 50
    ), f"expected to check >=50 LOAD_SUPPORT periods, checked {checked}"
