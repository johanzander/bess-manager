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

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
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
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)
    return bsm, controller


def _last_vpp_command(controller: MockHomeAssistantController) -> dict:
    return controller.calls["growatt_vpp_periods"][-1]


class TestIdleAtReserveFloorReleasesControl:
    def test_idle_at_the_floor_releases_the_inverter(self):
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

    def test_idle_above_the_floor_still_holds_battery_first(self):
        """#466 must survive #592: with energy still banked for the morning
        peak, IDLE holds battery_first exactly as before."""
        bsm, controller = _make_vpp_bsm(soc=50.0)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_released_control_stops_re_asserting_every_period(self):
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

    def test_hold_still_re_asserts_every_period_above_the_floor(self):
        """Guard rail on the test above: the every-period refresh is correct
        and must be preserved wherever remote control is genuinely active,
        otherwise the fallback timer would lapse mid-hold (#404)."""
        bsm, controller = _make_vpp_bsm(soc=50.0)

        for period in range(PERIOD, PERIOD + 4):
            bsm._apply_period_schedule(period)

        assert len(controller.calls["growatt_vpp_periods"]) == 4
