"""VPP IDLE releases control when the DP says the stored energy is worth less
than the grid price (#786).

Reported behaviour: at 07:15-07:59 the plan had a forecast deficit of 0.008 kWh
(below `FLOW_NOISE_FLOOR_KWH`), so no battery cover could be planned and the
period fell through to IDLE. On Growatt VPP IDLE is the `battery_first` hold
(`vpp_power=+1`, #466), which stops the battery serving house load. Solar then
came in at 0.0 instead of the forecast 0.117 kWh and the unplanned load was
imported at ~2.29 SEK/kWh although the battery's own stored energy was valued
at ~1.6-1.9.

`DecisionData.intra_period_discharge_allowed` is the DP's verdict on exactly
that comparison (`buy_price >= shadow_price`, #526) and every other
load-covering intent already consults it. IDLE did not, so on VPP the hold was
applied even where the plan itself would rather cover. The hold is kept where
the verdict is closed -- the energy is worth more later (#466) -- and where the
plan left a real deficit to the grid (a deliberate IDLE; the verdict is a
marginal value and releasing would drain the whole deficit). It is released
only for the fall-through: verdict open and deficit within the noise floor
(`strategic_intent.idle_hold_releasable`).

**These tests drive the real production write path**
(`BatterySystemManager._apply_period_schedule`), like #592's: the mapping alone
could be right while the verdict never reaches it. What is asserted is the
command that lands on the inverter.

The command is asserted, not an outcome, because this path has no execution
model that sees the verdict: `run_scenario_realized` is TOU-only and
`simulate_vpp` takes the verdict and planned import through its own arguments. The outcome is
asserted in `test_vpp_simulator_branches.py::TestIdleGateRelease`.
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_schedule import DPSchedule
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.strategic_intent import FLOW_NOISE_FLOOR_KWH, idle_hold_releasable
from core.bess.tests.conftest import MockHomeAssistantController

PERIOD = 30  # 07:30 -- inside the reported 07:15-07:59 IDLE stretch


def _make_vpp_bsm(
    soc: float,
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    controller.settings["battery_soc"] = soc
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([2.2] * 96),
        addon_options={
            "inverter": {
                "platform": "solax_modbus_growatt_min",
                "control_mode": "vpp",
            }
        },
    )
    inverter_controller = bsm._inverter_controller
    assert inverter_controller is not None
    inverter_controller.strategic_intents = ["IDLE"] * 96
    # A duck-typed stand-in: only `.actions` is read on this path.
    inverter_controller.current_schedule = cast(
        DPSchedule, SimpleNamespace(actions=[0.0] * 96)
    )
    return bsm, controller


def _store_verdict(
    bsm: BatterySystemManager, allowed: bool, planned_import: float = 0.008
) -> None:
    """Store the period carrying the DP's discharge verdict (#526) and the
    plan's own deficit (`grid_imported`); the default is the report's 0.008."""
    energy = EnergyData(
        solar_production=0.117,
        home_consumption=0.125,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=planned_import,
        grid_exported=0.0,
        battery_soe_start=3.4,
        battery_soe_end=3.4,
    )
    period_data = PeriodData(
        period=PERIOD,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(PERIOD),
        economic=EconomicData(),
        decision=DecisionData(
            strategic_intent="IDLE", intra_period_discharge_allowed=allowed
        ),
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=PERIOD)


def _last_vpp_command(controller: MockHomeAssistantController) -> dict[str, Any]:
    command: dict[str, Any] = controller.calls["growatt_vpp_periods"][-1]
    return command


class TestIdleGateRelease:
    def test_idle_with_the_gate_open_releases_the_inverter(self) -> None:
        """The #786 case: stored energy is worth less than the grid price, so
        IDLE must not block the battery from covering load."""
        bsm, controller = _make_vpp_bsm(soc=17.0)
        _store_verdict(bsm, allowed=True)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 0
        assert command["remote_control_enabled"] is False

    def test_idle_with_the_gate_closed_still_holds(self) -> None:
        """#466 must survive: the energy is worth more later than the grid
        price now, so the battery is held back and the house imports."""
        bsm, controller = _make_vpp_bsm(soc=17.0)
        _store_verdict(bsm, allowed=False)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_idle_with_the_gate_open_but_a_large_planned_deficit_still_holds(
        self,
    ) -> None:
        """The verdict is a marginal value at the planned SoE. Where the plan
        itself left a real deficit to the grid, IDLE was a choice, and releasing
        would let the battery cover all of it -- draining energy reserved for
        later (+3.6 SEK across the scenario corpus)."""
        bsm, controller = _make_vpp_bsm(soc=17.0)
        _store_verdict(bsm, allowed=True, planned_import=FLOW_NOISE_FLOOR_KWH + 0.5)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_the_noise_floor_itself_counts_as_within_it(self) -> None:
        assert idle_hold_releasable(True, FLOW_NOISE_FLOOR_KWH)
        assert not idle_hold_releasable(True, FLOW_NOISE_FLOOR_KWH + 1e-6)
        assert not idle_hold_releasable(False, 0.0)

    def test_idle_with_no_stored_verdict_still_holds(self) -> None:
        """Absence of an economic basis is not permission (#526). With no
        stored period the hold is exactly today's behaviour."""
        bsm, controller = _make_vpp_bsm(soc=17.0)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_idle_at_the_floor_with_the_gate_closed_still_releases(self) -> None:
        """#592 is unchanged: at the floor there is nothing to hold, whatever
        the verdict says."""
        bsm, controller = _make_vpp_bsm(soc=10.0)
        assert bsm.battery_settings.min_soc == 10.0
        _store_verdict(bsm, allowed=False)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 0
        assert command["remote_control_enabled"] is False


class TestReleaseUnderDischargeInhibit:
    """The discharge inhibit (e.g. an EV charging) only zeroes a nonzero
    discharge rate, and IDLE's is already 0 -- so on VPP the battery_first hold
    was what kept the battery out of the load. Releasing it must not lift that."""

    def test_inhibit_active_keeps_the_hold_despite_an_open_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bsm, controller = _make_vpp_bsm(soc=17.0)
        _store_verdict(bsm, allowed=True)
        monkeypatch.setattr(controller, "get_discharge_inhibit_active", lambda: True)

        bsm._apply_period_schedule(PERIOD)

        command = _last_vpp_command(controller)
        assert command["power_pct"] == 1
        assert command["remote_control_enabled"] is True

    def test_inhibit_toggling_mid_period_rewrites_an_idle_period(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rate is 0 before and after, so the rate-only dedupe would skip the
        write; the release flag must take part in it."""
        bsm, controller = _make_vpp_bsm(soc=17.0)
        _store_verdict(bsm, allowed=True)
        bsm._apply_period_schedule(PERIOD)
        assert _last_vpp_command(controller)["power_pct"] == 0

        monkeypatch.setattr(controller, "get_discharge_inhibit_active", lambda: True)
        bsm.apply_discharge_inhibit()
        assert _last_vpp_command(controller)["power_pct"] == 1

        monkeypatch.setattr(controller, "get_discharge_inhibit_active", lambda: False)
        bsm.apply_discharge_inhibit()
        assert _last_vpp_command(controller)["power_pct"] == 0
