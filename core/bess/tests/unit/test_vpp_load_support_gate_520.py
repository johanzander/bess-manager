"""VPP half of #520: LOAD_SUPPORT must consult the intra-period discharge gate.

TOU got this in #524. VPP was left releasing control unconditionally, so the
same house, same prices and same plan behave differently depending on which
inverter you own -- which is the asymmetry #520 exists to remove.

**Why this is a BSM-integration test rather than a plan-faithfulness (R == P)
scenario.** `implement-issue`'s required test shape for control/rate mapping
changes is `run_scenario_realized`, but `simulation/inverter_simulator.py` is
"Growatt MIN / cloud, execution-only" -- it has no VPP mode at all, so an
R == P scenario would exercise the load-following path and prove nothing
about the branch changed here. This mirrors
`test_vpp_discharge_gate_capability.py`, which exists for the same reason and
asserts on the VPP command actually written to hardware.

**The mapping is not the intuitive one** (#466, `INVERTER_PLATFORMS.md`
"IDLE semantics"): with remote control enabled the *sign* of `vpp_power`
selects the firmware priority, and `<= 0` is `grid_first`, which still draws
self-consumption from the battery (#118). Only `> 0` (`battery_first`)
releases the house to grid/solar. So a closed gate must write `+1`, not `0`
-- writing `0` would look correct and quietly keep discharging.
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

PERIOD = 20


def _make_bsm(control_mode: str):
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([2.0] * 96),
        addon_options={
            "inverter": {
                "platform": "solax_modbus_growatt_min",
                "control_mode": control_mode,
            }
        },
    )
    return bsm, controller


def _set_intent(bsm, period, intent):
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)


def _store_authorization(bsm, period, intent, allowed):
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=0.5,
        battery_charged=0.0,
        battery_discharged=0.3,
        grid_imported=0.2,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=9.7,
    )
    decision = DecisionData(
        strategic_intent=intent, intra_period_discharge_allowed=allowed
    )
    result = OptimizationResult(
        input_data={},
        period_data=[
            PeriodData(
                period=period,
                energy=energy,
                timestamp=time_utils.period_index_to_timestamp(period),
                economic=EconomicData(),
                decision=decision,
            )
        ],
    )
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestVppLoadSupportGate:
    def test_gate_open_releases_control_to_load_following(self):
        """Unchanged behaviour (#413): the battery is the cheaper source, so
        hand control to the inverter's own load-following self-use, which
        covers a within-period spike without a forced rate."""
        bsm, controller = _make_bsm("vpp")
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _store_authorization(bsm, PERIOD, "LOAD_SUPPORT", allowed=True)

        bsm._apply_period_schedule(PERIOD)

        call = controller.calls["growatt_vpp_periods"][-1]
        assert call["power_pct"] == 0
        assert call["remote_control_enabled"] is False

    def test_gate_closed_holds_the_battery_instead_of_releasing(self):
        """The DP says this stored energy is worth more later than the grid
        costs now, so a within-period spike must be imported, not taken from
        the battery. Releasing control would let the inverter spend it."""
        bsm, controller = _make_bsm("vpp")
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _store_authorization(bsm, PERIOD, "LOAD_SUPPORT", allowed=False)

        bsm._apply_period_schedule(PERIOD)

        call = controller.calls["growatt_vpp_periods"][-1]
        assert call["remote_control_enabled"] is True, (
            "releasing control hands the battery to load_first self-use, "
            "which is exactly what a closed gate must prevent"
        )
        assert call["power_pct"] > 0, (
            "power_pct <= 0 with remote control enabled selects grid_first, "
            "which still draws self-consumption from the battery (#118) -- "
            "only battery_first (> 0) releases the house to grid/solar"
        )

    def test_tou_mode_is_unaffected_by_the_vpp_mapping(self):
        """#524's TOU path stays as merged -- this change is VPP-only."""
        bsm, controller = _make_bsm("tou")
        _set_intent(bsm, PERIOD, "LOAD_SUPPORT")
        _store_authorization(bsm, PERIOD, "LOAD_SUPPORT", allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert not controller.calls.get("growatt_vpp_periods")
