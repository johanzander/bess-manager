"""Unit tests for PredictionSnapshotStore."""

import itertools
import json
import os
import threading
import time
from datetime import date, datetime

from core.bess import daily_view_store, prediction_snapshot, time_utils
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
        """Today's snapshot never leaks into yesterday's file, and yesterday's
        snapshots are pruned to one-day retention while its view survives."""
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])
        view_store = DailyViewStore(persist_dir=tmp_path)

        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        view_store.save_day(_make_view(date(2026, 7, 8)))

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
        assert "snapshots" not in day1
        assert day1["view"]["total_savings"] == 3.5
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


class TestConcurrentDayRollover:
    """A day-boundary race must not lose or misfile an in-flight snapshot."""

    def test_in_flight_store_survives_concurrent_rollover(self, tmp_path, monkeypatch):
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        DailyViewStore(persist_dir=tmp_path).save_day(_make_view(date(2026, 7, 8)))

        day1_entered = threading.Event()
        day1_may_append = threading.Event()
        real_ensure_current_day = store._ensure_current_day

        def slow_ensure_current_day(as_of=None):
            real_ensure_current_day(as_of=as_of)
            if current["day"] == date(2026, 7, 8):
                # Thread A has just confirmed it's still "day 1" and is
                # about to append; give thread B a chance to flip the day
                # and race in before A finishes its append + save.
                day1_entered.set()
                day1_may_append.wait(timeout=5)

        monkeypatch.setattr(store, "_ensure_current_day", slow_ensure_current_day)

        errors: list[Exception] = []

        def store_day1_snapshot():
            try:
                store.store_snapshot(
                    snapshot_timestamp=datetime(2026, 7, 8, 23, 59),
                    optimization_period=95,
                    daily_view=_make_view(date(2026, 7, 8)),
                    growatt_schedule=[],
                    predicted_daily_savings=1.0,
                )
            except Exception as e:
                errors.append(e)

        def flip_day_then_store_day2_snapshot():
            day1_entered.wait(timeout=5)
            current["day"] = date(2026, 7, 9)
            day1_may_append.set()
            try:
                store.store_snapshot(
                    snapshot_timestamp=datetime(2026, 7, 9, 0, 0),
                    optimization_period=0,
                    daily_view=_make_view(date(2026, 7, 9)),
                    growatt_schedule=[],
                    predicted_daily_savings=2.0,
                )
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=store_day1_snapshot)
        t2 = threading.Thread(target=flip_day_then_store_day2_snapshot)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"writer thread raised: {errors[0]!r}"
        assert not t1.is_alive() and not t2.is_alive()

        day1_file = json.loads((tmp_path / "2026-07-08.json").read_text())
        day2_file = json.loads((tmp_path / "2026-07-09.json").read_text())
        # Thread A's day-1 snapshot must never be misfiled into day 2's file by
        # the concurrent rollover (see TestSnapshotFiledUnderItsOwnDate for the
        # deterministic single-threaded case).
        assert [s["optimization_period"] for s in day2_file["snapshots"]] == [0]
        # Both threads serialize on _instance_lock, so A's append+save to day 1
        # completes before B's rollover prunes it under one-day retention. Day
        # 1's view - the part that is real history - is untouched.
        assert "snapshots" not in day1_file
        assert day1_file["view"]["total_savings"] == 3.5


class TestTempFileHousekeeping:
    def test_write_removes_orphaned_temp_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        orphan = tmp_path / "2026-07-08.99999-deadbeef.tmp"
        orphan.write_text("{partial")
        # Aged past the in-flight threshold: a real crashed write, not a
        # concurrent writer's live temp file (see TestTempFileOwnership).
        old = time.time() - 3600
        os.utime(orphan, (old, old))

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


