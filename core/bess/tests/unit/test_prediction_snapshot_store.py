"""Unit tests for PredictionSnapshotStore."""

import itertools
import json
import threading
import time
from datetime import date, datetime

from core.bess import daily_view_store, time_utils
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


class TestDayRollover:
    """A single long-lived store must roll its in-memory list over at midnight.

    PredictionSnapshotStore is constructed once at process start and lives for
    the lifetime of the add-on, so a new calendar day must not inherit the
    previous day's snapshots.
    """

    def test_long_lived_store_drops_previous_day_snapshots(self, tmp_path, monkeypatch):
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])

        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        assert store.get_snapshot_count() == 1

        # Midnight passes; same store instance, no restart, no clear() call.
        current["day"] = date(2026, 7, 9)

        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 9, 6, 0),
            optimization_period=25,
            daily_view=_make_view(date(2026, 7, 9)),
            growatt_schedule=[],
            predicted_daily_savings=7.0,
        )

        snapshots = store.get_all_snapshots_today()
        assert len(snapshots) == 1
        assert snapshots[0].optimization_period == 25
        assert store.get_snapshot_count() == 1

    def test_rollover_writes_only_new_day_file(self, tmp_path, monkeypatch):
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])

        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        current["day"] = date(2026, 7, 9)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 9, 6, 0),
            optimization_period=25,
            daily_view=_make_view(date(2026, 7, 9)),
            growatt_schedule=[],
            predicted_daily_savings=7.0,
        )

        day1 = json.loads((tmp_path / "2026-07-08.json").read_text())
        day2 = json.loads((tmp_path / "2026-07-09.json").read_text())
        # Yesterday's file is untouched by today's writes.
        assert [s["optimization_period"] for s in day1["snapshots"]] == [24]
        assert [s["optimization_period"] for s in day2["snapshots"]] == [25]

    def test_read_only_access_also_rolls_over(self, tmp_path, monkeypatch):
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])

        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        current["day"] = date(2026, 7, 9)

        assert store.get_all_snapshots_today() == []
        assert store.get_snapshot_at_period(24) is None
        assert store.get_snapshot_count() == 0


class TestConcurrentSharedFileWrites:
    """Both stores mutate the same {date}.json; writes must not lose keys."""

    def test_interleaved_threaded_writes_keep_both_keys_intact(
        self, tmp_path, monkeypatch
    ):
        day = date(2026, 7, 8)
        monkeypatch.setattr(time_utils, "today", lambda: day)
        view_store = DailyViewStore(persist_dir=tmp_path)
        snapshot_store = PredictionSnapshotStore(persist_dir=tmp_path)
        path = tmp_path / "2026-07-08.json"

        # Widen the load->write window so an unguarded read-modify-write loses
        # an update deterministically instead of relying on timing luck, and
        # record the snapshot count of every container actually written.
        real_write = daily_view_store._write_container
        observed_counts: list[int] = []
        observe_lock = threading.Lock()

        def slow_write(p, c):
            time.sleep(0.002)
            with observe_lock:
                observed_counts.append(len(c.get("snapshots", [])))
            real_write(p, c)

        monkeypatch.setattr(daily_view_store, "_write_container", slow_write)

        iterations = 50
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def run(work):
            for _ in range(iterations):
                try:
                    barrier.wait(timeout=30)
                    work()
                except Exception as e:
                    errors.append(e)
                    barrier.abort()
                    return

        def write_view():
            view_store.save_day(_make_view(day))

        def write_snapshot():
            snapshot_store.store_snapshot(
                snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
                optimization_period=24,
                daily_view=_make_view(day),
                growatt_schedule=[],
                predicted_daily_savings=3.0,
            )

        threads = [
            threading.Thread(target=run, args=(write_view,)),
            threading.Thread(target=run, args=(write_snapshot,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert not errors, f"writer thread raised: {errors[0]!r}"
        assert all(not t.is_alive() for t in threads)

        # The core lost-update invariant: because the whole load-mutate-write
        # cycle is serialized, every container written observes at least as
        # many snapshots as the previously written one. A stale read (no lock)
        # shows up here as a regression, even though later writes would mask
        # it in the final file.
        regressions = [
            (i, prev, cur)
            for i, (prev, cur) in enumerate(itertools.pairwise(observed_counts))
            if cur < prev
        ]
        assert not regressions, f"lost update - snapshot count regressed: {regressions}"

        # File must parse and retain both stores' keys.
        container = json.loads(path.read_text())
        assert "view" in container
        assert len(container["snapshots"]) == iterations
        assert view_store.load_day(day) is not None
        assert (
            len(PredictionSnapshotStore(persist_dir=tmp_path).get_all_snapshots_today())
            == iterations
        )

        # No orphaned temp files left behind.
        assert list(tmp_path.glob("*.tmp")) == []

    def test_sequential_mixed_writes_never_drop_a_key(self, tmp_path, monkeypatch):
        day = date(2026, 7, 8)
        monkeypatch.setattr(time_utils, "today", lambda: day)
        view_store = DailyViewStore(persist_dir=tmp_path)
        snapshot_store = PredictionSnapshotStore(persist_dir=tmp_path)
        path = tmp_path / "2026-07-08.json"

        for i in range(50):
            view_store.save_day(_make_view(day))
            snapshot_store.store_snapshot(
                snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
                optimization_period=i,
                daily_view=_make_view(day),
                growatt_schedule=[],
                predicted_daily_savings=float(i),
            )
            container = json.loads(path.read_text())
            assert "view" in container
            assert len(container["snapshots"]) == i + 1


class TestTempFileHousekeeping:
    def test_write_removes_orphaned_temp_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        orphan = tmp_path / "2026-07-08.99999-deadbeef.tmp"
        orphan.write_text("{partial")

        DailyViewStore(persist_dir=tmp_path).save_day(_make_view(date(2026, 7, 8)))

        assert not orphan.exists()
        assert list(tmp_path.glob("*.tmp")) == []


class TestLegacyFlatFormatFallback:
    def test_snapshots_start_empty_for_pre_consolidation_flat_file(
        self, tmp_path, monkeypatch
    ):
        """A DailyViewStore file written before this change has no
        "snapshots" key at all - should load as zero snapshots, not error."""
        from dataclasses import asdict

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        path = tmp_path / "2026-07-08.json"
        path.write_text(json.dumps(asdict(_make_view(date(2026, 7, 8))), default=str))

        store = PredictionSnapshotStore(persist_dir=tmp_path)

        assert store.get_all_snapshots_today() == []
