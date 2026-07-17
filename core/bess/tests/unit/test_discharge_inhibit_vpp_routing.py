"""apply_discharge_inhibit() must route through the inverter controller's
per-period write path, not write directly to the EMS discharge_rate entity.

Found during #324 code review: apply_discharge_inhibit() called
self.controller.set_discharging_power_rate() directly, bypassing
self._inverter_controller.apply_period(). On platforms where
discharge_rate_is_load_following is False (VPP-style control), hardware
never reads that EMS entity -- it reads growatt_vpp_power / active-power
targets instead. So on exactly the platforms #324 concerns, the mid-period
discharge-inhibit safety mechanism (meant to stop discharge within ~1 minute
when e.g. an EV starts charging) was a dead write: it recorded a suppression
in the mock's discharge_rate call list, but never touched the VPP command
actually controlling the inverter.
"""

from types import SimpleNamespace

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController

PERIOD = 20


class InhibitableController(MockHomeAssistantController):
    def __init__(self, inhibit_active: bool = False) -> None:
        super().__init__()
        self.inhibit_active = inhibit_active

    def get_discharge_inhibit_active(self) -> bool:
        return self.inhibit_active


def _make_vpp_bsm(
    inhibit_active: bool = False,
) -> tuple[BatterySystemManager, InhibitableController]:
    controller = InhibitableController(inhibit_active=inhibit_active)
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([1.0] * 96),
        addon_options={
            "inverter": {
                "platform": "solax_modbus_growatt_min",
                "control_mode": "vpp",
            }
        },
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents


def _set_discharge_action(bsm: BatterySystemManager, period: int, kwh: float) -> None:
    actions = [0.0] * 96
    actions[period] = kwh
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=actions)


class TestApplyDischargeInhibitRoutesThroughVppPath:
    def test_inhibit_suppresses_the_actual_vpp_command(self):
        bsm, controller = _make_vpp_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _set_discharge_action(bsm, PERIOD, -3.75)  # -15 kW -> 100%
        bsm._apply_period_schedule(PERIOD)
        assert controller.calls["growatt_vpp_periods"][-1]["power_pct"] == -100

        controller.inhibit_active = True
        bsm.apply_discharge_inhibit()

        vpp_call = controller.calls["growatt_vpp_periods"][-1]
        assert vpp_call["power_pct"] == 0
        assert vpp_call["remote_control_enabled"] is False

    def test_inhibit_release_restores_the_actual_vpp_command(self):
        bsm, controller = _make_vpp_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _set_discharge_action(bsm, PERIOD, -3.75)  # -15 kW -> 100%
        bsm._apply_period_schedule(PERIOD)  # inhibited: desired=100, applied=0

        controller.inhibit_active = False
        bsm.apply_discharge_inhibit()

        vpp_call = controller.calls["growatt_vpp_periods"][-1]
        assert vpp_call["power_pct"] == -100
        assert vpp_call["remote_control_enabled"] is True
