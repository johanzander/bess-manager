"""LOAD_SUPPORT consults the intra-period discharge gate (#520).

    discharge_rate = max(plan_scaled, intra_period_discharge_gate(...))

DIRECTION CHANGE -- these assertions were inverted by #520. Between #393 and
#520 this file pinned the opposite property ("LOAD_SUPPORT's discharge_rate
never exceeds the plan-scaled baseline regardless of the gate"). Read this
before re-reverting on #393's reasoning:

#393 removed LOAD_SUPPORT from the gate as "a broad override of the #147
reservation pacing". That double-counts the reservation. The gate's input is
`decision.intra_period_discharge_allowed`, which the DP decides from dV/dSoE --
its own marginal value of stored energy (#526) -- so the future value the
pacing protects is already inside the comparison the DP made. Gate closed ->
import, reservation protected. Gate open -> the energy is worth more used now
than saved, so there is nothing being reserved. The gate does not override
reservation pacing; it evaluates it.

#393's headline "the gate evaluates true for 51/67 (~76%) of LOAD_SUPPORT
periods" measured gate-OPENNESS, not pacing-override: it means that in 76% of
those periods battery-now genuinely beat grid-now. The breadth is real --
corpus-wide, re-measured post-#526, the gate is open in 431 of 603
LOAD_SUPPORT periods (71.5%) and raises the ceiling in 427 of them -- and is
correct by the argument above, not despite it.

SOLAR_EXPORT/SOLAR_STORAGE are unaffected and predate all of this -- see
test_solar_export_discharge_gate.py / test_solar_storage_discharge_gate.py.
"""

from types import SimpleNamespace

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController

PERIOD = 20  # Arbitrary test period (quarter-hour slot)

# battery_action_kw = -3.0 kWh / 0.25h = -12.0 kW... use a smaller action so
# the baseline lands clearly between 0 and 100: -0.75 kWh over a 15-min period
# is -3.0 kW; scale_to_percent(3.0, max_discharge_power_kw=15.0) == 20.
BASELINE_ACTION_KWH = -0.75
BASELINE_DISCHARGE_RATE = 20


def _make_bsm(
    buy_prices: list[float],
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource(buy_prices),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    return bsm, controller


def _set_intent_with_action(
    bsm: BatterySystemManager, period: int, intent: str, action_kwh: float
) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    actions = [0.0] * 96
    actions[period] = action_kwh
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=actions)


def _store_authorization(bsm: BatterySystemManager, period: int, allowed: bool) -> None:
    """Populate the schedule store with a LOAD_SUPPORT period carrying the DP's
    sub-period discharge authorization (#526 -- the BSM reads the decision, not
    the shadow price it was derived from)."""
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    decision = DecisionData(
        strategic_intent="LOAD_SUPPORT", intra_period_discharge_allowed=allowed
    )
    period_data = PeriodData(
        period=period,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(period),
        economic=EconomicData(),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestLoadSupportDischargeCap:
    """BSM-integration coverage: proves the gate fires for LOAD_SUPPORT in the
    real hardware-write path (_apply_period_schedule) -- raising the ceiling
    when the DP authorized sub-period discharge, leaving the plan-scaled
    baseline alone when it did not. Mirrors TestSolarExportDischargeGate's
    structure."""

    def test_ceiling_raised_when_dp_authorizes(self):
        """DP authorized sub-period discharge -> gate open: the stored energy
        is worth less than buying now, so nothing is being reserved and the
        ceiling opens above the plan-scaled baseline to cover the deficit from
        the battery (#520)."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)
        _store_authorization(bsm, PERIOD, allowed=True)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_baseline_preserved_when_dp_withholds_authorization(self):
        """DP withheld authorization -> gate closed: the reserve is genuinely
        worth more later, so the deficit is bought from grid and the DP's own
        planned discharge (the baseline) is left exactly as planned -- neither
        raised nor lowered (lowering would regress #147)."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)
        _store_authorization(bsm, PERIOD, allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE

    def test_no_stored_schedule_keeps_baseline(self):
        """No schedule stored yet -> no DP decision to read, so the gate cannot
        evaluate: baseline (plan-scaled rate) is used as-is (safe default)."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE

    def test_battery_export_is_unaffected(self):
        """BATTERY_EXPORT has no deficit backstop (grid_first) -- it was never
        part of this gate and still isn't, even when the DP authorized
        sub-period discharge."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent_with_action(bsm, PERIOD, "BATTERY_EXPORT", BASELINE_ACTION_KWH)
        energy = EnergyData(
            solar_production=0.0,
            home_consumption=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=0.0,
            battery_soe_start=10.0,
            battery_soe_end=10.0,
        )
        decision = DecisionData(
            strategic_intent="BATTERY_EXPORT", intra_period_discharge_allowed=True
        )
        period_data = PeriodData(
            period=PERIOD,
            energy=energy,
            timestamp=time_utils.period_index_to_timestamp(PERIOD),
            economic=EconomicData(),
            decision=decision,
        )
        result = OptimizationResult(input_data={}, period_data=[period_data])
        bsm.schedule_store.store_schedule(result, optimization_period=PERIOD)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE
