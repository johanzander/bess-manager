"""Force mode through a real schedule update: optimizer -> override -> inverter.

Asserts the command that lands on the (mock) inverter, because the update cycle
has no execution model of its own; the forced modes' physical outcomes are
asserted in core/bess/tests/unit/test_force_mode.py.
"""

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
