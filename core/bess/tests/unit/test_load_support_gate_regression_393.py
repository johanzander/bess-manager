"""LOAD_SUPPORT + intra-period discharge gate, replayed against a real user's
captured data.

DIRECTION CHANGE -- this file's assertion was deliberately inverted by #520.
It previously pinned "LOAD_SUPPORT's discharge_rate never exceeds the
plan-scaled baseline regardless of the gate" (#393). It now pins the
opposite: the ceiling IS raised when the gate is open, and is NOT raised when
the gate is closed. Read this before re-reverting on #393's reasoning:

#393 removed LOAD_SUPPORT from the gate as "a broad override of the #147
reservation pacing". That double-counts the reservation. The gate's input is
`decision.intra_period_discharge_allowed`, which the DP decides from dV/dSoE --
its own marginal value of stored energy (`buy_price * eff_d >= shadow_price`,
evaluated in `_record_marginal_value` where the value function is owned, #526).
The future value the pacing protects is therefore already inside the comparison
the DP made. Gate closed -> import, reservation protected by construction. Gate
open -> the energy is worth more used now than saved, so there is nothing being
reserved. The gate does not override reservation pacing; it evaluates it.

#393's headline figure from this very fixture -- "the gate evaluates true for
51 of 67 LOAD_SUPPORT periods (~76%)" -- measured gate-OPENNESS, not
pacing-override. That exact figure no longer reproduces: on this branch the
same fixture yields 41 of 68 (60.3%), the DP having changed underneath it since
#393 (notably #512's finer state/action grid). The majority-open regime it
identified does still hold, which is all the sanity check below asserts.

The breadth is real and corpus-wide, re-measured post-#526: the gate is open in
431 of 603 LOAD_SUPPORT periods (71.5%) and raises the ceiling in 427 of them.
It is correct by the argument above, not despite it.

`core/bess/tests/unit/data/regression_2026_07_26_203726.json` is a real
optimizer input (buy/sell price, home consumption, solar production, battery
state) captured from a user's debug bundle via
`scripts/mock_ha/scenarios/from_debug_log.py --issue 393`. Each LOAD_SUPPORT
period's real (buy_price, DP authorization, planned action) triple is replayed
through the production hardware-write path
(`BatterySystemManager._apply_period_schedule`) -- not the simulator's mirror,
which does not model this sub-period behaviour.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.execution_model import (
    command_index,
    intra_period_discharge_gate,
)
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.settings import BatterySettings
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import _scenario_inputs

FIXTURE_PATH = Path(__file__).parent / "data" / "regression_2026_07_26_203726.json"

TEST_PERIOD = 20  # arbitrary quarter-hour slot to replay each period into

# Neutralises the retail price build-up ((spot * mult + markup) * vat + costs)
# so the buy price the replayed period sees is exactly the fixture's own buy
# price -- the same number the DP optimized against.
RAW_SPOT_PRICE_SETTINGS = {
    "markup_rate": 0.0,
    "vat_multiplier": 1.0,
    "additional_costs": 0.0,
    "spot_multiplier": 1.0,
}


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _make_bsm(
    buy_price: float, battery_settings: BatterySettings
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    """A BSM running the fixture's real battery (rate limits drive the
    plan-scaled baseline) at the given buy price."""
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([buy_price] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    bsm.update_settings(
        {
            "price": RAW_SPOT_PRICE_SETTINGS,
            "battery": {
                "max_charge_power_kw": battery_settings.max_charge_power_kw,
                "max_discharge_power_kw": battery_settings.max_discharge_power_kw,
                "efficiency_discharge": battery_settings.efficiency_discharge,
            },
        }
    )
    return bsm, controller


def _apply_load_support_period(
    bsm: BatterySystemManager, action_kwh: float, allowed: bool
) -> None:
    intents = ["IDLE"] * 96
    intents[TEST_PERIOD] = "LOAD_SUPPORT"
    bsm._inverter_controller.strategic_intents = intents
    actions = [0.0] * 96
    actions[TEST_PERIOD] = action_kwh
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=actions)

    period_data = PeriodData(
        period=TEST_PERIOD,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=0.0,
            battery_soe_start=10.0,
            battery_soe_end=10.0,
        ),
        timestamp=time_utils.period_index_to_timestamp(TEST_PERIOD),
        economic=EconomicData(),
        decision=DecisionData(
            strategic_intent="LOAD_SUPPORT", intra_period_discharge_allowed=allowed
        ),
    )
    bsm.schedule_store.store_schedule(
        OptimizationResult(input_data={}, period_data=[period_data]),
        optimization_period=TEST_PERIOD,
    )

    bsm._apply_period_schedule(TEST_PERIOD)


def _load_support_periods() -> tuple[list[tuple[int, float, bool, float]], dict]:
    """Replay the real fixture through the DP and return, per LOAD_SUPPORT
    period, (index, buy_price, DP authorization, planned battery action kWh)."""
    inp = _scenario_inputs(_load_fixture())
    result = optimize_battery_schedule(**inp)
    buy_price = inp["buy_price"]
    periods = [
        (
            i,
            buy_price[i],
            pd.decision.intra_period_discharge_allowed,
            pd.decision.battery_action or 0.0,
        )
        for i, pd in enumerate(result.period_data)
        if pd.decision.strategic_intent == "LOAD_SUPPORT"
    ]
    return periods, inp


def test_gate_condition_is_favorable_for_most_load_support_periods():
    """Sanity check on the fixture itself: it is still in the majority-open
    regime #393 identified. The exact figure has drifted with the DP (#393
    measured 51/67 = 76%; this branch measures 41/68 = 60.3%), so only the
    majority property is asserted. If even that stops being true, the test
    below is no longer exercising the regime it guards -- investigate before
    touching the assertions."""
    periods, _inp = _load_support_periods()

    gate_open_count = sum(
        1 for _, _buy, allowed, _ in periods if intra_period_discharge_gate(allowed)
    )

    assert len(periods) >= 50, (
        f"expected a substantial number of LOAD_SUPPORT periods in this real "
        f"fixture, got {len(periods)} -- fixture may have changed"
    )
    assert gate_open_count / len(periods) > 0.5, (
        f"gate-open condition true for only {gate_open_count}/{len(periods)} "
        "LOAD_SUPPORT periods -- expected the majority-open regime this test "
        "exercises"
    )


def test_load_support_ceiling_follows_the_gate_on_real_data():
    """Every LOAD_SUPPORT period of this real capture, through the production
    hardware-write path: gate open -> ceiling raised to 100 (the energy is
    worth less now than later, nothing is being reserved); gate closed ->
    exactly the DP's plan-scaled baseline, neither raised nor lowered (#520,
    inverting #393)."""
    periods, inp = _load_support_periods()
    dt = inp["period_duration_hours"]
    settings = inp["battery_settings"]

    opened = 0
    held = 0
    for i, buy, allowed, action_kwh in periods:
        action_kw = action_kwh / dt
        # The plan-scaled baseline comes from the shared conversion rather
        # than a restatement of it here: this test is about the *gate*, and a
        # mirrored rounding rule only pins the mirror. Phase 4b made the
        # direction command-dependent (a load_first ceiling rounds up, or it
        # under-delivers the plan), which a hand-written `round()` here got
        # wrong the moment production changed.
        baseline = command_index(
            abs(action_kw),
            settings.max_discharge_power_kw / 100,
            rate_is_ceiling=True,
        )
        gate = intra_period_discharge_gate(allowed)

        bsm, controller = _make_bsm(buy, settings)
        _apply_load_support_period(bsm, action_kwh, allowed)
        applied = controller.calls["discharge_rate"][-1]

        assert applied == max(baseline, gate), (
            f"period {i}: applied discharge_rate={applied}, expected "
            f"max(plan_scaled={baseline}, gate={gate}) "
            f"(buy={buy:.4f}, allowed={allowed}) -- LOAD_SUPPORT must "
            "follow the DP's intra-period discharge decision (#520)"
        )
        if gate == 100:
            opened += 1
        else:
            held += 1

    assert opened > 0 and held > 0, (
        f"fixture no longer exercises both sides of the gate "
        f"(open={opened}, closed={held}) -- the assertion above is no longer "
        "discriminating"
    )
