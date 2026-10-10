"""IDLE can cover a forecast miss on load-following (Growatt TOU/cloud) platforms (#811).

A slot whose flows are all within `FLOW_NOISE_FLOOR_KWH` is classified IDLE, and
IDLE was written with discharge rate 0 -- the one intent that could not cover
solar coming in lower (or load higher) than forecast, so the house imported at
the buy price. The sibling intents get their ceiling raised when the DP's
verdict is open (#526); IDLE now gets the same lift, but only when
`idle_hold_releasable` says the IDLE is a fall-through (open verdict and a
planned deficit within the noise floor), never for a deliberate hold: releasing
every open-verdict IDLE measured +3.6 SEK worse over the corpus (#810).

The outcome tests drive `derive_control_command` into `simulate` against a load
the plan did not predict and assert delivered energy and realized cost. The
write-path tests pin the command the BSM sends, which is legitimate here only as
the supplement: the outcome tests are what prove the battery actually covers.
"""

from types import SimpleNamespace

import pytest

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
from core.bess.simulation.inverter_simulator import (
    SimulationResult,
    derive_control_command,
    simulate,
)
from core.bess.strategic_intent import FLOW_NOISE_FLOOR_KWH
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import make_battery_settings

PERIOD = 20
SUB_FLOOR_DEFICIT = 0.008
DELIBERATE_DEFICIT = 0.5


def _make_bsm() -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([2.0] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    return bsm, controller


def _seed_idle_intents(bsm: BatterySystemManager) -> None:
    controller = bsm._inverter_controller
    assert controller is not None
    controller.strategic_intents = ["IDLE"] * 96
    controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)  # type: ignore[assignment]


def _store_idle_period(
    bsm: BatterySystemManager, *, allowed: bool, planned_grid_imported: float
) -> None:
    _seed_idle_intents(bsm)
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=planned_grid_imported,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=planned_grid_imported,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
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
    bsm.schedule_store.store_schedule(
        OptimizationResult(input_data={}, period_data=[period_data]),
        optimization_period=PERIOD,
    )


def _run_idle(
    *, allowed: bool, planned_grid_imported: float, actual_home: float
) -> SimulationResult:
    """Execute one IDLE period against a load the plan did not predict."""
    settings = make_battery_settings()
    command = derive_control_command(
        "IDLE",
        0.0,
        settings,
        intra_period_discharge_allowed=allowed,
        planned_grid_imported_kwh=planned_grid_imported,
    )
    return simulate(
        [command],
        solar_production=[0.0],
        home_consumption=[actual_home],
        buy_price=[2.0],
        sell_price=[0.5],
        initial_soe=10.0,
        settings=settings,
        dt=1.0,
    )


def test_fall_through_idle_covers_a_forecast_miss_from_the_battery() -> None:
    """Open verdict + sub-floor planned deficit: the miss is served from the
    battery rather than imported."""
    sim = _run_idle(
        allowed=True, planned_grid_imported=SUB_FLOOR_DEFICIT, actual_home=2.0
    )
    energy = sim.period_data[0].energy

    assert energy.battery_discharged == pytest.approx(2.0, abs=1e-6)
    assert energy.grid_imported == pytest.approx(0.0, abs=1e-6)


def test_lift_is_worth_the_price_of_the_unforecast_deficit() -> None:
    """The released slot realizes 2 kWh x 2.0 SEK less cost than the held one."""
    held = _run_idle(
        allowed=False, planned_grid_imported=SUB_FLOOR_DEFICIT, actual_home=2.0
    )
    released = _run_idle(
        allowed=True, planned_grid_imported=SUB_FLOOR_DEFICIT, actual_home=2.0
    )

    assert held.realized_cost - released.realized_cost == pytest.approx(4.0, abs=1e-6)


def test_deliberate_idle_with_a_planned_deficit_stays_held() -> None:
    """A planned deficit above the floor was a choice the DP made; an open
    verdict is only a marginal value and must not release it (#810)."""
    assert DELIBERATE_DEFICIT > FLOW_NOISE_FLOOR_KWH
    sim = _run_idle(
        allowed=True, planned_grid_imported=DELIBERATE_DEFICIT, actual_home=2.0
    )
    energy = sim.period_data[0].energy

    assert energy.battery_discharged == pytest.approx(0.0, abs=1e-6)
    assert energy.grid_imported == pytest.approx(2.0, abs=1e-6)


class TestIdleDischargeLiftWritePath:
    def test_fall_through_idle_raises_the_discharge_ceiling(self) -> None:
        bsm, controller = _make_bsm()
        _store_idle_period(bsm, allowed=True, planned_grid_imported=SUB_FLOOR_DEFICIT)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_closed_verdict_keeps_idle_at_zero(self) -> None:
        bsm, controller = _make_bsm()
        _store_idle_period(bsm, allowed=False, planned_grid_imported=0.0)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_deliberate_idle_deficit_keeps_idle_at_zero(self) -> None:
        bsm, controller = _make_bsm()
        _store_idle_period(bsm, allowed=True, planned_grid_imported=DELIBERATE_DEFICIT)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_no_stored_schedule_keeps_idle_at_zero(self) -> None:
        bsm, controller = _make_bsm()
        _seed_idle_intents(bsm)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0
