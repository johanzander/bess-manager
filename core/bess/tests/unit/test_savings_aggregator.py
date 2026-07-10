"""Unit tests for savings_aggregator bucketing."""

from datetime import date, timedelta

import pytest

from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.savings_aggregator import DEFAULT_COUNTS, build_buckets


def _period(grid_imported: float, grid_exported: float) -> PeriodData:
    energy = EnergyData(
        solar_production=2.0,
        home_consumption=grid_imported,
        battery_charged=0.5,
        battery_discharged=0.3,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.1)
    return PeriodData(period=0, energy=energy, economic=economic)


def _seed_day(
    store: DailyViewStore,
    day: date,
    grid_imported: float,
    grid_exported: float,
    savings: float,
) -> None:
    view = DailyView(
        date=day,
        periods=[_period(grid_imported, grid_exported)],
        total_savings=savings,
        actual_count=1,
        predicted_count=0,
    )
    store.save_day(view)


class TestWeekBuckets:
    def test_sums_the_single_saved_day_into_its_week(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        # Wednesday 2026-07-08 is in ISO week 2026-W28 (Mon 2026-07-06 .. Sun 2026-07-12)
        _seed_day(
            store, date(2026, 7, 8), grid_imported=1.0, grid_exported=2.0, savings=3.0
        )

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        assert len(buckets) == 1
        bucket = buckets[0]
        assert bucket.label == "2026-W28"
        assert bucket.start_date == "2026-07-06"
        assert bucket.end_date == "2026-07-12"
        assert bucket.day_count == 1
        assert bucket.totals.import_kwh == 1.0
        assert bucket.totals.export_kwh == 2.0
        assert bucket.totals.import_eur == 2.0  # 1.0 * buy_price 2.0
        assert bucket.totals.export_eur == 2.0  # 2.0 * sell_price 1.0
        assert bucket.totals.grid_cost == 0.0
        assert bucket.totals.savings_vs_grid_only == 3.0

    def test_two_days_in_the_same_week_are_summed(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 7, 6), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )
        _seed_day(
            store, date(2026, 7, 8), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        assert buckets[0].day_count == 2
        assert buckets[0].totals.import_kwh == 2.0
        assert buckets[0].totals.savings_vs_grid_only == 2.0

    def test_multiple_weeks_returned_oldest_first(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 6, 29), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )  # W27
        _seed_day(
            store, date(2026, 7, 8), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )  # W28

        buckets = build_buckets("week", count=2, store=store, today=date(2026, 7, 9))

        assert [b.label for b in buckets] == ["2026-W27", "2026-W28"]

    def test_day_with_no_snapshot_is_not_counted(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)

        buckets = build_buckets("week", count=1, store=store, today=date(2026, 7, 9))

        assert buckets[0].day_count == 0
        assert buckets[0].totals.import_kwh == 0.0

    def test_multi_bucket_sequence_crosses_iso_year_boundary(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        # Jan 2, 2026 is a Friday in ISO week 2026-W01 (Mon 2025-12-29 - Sun 2026-01-04).
        # Stepping back 7 days from the week's Monday (Dec 29) lands on Dec 22, which is in 2025-W52.
        # This gives us a sequence where the ISO year label changes: 2025-W52 → 2026-W01.
        buckets = build_buckets("week", count=2, store=store, today=date(2026, 1, 2))

        assert len(buckets) == 2
        assert [b.label for b in buckets] == ["2025-W52", "2026-W01"]
        # 2025-W52: Mon 2025-12-22 to Sun 2025-12-28
        assert buckets[0].start_date == "2025-12-22"
        assert buckets[0].end_date == "2025-12-28"
        # 2026-W01: Mon 2025-12-29 to Sun 2026-01-04 (contains Jan 4, so labeled as 2026)
        assert buckets[1].start_date == "2025-12-29"
        assert buckets[1].end_date == "2026-01-04"
        # Verify contiguity: next week's start is exactly one day after previous week's end
        assert date.fromisoformat(buckets[1].start_date) == date.fromisoformat(
            buckets[0].end_date
        ) + timedelta(days=1)


class TestMonthBuckets:
    def test_bucket_spans_the_whole_calendar_month(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 7, 15), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )

        buckets = build_buckets("month", count=1, store=store, today=date(2026, 7, 20))

        assert buckets[0].label == "2026-07"
        assert buckets[0].start_date == "2026-07-01"
        assert buckets[0].end_date == "2026-07-31"
        assert buckets[0].day_count == 1

    def test_february_end_date_respects_leap_year(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)

        buckets = build_buckets("month", count=1, store=store, today=date(2028, 2, 10))

        assert buckets[0].end_date == "2028-02-29"

    def test_multi_bucket_sequence_crosses_december_to_january_boundary(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)

        buckets = build_buckets("month", count=2, store=store, today=date(2026, 1, 15))

        assert len(buckets) == 2
        assert [b.label for b in buckets] == ["2025-12", "2026-01"]
        # December bucket: full month
        assert buckets[0].start_date == "2025-12-01"
        assert buckets[0].end_date == "2025-12-31"
        # January bucket: full month
        assert buckets[1].start_date == "2026-01-01"
        assert buckets[1].end_date == "2026-01-31"
        # Verify contiguity: January starts the day after December ends
        assert buckets[1].start_date == "2026-01-01"


class TestYearBuckets:
    def test_bucket_spans_the_whole_calendar_year(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        _seed_day(
            store, date(2026, 3, 1), grid_imported=1.0, grid_exported=0.0, savings=1.0
        )

        buckets = build_buckets("year", count=1, store=store, today=date(2026, 12, 1))

        assert buckets[0].label == "2026"
        assert buckets[0].start_date == "2026-01-01"
        assert buckets[0].end_date == "2026-12-31"
        assert buckets[0].day_count == 1

    def test_multi_bucket_sequence_crosses_year_boundary(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)

        buckets = build_buckets("year", count=2, store=store, today=date(2026, 1, 5))

        assert len(buckets) == 2
        assert [b.label for b in buckets] == ["2025", "2026"]
        # 2025 bucket: full year
        assert buckets[0].start_date == "2025-01-01"
        assert buckets[0].end_date == "2025-12-31"
        # 2026 bucket: full year
        assert buckets[1].start_date == "2026-01-01"
        assert buckets[1].end_date == "2026-12-31"


class TestInvalidPeriod:
    def test_unknown_period_raises(self, tmp_path):
        store = DailyViewStore(persist_dir=tmp_path)
        with pytest.raises(ValueError):
            build_buckets("fortnight", count=1, store=store)


class TestDefaultCounts:
    def test_has_an_entry_for_every_valid_period(self):
        assert set(DEFAULT_COUNTS.keys()) == {"week", "month", "year"}
