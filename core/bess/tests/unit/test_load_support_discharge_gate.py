"""LOAD_SUPPORT discharge-rate cap stays plan-scaled, unconditionally (#393).

#384/#385 extended intra_period_discharge_gate (the shadow-price economic gate
already used for SOLAR_EXPORT/SOLAR_STORAGE) to LOAD_SUPPORT, opening the
discharge-rate ceiling above the DP's plan-scaled rate whenever
`buy_price * eff_d >= shadow_price`. Two problems surfaced after shipping:

- #385's own validation against the reporting user's real captured data found
  the gate does NOT open during the sustained overnight near-tie regime it was
  built to fix -- shadow_price sits within a cent or two of buy_price for the
  whole stretch there, so the strict inequality rarely trips.
- A second, independent real-world report (different day, different price
  shape) showed the same gate condition evaluating true for the large
  majority of LOAD_SUPPORT periods -- a broad, mostly-untested override of the
  #147 reservation pacing (LOAD_SUPPORT deliberately reserves battery for a
  later, pricier period rather than dumping at full rate), not the narrow
  safety valve it was meant to be.

LOAD_SUPPORT no longer consults this gate at all -- back to the plan-scaled
cap alone, matching pre-#384 (and current v9.9.0b23) behavior. SOLAR_EXPORT/
SOLAR_STORAGE are unaffected (older, unrelated, pre-date #384) -- see
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
    """BSM-integration coverage: proves LOAD_SUPPORT's discharge_rate stays at
    the DP's plan-scaled baseline regardless of the DP's authorization, i.e.
    the gate is never consulted for this intent. Mirrors
    TestSolarExportDischargeGate's structure, inverted expectations."""

    def test_baseline_preserved_even_when_gate_condition_would_be_favorable(self):
        """The DP authorized sub-period discharge -- exactly the condition that
        used to open the gate to 100% -- and that now leaves the plan-scaled
        baseline untouched."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)
        _store_authorization(bsm, PERIOD, allowed=True)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE

    def test_baseline_preserved_when_dp_withholds_authorization(self):
        """DP withheld authorization -- the DP's own planned discharge
        (the baseline) is NOT zeroed out -- LOAD_SUPPORT already has a nonzero
        plan to protect, and nothing may lower it (that would regress #147)."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)
        _store_authorization(bsm, PERIOD, allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE

    def test_no_stored_schedule_keeps_baseline(self):
        """No schedule stored yet -- baseline (plan-scaled rate) is used as-is,
        matching pre-gate LOAD_SUPPORT behavior."""
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