class TestOneDayRetention:
    """Snapshots stay today-only on disk, as they were before #409.

    Consolidating the *format* into the shared per-day file must not silently
    change the *lifecycle*. Pre-#409 the snapshot file was discarded unless it
    was dated today, so a year of history cost ~30 MB. Letting every day keep
    its ~96 embedded DailyViews takes that to ~2.9 GB on an SD-backed /data.
    """

    def test_rollover_prunes_previous_days_snapshots_from_disk(
        self, tmp_path, monkeypatch
    ):
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
        DailyViewStore(persist_dir=tmp_path).save_day(_make_view(date(2026, 7, 8)))

        day1 = tmp_path / "2026-07-08.json"
        assert json.loads(day1.read_text())["snapshots"]

        current["day"] = date(2026, 7, 9)
        store.get_snapshot_count()  # any public access triggers rollover

        raw = json.loads(day1.read_text())
        assert "snapshots" not in raw, "yesterday's snapshots must be pruned"
        assert raw["view"]["total_savings"] == 3.5, "the day's view must survive"

    def test_startup_sweep_prunes_snapshots_left_by_a_previous_process(
        self, tmp_path, monkeypatch
    ):
        """A restart across midnight never runs the in-process rollover."""
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        stale = tmp_path / "2026-07-07.json"
        stale.write_text(
            json.dumps({"view": {"total_savings": 1.0}, "snapshots": [{"x": 1}]})
        )

        PredictionSnapshotStore(persist_dir=tmp_path)

        raw = json.loads(stale.read_text())
        assert "snapshots" not in raw
        assert raw["view"] == {"total_savings": 1.0}

    def test_sweep_deletes_a_snapshot_only_file_with_no_view(
        self, tmp_path, monkeypatch
    ):
        """A view-less file would otherwise be advertised by
        list_available_dates() and then 404 / dilute the savings average."""
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        orphan = tmp_path / "2026-07-06.json"
        orphan.write_text(json.dumps({"snapshots": [{"x": 1}]}))

        PredictionSnapshotStore(persist_dir=tmp_path)

        assert not orphan.exists()
        assert DailyViewStore(persist_dir=tmp_path).list_available_dates() == []

    def test_rollover_prune_is_scoped_to_the_day_that_just_ended(
        self, tmp_path, monkeypatch
    ):
        """A midnight rollover must not re-scan the whole history directory.

        Only the previous day's file can have gained snapshots while the
        process was running; sweeping every file an install has ever written
        costs a full glob+parse under container_lock every midnight.
        """
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        # Written after startup, so the startup sweep never saw it.
        untouched = tmp_path / "2026-01-01.json"
        untouched.write_text(
            json.dumps({"view": {"total_savings": 9.0}, "snapshots": [{"x": 1}]})
        )
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )
        DailyViewStore(persist_dir=tmp_path).save_day(_make_view(date(2026, 7, 8)))

        current["day"] = date(2026, 7, 9)
        store.get_snapshot_count()

        assert "snapshots" not in json.loads((tmp_path / "2026-07-08.json").read_text())
        # The unrelated old file was not visited: rollover touches one file.
        assert json.loads(untouched.read_text())["snapshots"] == [{"x": 1}]

    def test_sweep_leaves_todays_snapshots_alone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        store = PredictionSnapshotStore(persist_dir=tmp_path)
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 6, 0),
            optimization_period=24,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        assert PredictionSnapshotStore(persist_dir=tmp_path).get_snapshot_count() == 1

    def test_sweep_preserves_a_legacy_flat_view_file(self, tmp_path, monkeypatch):
        """Pre-#409 flat files are the whole DailyView dict - not view-less."""
        from dataclasses import asdict

        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        legacy = tmp_path / "2026-07-05.json"
        legacy.write_text(json.dumps(asdict(_make_view(date(2026, 7, 5))), default=str))

        PredictionSnapshotStore(persist_dir=tmp_path)

        assert legacy.exists()
        loaded = DailyViewStore(persist_dir=tmp_path).load_day(date(2026, 7, 5))
        assert loaded is not None and loaded.total_savings == 3.5


