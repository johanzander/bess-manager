"""Unit tests for PredictionSnapshotStore."""

from datetime import date, datetime

from core.bess import time_utils
from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.prediction_snapshot import PredictionSnapshotStore


def _make_period(period: int) -> PeriodData:
    energy = EnergyData(
        solar_production=1.0,
        home_consumption=1.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=1.0,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.05)
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=datetime(2026, 7, 8, period // 4, (period % 4) * 15),
        data_source="predicted",
        economic=economic,
    )


def _make_view(day: date) -> DailyView:
    return DailyView(
        date=day,
        periods=[_make_period(0), _make_period(1)],
        total_savings=3.5,
        actual_count=0,
        predicted_count=2,
    )


class TestStoreAndRetrieve:
    def test_store_snapshot_round_trips_through_disk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[{"start": "00:00", "end": "06:00"}],
            predicted_daily_savings=12.5,
        )

        reloaded = PredictionSnapshotStore(persist_dir=tmp_path)
        snapshots = reloaded.get_all_snapshots_today()

        assert len(snapshots) == 1
        assert snapshots[0].optimization_period == 24
        assert snapshots[0].predicted_daily_savings == 12.5
        assert snapshots[0].daily_view.total_savings == 3.5
        assert snapshots[0].growatt_schedule == [{"start": "00:00", "end": "06:00"}]

    def test_get_all_snapshots_today_orders_chronologically(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 12, 0),
            optimization_period=48,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=5.0,
        )
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        ordered = store.get_all_snapshots_today()
        assert [s.optimization_period for s in ordered] == [24, 48]

    def test_get_snapshot_at_period_returns_closest_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 12, 0),
            optimization_period=48,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=5.0,
        )

        closest = store.get_snapshot_at_period(50)
        assert closest.optimization_period == 48

    def test_get_snapshot_at_period_returns_none_when_empty(self, tmp_path):
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        assert store.get_snapshot_at_period(10) is None


class TestClearAndCount:
    def test_clear_empties_snapshots_and_persists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        store.clear()

        assert store.get_snapshot_count() == 0
        reloaded = PredictionSnapshotStore(persist_dir=tmp_path)
        assert reloaded.get_snapshot_count() == 0

    def test_get_snapshot_count_starts_at_zero(self, tmp_path):
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        assert store.get_snapshot_count() == 0


class TestSharedFileWithDailyViewStore:
    def test_snapshot_write_does_not_clobber_daily_view(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        view_store = DailyViewStore(persist_dir=tmp_path)
        snapshot_store = PredictionSnapshotStore(persist_dir=tmp_path)

        view_store.save_day(_make_view(date(2026, 7, 8)))
        snapshot_store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        assert view_store.load_day(date(2026, 7, 8)) is not None
        assert (
            len(PredictionSnapshotStore(persist_dir=tmp_path).get_all_snapshots_today())
            == 1
        )

    def test_daily_view_save_after_snapshot_write_preserves_snapshots(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        view_store = DailyViewStore(persist_dir=tmp_path)
        snapshot_store = PredictionSnapshotStore(persist_dir=tmp_path)

        snapshot_store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        view_store.save_day(_make_view(date(2026, 7, 8)))

        assert (
            len(PredictionSnapshotStore(persist_dir=tmp_path).get_all_snapshots_today())
            == 1
        )


class TestLegacyFlatFormatFallback:
    def test_snapshots_start_empty_for_pre_consolidation_flat_file(
        self, tmp_path, monkeypatch
    ):
        """A DailyViewStore file written before this change has no
        "snapshots" key at all - should load as zero snapshots, not error."""
        import json
        from dataclasses import asdict

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        path = tmp_path / "2026-07-08.json"
        path.write_text(json.dumps(asdict(_make_view(date(2026, 7, 8))), default=str))

        store = PredictionSnapshotStore(persist_dir=tmp_path)

        assert store.get_all_snapshots_today() == []
