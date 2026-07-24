"""_get_planned_intent_for_period: timestamp-based schedule lookup.

Regression for issue #380. The same positional-arithmetic bug that
corrupted the dashboard chart at the today/tomorrow midnight boundary also
affects strategic-intent recovery: during the 23:55-00:00 window, the
standalone prepare_next_day schedule (optimization_period=0, period_data[0]
timestamped tomorrow 00:00) was mistaken for today's schedule at the same
positional index.
"""

from datetime import timedelta

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


def _make_bsm() -> BatterySystemManager:
    return BatterySystemManager(
        controller=MockHomeAssistantController(),
        price_source=MockSource([1.0] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )


def _period_data(period: int, timestamp, intent: str) -> PeriodData:
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=0.0,
            battery_soe_start=10.0,
            battery_soe_end=10.0,
        ),
        timestamp=timestamp,
        economic=EconomicData(),
        decision=DecisionData(strategic_intent=intent),
    )


def test_planned_intent_uses_the_schedule_covering_todays_period():
    bsm = _make_bsm()

    today_periods = [
        _period_data(
            92 + i, time_utils.period_index_to_timestamp(92 + i), "LOAD_SUPPORT"
        )
        for i in range(4)
    ]
    bsm.schedule_store.store_schedule(
        OptimizationResult(input_data={}, period_data=today_periods),
        optimization_period=92,
    )

    tomorrow_start = time_utils.period_index_to_timestamp(96)
    tomorrow_periods = [
        _period_data(95, tomorrow_start + timedelta(minutes=15 * 95), "GRID_CHARGE")
    ]
    bsm.schedule_store.store_schedule(
        OptimizationResult(input_data={}, period_data=tomorrow_periods),
        optimization_period=0,
    )

    assert bsm._get_planned_intent_for_period(95) == "LOAD_SUPPORT"