class TestLegacyPersistFileRemoval:
    """The pre-#409 /data/bess_prediction_snapshots.json is superseded.

    Nothing references it after this change, so left in place it would sit on
    /data forever.
    """

    def test_startup_removes_the_legacy_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        legacy = tmp_path / "bess_prediction_snapshots.json"
        legacy.write_text(json.dumps({"date": "2026-07-08", "snapshots": []}))
        data_dir = tmp_path / "daily_views"
        monkeypatch.setattr(prediction_snapshot, "PERSIST_DIR", data_dir)
        monkeypatch.setattr(prediction_snapshot, "LEGACY_PERSIST_PATH", legacy)

        PredictionSnapshotStore(persist_dir=data_dir)

        assert not legacy.exists()

    def test_a_store_on_another_root_leaves_the_legacy_file_alone(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        legacy = tmp_path / "bess_prediction_snapshots.json"
        legacy.write_text("{}")
        monkeypatch.setattr(prediction_snapshot, "PERSIST_DIR", tmp_path / "real")
        monkeypatch.setattr(prediction_snapshot, "LEGACY_PERSIST_PATH", legacy)

        PredictionSnapshotStore(persist_dir=tmp_path / "elsewhere")

        assert legacy.exists()


class TestSnapshotFiledUnderItsOwnDate:
    def test_snapshot_built_before_midnight_lands_in_its_own_day_file(
        self, tmp_path, monkeypatch
    ):
        """The caller stamps snapshot_timestamp; if the clock ticks past
        midnight before the lock is acquired, the snapshot must still be filed
        under the day it describes, not the day it was written."""
        current = {"day": date(2026, 7, 8)}
        monkeypatch.setattr(time_utils, "today", lambda: current["day"])
        store = PredictionSnapshotStore(persist_dir=tmp_path)

        current["day"] = date(2026, 7, 9)  # midnight passes before the write
        store.store_snapshot(
            snapshot_timestamp=datetime(2026, 7, 8, 23, 59, 55),
            optimization_period=95,
            daily_view=_make_view(date(2026, 7, 8)),
            growatt_schedule=[],
            predicted_daily_savings=3.0,
        )

        day1 = json.loads((tmp_path / "2026-07-08.json").read_text())
        assert len(day1["snapshots"]) == 1
        assert not (tmp_path / "2026-07-09.json").exists()


class TestCorruptSnapshotIsBestEffort:
    def test_malformed_snapshot_entry_does_not_raise(self, tmp_path, monkeypatch):
        """_load_from_disk runs inside every public accessor, so a schema-shifted
        entry must not turn /api/prediction-analysis/snapshots into a 500."""
        monkeypatch.setattr(time_utils, "today", lambda: date(2026, 7, 8))
        path = tmp_path / "2026-07-08.json"
        # Every key present, so the old `except (KeyError, ValueError)` does not
        # catch it: _daily_view_from_dict does d["periods"] on a str, raising
        # TypeError.
        path.write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "snapshot_timestamp": "2026-07-08T06:00:00",
                            "optimization_period": 24,
                            "daily_view": "not-a-dict",
                            "growatt_schedule": [],
                            "predicted_daily_savings": 1.0,
                        }
                    ]
                }
            )
        )

        store = PredictionSnapshotStore(persist_dir=tmp_path)

        assert store.get_all_snapshots_today() == []


class TestTempFileOwnership:
    def test_write_leaves_a_fresh_foreign_temp_file_alone(self, tmp_path):
        """container_lock is process-local; another process's in-flight temp
        file must not be unlinked out from under its os.replace()."""
        path = tmp_path / "2026-07-08.json"
        foreign = tmp_path / "2026-07-08.99999-deadbeef.tmp"
        foreign.write_text("{}")

        daily_view_store._write_container(path, {"view": None})

        assert foreign.exists()
