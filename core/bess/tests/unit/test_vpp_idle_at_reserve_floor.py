"""IDLE at the reserve floor releases VPP control so the BMS can sleep (#592).

Reported behaviour: during a long overnight IDLE with the battery already at
its minimum SoC, the inverter was held in `battery_first` (`vpp_power=+1`,
remote control enabled) and that command was re-asserted every period, so the
inverter was never handed back and its BMS never slept.

`battery_first` is right whenever IDLE is *holding energy back* for a later
peak (#466) -- it keeps self-consumption on grid/solar instead of draining the
battery, which IDLE's own DP cost model (`_idle_battery_flows`) never credits.
At the reserve floor there is nothing left to hold, so the hold buys nothing
and costs the BMS its sleep.

**These tests drive the real production write path**
(`BatterySystemManager._apply_period_schedule`), not `_intent_to_vpp` with
hand-built arguments. That is deliberate: the mapping alone could be correct
while the floor flag never reaches it -- the branch would be dead in
production and a unit test on the mapping would still pass. What is asserted
here is the command that actually lands on the inverter.

Flow-neutrality of the swap (the reason this needs no VPP baseline re-pin) is
proved separately in
`test_vpp_simulator_branches.py::TestIdleAtReserveFloor`.
"""

from types import SimpleNamespace
from typing import Any, cast

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_schedule import DPSchedule
from core.bess.price_manager import MockSource
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController

PERIOD = 12  # 03:00 -- the overnight idle stretch from the report


