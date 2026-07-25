"""LOAD_SUPPORT intra-period discharge gate (#384).

_map_intent_to_rates shares one branch for LOAD_SUPPORT and BATTERY_EXPORT,
capping the discharge_rate register at the DP's planned average power for the
period. That cap is correct for BATTERY_EXPORT (grid_first has no deficit
backstop -- an open ceiling would oversell beyond the arbitrage plan). But
LOAD_SUPPORT runs through load_first, which is already self-limiting to the
real house deficit: opening its ceiling can never cause it to export or
overshoot beyond actual need, only to spend reserve covering a real spike.

This reuses the existing intra_period_discharge_gate (shadow-price economic
gate, see test_solar_export_discharge_gate.py) for LOAD_SUPPORT, but unlike
SOLAR_EXPORT/SOLAR_STORAGE (whose planned baseline is always 0, so the gate
fully determines the outcome), LOAD_SUPPORT's baseline is already a nonzero
plan-scaled rate. So the fix is `discharge_rate = max(baseline, gate_rate)`:
only ever raise the ceiling when the reserve isn't needed elsewhere, never
lower it below what the DP already planned (that would regress #147, where a
hardcoded 100% LOAD_SUPPORT rate drained the battery early on high-consumption
days).
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


def _store_shadow_price(
    bsm: BatterySystemManager, period: int, shadow_price: float
) -> None:
    """Populate the schedule store with a LOAD_SUPPORT period at the given shadow price."""
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
    decision = DecisionData(strategic_intent="LOAD_SUPPORT", shadow_price=shadow_price)
    period_data = PeriodData(
        period=period,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(period),
        economic=EconomicData(),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestLoadSupportDischargeGate:
    """BSM-integration coverage: proves the gate fires in the real
    hardware-write path (_apply_period_schedule), not just the standalone
    gate function. Mirrors TestSolarExportDischargeGate."""

    def test_gate_opens_to_full_rate_when_reserve_not_needed(self):
        """High buy price, low shadow price -> gate opens, ceiling raised
        above the plan-scaled baseline to cover a real load spike."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)
        _store_shadow_price(bsm, PERIOD, shadow_price=0.5)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_baseline_preserved_when_shadow_price_high(self):
        """Low buy price, high shadow price -> gate stays closed, but the
        DP's own planned discharge (the baseline) is NOT zeroed out -- unlike
        SOLAR_EXPORT/SOLAR_STORAGE, LOAD_SUPPORT already has a nonzero plan to
        protect, and the gate must never lower it (that would regress #147)."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)
        _store_shadow_price(bsm, PERIOD, shadow_price=4.0)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE

    def test_no_stored_schedule_keeps_baseline(self):
        """No schedule stored yet -> gate cannot evaluate, baseline (plan-scaled
        rate) is used as-is, matching pre-gate LOAD_SUPPORT behavior."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent_with_action(bsm, PERIOD, "LOAD_SUPPORT", BASELINE_ACTION_KWH)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == BASELINE_DISCHARGE_RATE

    def test_battery_export_is_unaffected_by_the_gate(self):
        """BATTERY_EXPORT has no deficit backstop (grid_first) -- the gate
        must not touch it even with a favorable (low) shadow price, since
        opening its ceiling would oversell beyond the arbitrage plan."""
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
        decision = DecisionData(strategic_intent="BATTERY_EXPORT", shadow_price=0.5)
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
