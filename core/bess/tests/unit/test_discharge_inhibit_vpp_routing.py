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
from core.bess.simulation.vpp_simulator import VppCommand, vpp_command_to_power
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
    def test_inhibit_suppresses_the_actual_vpp_command(self) -> None:
        # BATTERY_EXPORT, not LOAD_SUPPORT: #413 made LOAD_SUPPORT release VPP
        # control entirely (no forced rate to suppress), so it no longer
        # exercises this routing path. BATTERY_EXPORT still forces a rate.
        bsm, controller = _make_vpp_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "BATTERY_EXPORT")
        _set_discharge_action(bsm, PERIOD, -3.75)  # -15 kW -> 100%
        bsm._apply_period_schedule(PERIOD)
        assert controller.calls["growatt_vpp_periods"][-1]["power_pct"] == -100

        controller.inhibit_active = True
        bsm.apply_discharge_inhibit()

        vpp_call = controller.calls["growatt_vpp_periods"][-1]
        assert vpp_call["power_pct"] == 0
        # BATTERY_EXPORT blocks passive charging (INTENT_TO_CONTROL charge_rate=0)
        # -- an inhibited discharge should hold the battery (grid first), not
        # fall back to self-use and let solar recharge it mid-inhibit. Fixed
        # alongside #355 (see
        # docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md) --
        # this was the same class of bug on the discharge-inhibit path.
        assert vpp_call["remote_control_enabled"] is True

    def test_inhibit_release_restores_the_actual_vpp_command(self) -> None:
        bsm, controller = _make_vpp_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "BATTERY_EXPORT")
        _set_discharge_action(bsm, PERIOD, -3.75)  # -15 kW -> 100%
        bsm._apply_period_schedule(PERIOD)  # inhibited: desired=100, applied=0

        controller.inhibit_active = False
        bsm.apply_discharge_inhibit()

        vpp_call = controller.calls["growatt_vpp_periods"][-1]
        assert vpp_call["power_pct"] == -100
        assert vpp_call["remote_control_enabled"] is True


def _battery_power_under_last_command(
    bsm: BatterySystemManager, controller: InhibitableController
) -> float | None:
    """What the battery does under the VPP command BSM last wrote, executed
    through `vpp_simulator`'s firmware model: an evening of two EVs charging
    (18 kW house deficit, no solar) on a battery well above its floor --
    #881's night. 0.0 or None means the battery is not discharging."""
    vpp_call = controller.calls["growatt_vpp_periods"][-1]
    settings = bsm.battery_settings
    return vpp_command_to_power(
        VppCommand(vpp_call["power_pct"], vpp_call["remote_control_enabled"]),
        solar=0.0,
        home=18.0 * 0.25,
        soe=settings.total_capacity * 0.6,
        settings=settings,
        dt=0.25,
    )


def _discharging(power: float | None) -> bool:
    return power is not None and power < 0


class TestInhibitHoldsLoadSupport:
    """#881: on Growatt VPP a LOAD_SUPPORT period releases remote control, so
    the inverter's own self-use covers whatever load appears -- including the
    EVs the discharge inhibit exists to keep the battery out of. The inhibit
    zeroed the discharge rate, but the release ignored the rate, so the
    inhibit did nothing on exactly the periods it matters most.

    Asserted on the battery's resulting power under the firmware model, not on
    the register values: the point is that the battery stops serving the load.
    """

    def test_load_support_follows_load_without_inhibit(self) -> None:
        """Unchanged #413 behaviour: no inhibit, the period follows load."""
        bsm, controller = _make_vpp_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _set_discharge_action(bsm, PERIOD, -0.1)
        bsm._apply_period_schedule(PERIOD)

        power = _battery_power_under_last_command(bsm, controller)
        assert power is not None and power < -1.0

    def test_inhibit_keeps_the_battery_out_of_the_load(self) -> None:
        bsm, controller = _make_vpp_bsm(inhibit_active=True)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _set_discharge_action(bsm, PERIOD, -0.1)
        bsm._apply_period_schedule(PERIOD)

        assert not _discharging(_battery_power_under_last_command(bsm, controller))

    def test_inhibit_toggling_mid_period_holds_then_restores(self) -> None:
        """The every-minute inhibit job must reach a LOAD_SUPPORT period too:
        an EV that starts charging mid-period stops the discharge, and one that
        stops hands the period back to load-following."""
        bsm, controller = _make_vpp_bsm(inhibit_active=False)
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _set_discharge_action(bsm, PERIOD, -0.1)
        bsm._apply_period_schedule(PERIOD)

        controller.inhibit_active = True
        bsm.apply_discharge_inhibit()
        assert not _discharging(_battery_power_under_last_command(bsm, controller))

        controller.inhibit_active = False
        bsm.apply_discharge_inhibit()
        power = _battery_power_under_last_command(bsm, controller)
        assert power is not None and power < -1.0
