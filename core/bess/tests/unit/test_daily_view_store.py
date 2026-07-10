"""Unit tests for DailyViewStore."""

import json
import logging
from datetime import date, datetime
from pathlib import Path

from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData


def _make_period(period: int, grid_imported: float, grid_exported: float) -> PeriodData:
    energy = EnergyData(
        solar_production=1.0,
        home_consumption=grid_imported,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.05)
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=datetime(2026, 7, 8, period // 4, (period % 4) * 15),
        data_source="actual",
        economic=economic,
    )


def _make_view(day: date) -> DailyView:
    return DailyView(
        date=day,
        periods=[_make_period(0, 1.0, 0.0), _make_period(1, 0.0, 2.0)],
        total_savings=3.5,
        actual_count=2,
        predicted_count=0,
    )


class TestSaveAndLoad:
    def test_load_day_returns_none_when_nothing_saved(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        assert store.load_day(date(2026, 7, 8)) is None

    def test_save_then_load_round_trips_the_view(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        view = _make_view(date(2026, 7, 8))

        store.save_day(view)
        loaded = store.load_day(date(2026, 7, 8))

        assert loaded is not None
        assert loaded.date == date(2026, 7, 8)
        assert loaded.total_savings == 3.5
        assert len(loaded.periods) == 2
        assert loaded.periods[0].energy.grid_imported == 1.0
        assert loaded.periods[1].economic.sell_price == 1.0

    def test_save_day_overwrites_existing_file_for_same_date(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 8)))
        second_view = DailyView(
            date=date(2026, 7, 8),
            periods=[_make_period(0, 5.0, 0.0)],
            total_savings=9.0,
            actual_count=1,
            predicted_count=0,
        )

        store.save_day(second_view)
        loaded = store.load_day(date(2026, 7, 8))

        assert loaded.total_savings == 9.0
        assert len(loaded.periods) == 1


class TestSaveDayResilience:
    def test_save_day_does_not_raise_when_mkdir_fails(
        self, tmp_path, monkeypatch, caplog
    ):
        store = DailyViewStore(persist_dir=tmp_path / "unwritable")

        def _raise_mkdir(*args, **kwargs):
            raise OSError("Read-only file system")

        monkeypatch.setattr(Path, "mkdir", _raise_mkdir)

        with caplog.at_level(logging.WARNING):
            store.save_day(_make_view(date(2026, 7, 8)))

        assert any(
            "Failed to persist daily view" in record.message
            for record in caplog.records
        )


class TestLoadDayResilience:
    def test_load_day_returns_none_for_schema_invalid_json(self, tmp_path, caplog):
        store = DailyViewStore(persist_dir=tmp_path)
        path = tmp_path / "2026-07-08.json"
        path.write_text(json.dumps({"foo": "bar"}))

        with caplog.at_level(logging.WARNING):
            loaded = store.load_day(date(2026, 7, 8))

        assert loaded is None


class TestListAvailableDates:
    def test_empty_store_returns_empty_list(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        assert store.list_available_dates() == []

    def test_returns_sorted_iso_dates(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 9)))
        store.save_day(_make_view(date(2026, 7, 7)))
        store.save_day(_make_view(date(2026, 7, 8)))

        assert store.list_available_dates() == [
            "2026-07-07",
            "2026-07-08",
            "2026-07-09",
        ]


class TestDiskUsageAndClear:
    def test_disk_usage_zero_when_empty(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        assert store.get_disk_usage() == {"day_count": 0, "total_bytes": 0}

    def test_disk_usage_counts_saved_days(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 7)))
        store.save_day(_make_view(date(2026, 7, 8)))

        usage = store.get_disk_usage()

        assert usage["day_count"] == 2
        assert usage["total_bytes"] > 0

    def test_clear_all_removes_every_saved_day(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        store.save_day(_make_view(date(2026, 7, 7)))
        store.save_day(_make_view(date(2026, 7, 8)))

        store.clear_all()

        assert store.list_available_dates() == []
        assert store.get_disk_usage() == {"day_count": 0, "total_bytes": 0}
