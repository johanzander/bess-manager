"""A completed day must not remain 95 actual quarters plus one prediction."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.exceptions import HistoricalDataUnavailableError
from core.bess.ha_recorder_helper import get_sensor_data_batch
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.performance_hindsight import historical_context
from core.bess.price_manager import MockSource
from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings
from core.bess.tests.helpers import pinned_datetime_class
from core.bess.tests.unit.test_sensor_collector_gapfill import (
    _entity_map,
    _make_ha_controller,
)


def _pin(monkeypatch: pytest.MonkeyPatch, day: date, minute: int = 0) -> None:
    tz = ZoneInfo("Europe/Helsinki")
    monkeypatch.setattr(time_utils, "TIMEZONE", tz)
    monkeypatch.setattr(
        time_utils,
        "datetime",
        pinned_datetime_class(
            datetime.combine(day, datetime.min.time(), tzinfo=tz)
            + timedelta(minutes=minute)
        ),
    )


def _manager(mock_controller: Any, path: Path) -> BatterySystemManager:
    manager = BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    manager.daily_view_store = DailyViewStore(path)
    return manager


def _unfinished(manager: BatterySystemManager, day: date) -> None:
    count = time_utils.get_period_count(day)
    context = historical_context(
        manager.battery_settings, manager.home_settings, manager.platform_capabilities
    )
    rows = []
    for index in range(count):
        energy = EnergyData(
            0,
            0.25,
            0,
            0,
            0.25,
            0,
            manager.battery_settings.min_soe_kwh,
            manager.battery_settings.min_soe_kwh,
            observation_verified=True,
        )
        rows.append(
            PeriodData(
                index,
                energy,
                time_utils.period_start(day, index),
                "predicted" if index == count - 1 else "actual",
                EconomicData.from_energy_data(energy, 0.173, -0.01),
                historical_inputs=context,
            )
        )
    manager.daily_view_store.save_day(
        DailyView(day, rows, 0, count - 1, 1, finalization_pending=True)
    )


@pytest.mark.parametrize(
    "day,count",
    [(date(2026, 11, 9), 96), (date(2026, 3, 29), 92), (date(2026, 10, 25), 100)],
)
def test_midnight_finalizes_previous_day_using_its_original_price(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_controller: Any,
    day: date,
    count: int,
) -> None:
    _pin(monkeypatch, day + timedelta(days=1))
    manager = _manager(mock_controller, tmp_path)
    _unfinished(manager, day)
    monkeypatch.setattr(
        manager.sensor_collector,
        "collect_energy_data",
        MagicMock(
            return_value=EnergyData(
                0,
                0.31,
                0,
                0,
                0.31,
                0,
                manager.battery_settings.min_soe_kwh,
                manager.battery_settings.min_soe_kwh,
                observation_verified=True,
            )
        ),
    )
    manager._handle_special_cases(0, False, False)
    view = manager.daily_view_store.load_day(day)
    assert view is not None
    assert view.actual_count == count
    assert view.predicted_count == 0
    assert not view.finalization_pending
    assert view.periods[-1].energy.home_consumption == pytest.approx(0.31)
    assert view.periods[-1].economic.grid_cost == pytest.approx(0.31 * 0.173)
    assert view.periods[-1].timestamp == time_utils.period_start(day, count - 1)


def test_delayed_recorder_retries_after_restart_without_relabelling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_controller: Any
) -> None:
    day = date(2026, 11, 9)
    _pin(monkeypatch, day + timedelta(days=1))
    manager = _manager(mock_controller, tmp_path)
    _unfinished(manager, day)
    path = tmp_path / f"{day}.json"
    original = path.read_bytes()
    monkeypatch.setattr(
        manager.sensor_collector,
        "collect_energy_data",
        MagicMock(side_effect=HistoricalDataUnavailableError("recorder not ready")),
    )
    manager._handle_special_cases(0, False, False)
    assert path.read_bytes() == original
    _pin(monkeypatch, day + timedelta(days=2), 15)
    restarted = _manager(mock_controller, tmp_path)
    monkeypatch.setattr(
        restarted.sensor_collector,
        "collect_energy_data",
        MagicMock(
            return_value=EnergyData(
                0,
                0.4,
                0,
                0,
                0.4,
                0,
                restarted.battery_settings.min_soe_kwh,
                restarted.battery_settings.min_soe_kwh,
                observation_verified=True,
            )
        ),
    )
    restarted._handle_special_cases(1, False, True)
    view = restarted.daily_view_store.load_day(day)
    assert view is not None and view.actual_count == 96
    assert view.periods[-1].energy.grid_imported == pytest.approx(0.4)


def test_past_collection_does_not_corrupt_today_cache_or_use_live_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = date(2026, 11, 9)
    _pin(monkeypatch, day + timedelta(days=1), 30)
    ha = _make_ha_controller()
    manager_settings = BatterySettings(total_capacity=21)
    collector = SensorCollector(ha, manager_settings)
    readings = {
        value: 100.0
        for key, value in _entity_map().items()
        if key.startswith("lifetime_")
    }
    readings["soc_entity"] = 50
    end = {**readings, "import_entity": 100.3}
    monkeypatch.setattr(
        collector, "_get_period_readings", MagicMock(side_effect=[end, readings])
    )
    collector._last_readings = {"today-sentinel": 1}
    ha.get_battery_soc.side_effect = AssertionError(
        "No live SOC substitution for historical periods"
    )
    energy = collector.collect_energy_data(95, target_date=day)
    assert energy.grid_imported == pytest.approx(0.3)
    assert collector._last_readings == {"today-sentinel": 1}
    del end["soc_entity"]
    monkeypatch.setattr(
        collector, "_get_period_readings", MagicMock(side_effect=[end, readings])
    )
    with pytest.raises(HistoricalDataUnavailableError):
        collector.collect_energy_data(95, target_date=day)


@pytest.mark.parametrize(
    "day,count", [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)]
)
def test_recorder_uses_elapsed_quarters_and_includes_the_midnight_boundary(
    monkeypatch: pytest.MonkeyPatch, day: date, count: int
) -> None:
    _pin(monkeypatch, day + timedelta(days=1))
    controller = MagicMock()
    history = [
        [
            {
                "entity_id": "sensor.counter",
                "state": "100",
                "last_changed": time_utils.period_start(day, 0).isoformat(),
            },
            {
                "state": "101",
                "last_changed": time_utils.period_start(day, count).isoformat(),
            },
        ]
    ]
    # Exercise a recorder that excludes end_time, as range queries can do.
    controller.get_history_period.side_effect = lambda ids, start, end: [
        [
            entry
            for entry in history[0]
            if datetime.fromisoformat(entry["last_changed"]).timestamp()
            < datetime.fromisoformat(end).timestamp()
        ]
    ]
    result = get_sensor_data_batch(controller, ["counter"], day)
    assert len(result["data"]) == count
    assert result["data"][count - 1]["sensor.counter"] == 101


def test_next_day_preparation_confirms_and_corrects_todays_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_controller: Any
) -> None:
    day = date(2026, 11, 9)
    _pin(monkeypatch, day, minute=23 * 60 + 55)
    manager = _manager(mock_controller, tmp_path)
    final_buy, final_sell = manager.price_manager.get_available_prices()
    energy = EnergyData(0, 0.4, 0, 0, 0.4, 0, 5, 5, observation_verified=True)
    # Quarter 0 kept a stale forecast price; quarter 1 already had the final one.
    manager.historical_store.record_period(
        0,
        PeriodData(
            0, energy, None, "actual", EconomicData.from_energy_data(energy, 0.5, 0.1)
        ),
    )
    manager.historical_store.record_period(
        1,
        PeriodData(
            1,
            energy,
            None,
            "actual",
            EconomicData.from_energy_data(energy, final_buy[1], final_sell[1]),
        ),
    )
    manager._handle_special_cases(95, True, False)
    for period in (0, 1):
        stored = manager.historical_store.get_period(period)
        assert stored is not None
        assert stored.economic.buy_price == pytest.approx(final_buy[period])
        assert stored.economic.prices_verified is True
        assert stored.economic.import_cost == pytest.approx(0.4 * final_buy[period])
