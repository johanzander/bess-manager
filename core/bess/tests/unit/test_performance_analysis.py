"""BSM serves performance analyses from one cache keyed by what they read."""

import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

import core.bess.battery_system_manager as bsm_module
from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.performance_hindsight import PerformanceAnalysis
from core.bess.price_manager import MockSource
from core.bess.tests.helpers import pinned_datetime_class
from core.bess.tests.unit.test_performance_hindsight import WEEK, synthetic_week


def _manager(mock_controller: Any, path: Path) -> BatterySystemManager:
    manager = BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    manager.daily_view_store = DailyViewStore(path)
    return manager


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    calls: list[date] = []
    real = bsm_module.analyze_period

    def counting(
        store: DailyViewStore, anchor: date, *args: Any, **kwargs: Any
    ) -> PerformanceAnalysis:
        calls.append(anchor)
        return real(store, anchor, *args, **kwargs)

    monkeypatch.setattr(bsm_module, "analyze_period", counting)
    return calls


def test_an_analysis_is_reused_until_its_history_or_settings_change(
    tmp_path: Path, mock_controller: Any, counted: list[date]
) -> None:
    manager = _manager(mock_controller, tmp_path)
    manager.battery_settings = synthetic_week(manager.daily_view_store).battery
    manager.analyze_performance(WEEK, "week")
    manager.analyze_performance(WEEK, "week")
    assert len(counted) == 1
    view = manager.daily_view_store.load_day(date(2026, 9, 8))
    assert view is not None
    view.periods[0].energy.home_consumption += 0.1
    manager.daily_view_store.save_day(view)
    manager.analyze_performance(WEEK, "week")
    assert len(counted) == 2
    manager.battery_settings.cycle_cost_per_kwh += 0.01
    manager.analyze_performance(WEEK, "week")
    assert len(counted) == 3


def test_concurrent_requests_compute_an_analysis_once(
    tmp_path: Path, mock_controller: Any, counted: list[date]
) -> None:
    manager = _manager(mock_controller, tmp_path)
    manager.battery_settings = synthetic_week(manager.daily_view_store).battery
    threads = [
        threading.Thread(target=manager.analyze_performance, args=(WEEK, "week"))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert counted == [WEEK]


def test_without_a_date_the_newest_comparable_period_is_returned(
    tmp_path: Path,
    mock_controller: Any,
    counted: list[date],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        time_utils,
        "datetime",
        pinned_datetime_class(datetime(2026, 9, 23, 12, tzinfo=time_utils.TIMEZONE)),
    )
    manager = _manager(mock_controller, tmp_path)
    manager.battery_settings = synthetic_week(manager.daily_view_store).battery
    # A newer week whose only stored day has no usable observations.
    newer = date(2026, 9, 14)
    manager.daily_view_store.save_day(DailyView(newer, [], 0, 0, 0))
    result = manager.analyze_performance(None, "week")
    assert counted[:2] == [newer, WEEK]
    assert result.start_date == WEEK.isoformat()
    assert result.comparison is not None