def _make_vpp_bsm(
    soc: float,
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    controller.settings["battery_soc"] = soc
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
    intents = ["IDLE"] * 96
    inverter_controller = bsm._inverter_controller
    assert inverter_controller is not None
    inverter_controller.strategic_intents = intents
    # A duck-typed stand-in: only `.actions` is read on this path.
    inverter_controller.current_schedule = cast(
        DPSchedule, SimpleNamespace(actions=[0.0] * 96)
    )
    return bsm, controller


def _last_vpp_command(controller: MockHomeAssistantController) -> dict[str, Any]:
    command: dict[str, Any] = controller.calls["growatt_vpp_periods"][-1]
    return command


class TestIdleAtReserveFloorReleasesControl:
    def test_idle_at_the_floor_releases_the_inverter(self) -> None:
        """At min SoC the written command must release remote control, so the
        inverter reverts to its own self-use and stops being commanded."""
        bsm, controller = _make_vpp_bsm(soc=10.0)
        assert (
            bsm.battery_settings.min_soc == 10.0
        ), "fixture assumes the default 10% floor; the SoC above must equal it"

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 0
        assert command["remote_control_enabled"] is False

    def test_idle_above_the_floor_still_holds_battery_first(self) -> None:
        """#466 must survive #592: with energy still banked for the morning
        peak, IDLE holds battery_first exactly as before."""
        bsm, controller = _make_vpp_bsm(soc=50.0)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_released_control_stops_re_asserting_every_period(self) -> None:
        """The actual mechanism behind "the BMS never sleeps": with remote
        control enabled `_apply_period_vpp` rewrites every period to refresh
        the inverter's fallback timer (#404). Once released there is nothing
        to refresh, so the writes must stop rather than continue silently."""
        bsm, controller = _make_vpp_bsm(soc=10.0)

        for period in range(PERIOD, PERIOD + 4):
            bsm._apply_period_schedule(period)

        assert len(controller.calls["growatt_vpp_periods"]) == 1, (
            "a released inverter must be written once, not re-commanded every "
            "period -- re-asserting is what kept the BMS awake"
        )

    def test_unreadable_soc_holds_rather_than_releasing(self) -> None:
        """`get_battery_soc()` is typed `float | None`, so a transient
        unavailable/unknown HA sensor must not decide this.

        Holding is the safe direction and is exactly today's behaviour: the
        release is what could let the inverter's own self-use draw the battery
        down, so acting on an unreadable reading is the only outcome that can
        make things worse. Deliberately NOT a silent default -- the branch is
        explicit and logged, per rules.md. Releasing on bad data would be the
        unsafe direction; crashing on it would take down the whole period
        write, including grid_charge and discharge_rate.
        """
        bsm, controller = _make_vpp_bsm(soc=50.0)
        controller.settings["battery_soc"] = None

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_out_of_range_soc_holds_rather_than_releasing(self) -> None:
        """Same branch, the other invalid shape a sensor can report. Mirrors
        the existing `0 <= soc <= 100` validation in
        `_get_current_battery_soc()` rather than inventing a second rule."""
        bsm, controller = _make_vpp_bsm(soc=50.0)
        controller.settings["battery_soc"] = -1.0

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_hold_still_re_asserts_every_period_above_the_floor(self) -> None:
        """Guard rail on the test above: the every-period refresh is correct
        and must be preserved wherever remote control is genuinely active,
        otherwise the fallback timer would lapse mid-hold (#404)."""
        bsm, controller = _make_vpp_bsm(soc=50.0)

        for period in range(PERIOD, PERIOD + 4):
            bsm._apply_period_schedule(period)

        assert len(controller.calls["growatt_vpp_periods"]) == 4


def _vpp_controller_with_plan(soe: float) -> SolaxModbusGrowattController:
    """A VPP controller whose plan idles all day at the given SoE."""
    settings = BatterySettings(total_capacity=50.0, min_soc=10.0, max_soc=95.0)
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    controller.strategic_intents = ["IDLE"] * 96
    controller.current_schedule = DPSchedule(
        actions=[0.0] * 96,
        state_of_energy=[soe] * 97,
        prices=[0.1] * 96,
        original_dp_results={"strategic_intent": ["IDLE"] * 96},
    )
    return controller


CROSSING = 20  # the period during which the plan discharges onto the floor


def _vpp_controller_with_plan_crossing_the_floor() -> SolaxModbusGrowattController:
    """A plan that is above the floor until it discharges onto it during
    `CROSSING`, so index p and index p-1 give different answers there."""
    settings = BatterySettings(total_capacity=50.0, min_soc=10.0, max_soc=95.0)
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    controller.strategic_intents = ["IDLE"] * 96
    # state_of_energy[p] == SoE LEAVING period p. Leaving CROSSING is the
    # floor, so entering CROSSING (index CROSSING - 1) is still above it.
    controller.current_schedule = DPSchedule(
        actions=[0.0] * 96,
        state_of_energy=[8.0 if p < CROSSING else 5.0 for p in range(97)],
        prices=[0.1] * 96,
        original_dp_results={"strategic_intent": ["IDLE"] * 96},
    )
    return controller


class TestDisplayAgreesWithWhatIsWritten:
    """`get_period_settings()` feeds the API/UI, and `_mode_display_fields`'s
    contract is that it "never fabricates a label the hardware doesn't back".

    A displayed period is a *prediction*, so it reads the plan's own SoE
    trajectory where the production write path reads live SoC -- different
    inputs, same rule. Without this the UI reports the battery_first hold for
    exactly the periods production releases.
    """

    def test_predicted_idle_at_the_floor_displays_the_release(self) -> None:
        controller = _vpp_controller_with_plan(soe=5.0)  # == min_soe_kwh
        fields = controller.get_period_settings(PERIOD)
        assert fields["vpp_power_pct"] == 0
        assert fields["vpp_remote_control"] is False

    def test_predicted_idle_above_the_floor_displays_the_hold(self) -> None:
        controller = _vpp_controller_with_plan(soe=25.0)
        fields = controller.get_period_settings(PERIOD)
        assert fields["vpp_power_pct"] == 1
        assert fields["vpp_remote_control"] is True

    def test_the_crossing_period_still_displays_the_hold(self) -> None:
        """The uniform-trajectory fixtures above cannot see an off-by-one:
        with every index equal, `soe[period]` and `soe[period - 1]` agree.

        This one varies across the boundary. `state_of_energy[p]` is the SoE
        *leaving* period p, so a plan that discharges to the floor during
        CROSSING is still above the floor *entering* it -- the write path,
        reading live SoC, would hold there. Reading index `period` instead of
        `period - 1` reports the release one period early, which is precisely
        the display/write disagreement this class exists to catch.
        """
        controller = _vpp_controller_with_plan_crossing_the_floor()

        entering_above = controller.get_period_settings(CROSSING)
        assert entering_above["vpp_power_pct"] == 1
        assert entering_above["vpp_remote_control"] is True

        entering_at_floor = controller.get_period_settings(CROSSING + 1)
        assert entering_at_floor["vpp_power_pct"] == 0
        assert entering_at_floor["vpp_remote_control"] is False
