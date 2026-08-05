"""Regression for issue #380: discharge-rate shadow-price gate must not be
fooled by a standalone next-day schedule.

Around 23:55 every day, BatterySystemManager stores a next-day-only
schedule (optimization_period=0, period_data[0] timestamped tomorrow
00:00). The SOLAR_EXPORT/SOLAR_STORAGE intra-period discharge gate
(_apply_period_schedule) looks up the current period's shadow_price via
schedule_store.get_latest_schedule() + positional arithmetic -- during that
window this silently pulled tomorrow's shadow_price into today's gate
decision instead of today's real value, live-affecting battery hardware
control, not just the dashboard.
"""

from datetime import timedelta
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

PERIOD = 95  # 23:45 -- the tail period affected by the 23:55 prepare_next_day run


def _make_bsm(
    buy_prices: list[float],
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource(buy_prices),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)


def _period_data(period: int, timestamp, shadow_price: float) -> PeriodData:
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
        decision=DecisionData(
            strategic_intent="SOLAR_EXPORT", shadow_price=shadow_price
        ),
    )


def test_gate_uses_todays_shadow_price_not_next_day_schedules():
    # buy_price * efficiency_discharge (0.95 default) is comfortably above
    # today's real shadow_price (0.5) -> gate should OPEN (100).
    bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
    _set_intent(bsm, PERIOD, "SOLAR_EXPORT")

    # Today's real schedule, made moments earlier, with a low shadow_price.
    today_ts = time_utils.period_index_to_timestamp(PERIOD)
    bsm.schedule_store.store_schedule(
        OptimizationResult(
            input_data={},
            period_data=[_period_data(PERIOD, today_ts, shadow_price=0.5)],
        ),
        optimization_period=PERIOD,
    )

    # The prepare_next_day schedule stored at 23:55: optimization_period=0,
    # period_data[0] anchored to tomorrow 00:00, with a high shadow_price
    # that would close the gate (0) if wrongly read as today's period 95.
    tomorrow_ts = time_utils.period_index_to_timestamp(96) + timedelta(minutes=15 * 95)
    bsm.schedule_store.store_schedule(
        OptimizationResult(
            input_data={},
            period_data=[_period_data(95, tomorrow_ts, shadow_price=4.0)],
        ),
        optimization_period=0,
    )

    bsm._apply_period_schedule(PERIOD)

    assert controller.calls["discharge_rate"][-1] == 100
