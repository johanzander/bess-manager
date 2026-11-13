"""Force mode through a real schedule update: optimizer -> override -> inverter.

Asserts the command that lands on the (mock) inverter, because the update cycle
has no execution model of its own; the forced modes' physical outcomes are
asserted in core/bess/tests/unit/test_force_mode.py.
"""

import threading
from typing import Any

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.tests.conftest import MockHomeAssistantController

CURRENT_PERIOD = 32  # 08:00


def _intents_from_now(system: BatterySystemManager) -> list[str]:
    inverter_controller = system._inverter_controller
    assert inverter_controller is not None
    return inverter_controller.strategic_intents[CURRENT_PERIOD:96]


def test_forced_export_reaches_the_inverter_and_clearing_restores_the_plan(
    quarterly_battery_system: BatterySystemManager,
    mock_controller: MockHomeAssistantController,
) -> None:
    system = quarterly_battery_system
    assert system.update_battery_schedule(current_period=CURRENT_PERIOD)
    planned = _intents_from_now(system)
    assert set(planned) != {"BATTERY_EXPORT"}

    system.set_force_mode("BATTERY_EXPORT")
    assert system.update_battery_schedule(current_period=CURRENT_PERIOD)

    assert set(_intents_from_now(system)) == {"BATTERY_EXPORT"}
    assert mock_controller.calls["discharge_rate"][-1] == 100
    assert any(
        segment["batt_mode"] == "grid_first" and segment["enabled"]
        for segment in mock_controller.calls["tou_segments"]
    )
    # The dashboard's plan stays the optimizer's own.
    latest = system.schedule_store.get_latest_schedule()
    assert latest is not None
    plan_intents = {
        p.decision.strategic_intent for p in latest.optimization_result.period_data
    }
    assert plan_intents != {"BATTERY_EXPORT"}

    system.set_force_mode(None)
    assert system.update_battery_schedule(current_period=CURRENT_PERIOD)

    assert _intents_from_now(system) == planned


def test_next_day_preparation_forces_tomorrow_from_its_first_period(
    quarterly_battery_system: BatterySystemManager,
) -> None:
    system = quarterly_battery_system
    system.set_force_mode("SOLAR_STORAGE")

    assert system.update_battery_schedule(current_period=0, prepare_next_day=True)

    assert system._inverter_controller is not None
    assert set(system._inverter_controller.strategic_intents) == {"SOLAR_STORAGE"}


def test_clear_during_a_running_cycle_is_not_overwritten_by_it(
    quarterly_battery_system: BatterySystemManager,
) -> None:
    """A user's clear must win over a scheduled cycle already running forced.

    The scheduled cycle reads the force mode before it optimizes; a clear and
    its replan landing mid-cycle must not be followed by that cycle writing
    the forced schedule back over the plan.
    """
    system = quarterly_battery_system
    assert system.update_battery_schedule(current_period=CURRENT_PERIOD)
    planned = _intents_from_now(system)
    system.set_force_mode("BATTERY_EXPORT")

    replan_done = threading.Event()

    def clear_and_replan() -> None:
        system.set_force_mode(None)
        system.update_battery_schedule(current_period=CURRENT_PERIOD)
        replan_done.set()

    real_get_price_data = system._get_price_data
    replan = threading.Thread(target=clear_and_replan)

    def get_price_data_with_a_clear_landing(*args: Any, **kwargs: Any) -> Any:
        if not replan.is_alive() and not replan_done.is_set():
            replan.start()
            # Give the replan the chance to run to completion mid-cycle.
            replan_done.wait(timeout=1.0)
        return real_get_price_data(*args, **kwargs)

    system._get_price_data = get_price_data_with_a_clear_landing  # type: ignore[method-assign]
    assert system.update_battery_schedule(current_period=CURRENT_PERIOD)
    replan.join(timeout=30)
    assert not replan.is_alive()

    assert system.force_mode is None
    assert _intents_from_now(system) == planned
