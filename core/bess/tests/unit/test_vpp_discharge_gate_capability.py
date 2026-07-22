"""VPP mode must not force a full-power discharge via the SOLAR_EXPORT/
SOLAR_STORAGE intra-period discharge gate (#324).

intra_period_discharge_gate (#187/#318) assumes discharge_rate acts as a
ceiling under native load-first firmware: "allow up to 100%, the inverter
only draws what's needed to cover an actual deficit." That assumption holds
for Growatt's TOU/load_first path, but not for VPP-style control
(SolaxModbusGrowattController in control_mode="vpp", and SolaxController),
where discharge_rate becomes an immediate forced power command
(vpp_power/active-power target) regardless of actual load. A reported real
trace (issue #324) showed exactly this: SOLAR_EXPORT, Action=0.00 kWh
planned, but the gate opened and the inverter received power=-100% -- an
unplanned full-power battery dump at 11% SOC.

Mirrors the BSM-integration style of test_solar_export_discharge_gate.py /
test_solar_storage_discharge_gate.py, but asserts on the VPP command
actually written to hardware instead of the EMS discharge_rate register
(VPP mode never touches that register).
"""

from types import SimpleNamespace

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


def _make_bsm(
    buy_prices: list[float], control_mode: str
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource(buy_prices),
        addon_options={
            "inverter": {
                "platform": "solax_modbus_growatt_min",
                "control_mode": control_mode,
            }
        },
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)


def _store_shadow_price(
    bsm: BatterySystemManager, period: int, intent: str, shadow_price: float
) -> None:
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
    decision = DecisionData(strategic_intent=intent, shadow_price=shadow_price)
    period_data = PeriodData(
        period=period,
        energy=energy,
        economic=EconomicData(),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestVppModeDischargeGateExcluded:
    """VPP mode: the gate must not fire, since discharge_rate=100 there means
    an immediate forced-power command, not a load-following ceiling."""

    def test_solar_export_gate_open_does_not_force_vpp_discharge(self):
        """Same economics that open the gate on TOU (buy high, shadow low)
        must NOT produce a forced discharge command in VPP mode -- power
        must stay 0. remote_control_enabled is True (grid-first hold, #355)
        rather than a forced discharge, blocking passive solar charging
        instead of falling back to self-use."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96, control_mode="vpp")
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")
        _store_shadow_price(bsm, PERIOD, "SOLAR_EXPORT", shadow_price=0.5)

        bsm._apply_period_schedule(PERIOD)

        vpp_call = controller.calls["growatt_vpp_periods"][-1]
        assert vpp_call["power_pct"] == 0
        assert vpp_call["remote_control_enabled"] is True

    def test_solar_storage_gate_open_does_not_force_vpp_discharge(self):
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96, control_mode="vpp")
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_shadow_price(bsm, PERIOD, "SOLAR_STORAGE", shadow_price=0.5)

        bsm._apply_period_schedule(PERIOD)

        vpp_call = controller.calls["growatt_vpp_periods"][-1]
        assert vpp_call["power_pct"] == 0
        assert vpp_call["remote_control_enabled"] is False


class TestTouModeDischargeGateUnaffected:
    """Regression guard: the same solax_modbus_growatt_min platform in TOU
    mode must keep today's gate behavior (discharge_rate becomes 100)."""

    def test_solar_export_gate_still_opens_in_tou_mode(self):
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96, control_mode="tou")
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")
        _store_shadow_price(bsm, PERIOD, "SOLAR_EXPORT", shadow_price=0.5)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100
