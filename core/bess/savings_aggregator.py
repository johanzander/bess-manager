"""Aggregates persisted DailyView snapshots (DailyViewStore) into week/month/year buckets."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from .daily_view_builder import DailyView

VALID_PERIODS = ("day", "week", "month", "year")

DEFAULT_COUNTS: dict[str, int] = {"day": 1, "week": 12, "month": 12, "year": 5}


@dataclass
class DailyTotals:
    """Sums of one or more days' energy/economic fields."""

    import_kwh: float = 0.0
    import_eur: float = 0.0
    export_kwh: float = 0.0
    export_eur: float = 0.0
    grid_cost: float = 0.0
    grid_only_cost: float = 0.0
    battery_cycle_cost: float = 0.0
    savings_vs_grid_only: float = 0.0
    solar_kwh: float = 0.0
    battery_charged_kwh: float = 0.0
    battery_discharged_kwh: float = 0.0

    @classmethod
    def from_daily_view(cls, view: DailyView) -> DailyTotals:
        import_kwh = sum(p.energy.grid_imported for p in view.periods)
        export_kwh = sum(p.energy.grid_exported for p in view.periods)
        import_eur = sum(
            p.energy.grid_imported * p.economic.buy_price for p in view.periods
        )
        export_eur = sum(
            p.energy.grid_exported * p.economic.sell_price for p in view.periods
        )
        return cls(
            import_kwh=import_kwh,
            import_eur=import_eur,
            export_kwh=export_kwh,
            export_eur=export_eur,
            grid_cost=import_eur - export_eur,
            grid_only_cost=sum(p.economic.grid_only_cost for p in view.periods),
            battery_cycle_cost=sum(p.economic.battery_cycle_cost for p in view.periods),
            savings_vs_grid_only=view.total_savings,
            solar_kwh=sum(p.energy.solar_production for p in view.periods),
            battery_charged_kwh=sum(p.energy.battery_charged for p in view.periods),
            battery_discharged_kwh=sum(
                p.energy.battery_discharged for p in view.periods
            ),
        )

    def __add__(self, other: DailyTotals) -> DailyTotals:
        return DailyTotals(
            import_kwh=self.import_kwh + other.import_kwh,
            import_eur=self.import_eur + other.import_eur,
            export_kwh=self.export_kwh + other.export_kwh,
            export_eur=self.export_eur + other.export_eur,
            grid_cost=self.grid_cost + other.grid_cost,
            grid_only_cost=self.grid_only_cost + other.grid_only_cost,
            battery_cycle_cost=self.battery_cycle_cost + other.battery_cycle_cost,
            savings_vs_grid_only=self.savings_vs_grid_only + other.savings_vs_grid_only,
            solar_kwh=self.solar_kwh + other.solar_kwh,
            battery_charged_kwh=self.battery_charged_kwh + other.battery_charged_kwh,
            battery_discharged_kwh=self.battery_discharged_kwh
            + other.battery_discharged_kwh,
        )


@dataclass
class SavingsBucket:
    """One week/month/year of aggregated savings."""

    label: str
    start_date: str
    end_date: str
    day_count: int
    totals: DailyTotals = field(default_factory=DailyTotals)


def _day_bounds(d: date) -> tuple[date, date]:
    return d, d


def _week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())  # Monday
    return start, start + timedelta(days=6)


def _month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    last_day = calendar.monthrange(d.year, d.month)[1]
    return start, d.replace(day=last_day)


def _year_bounds(d: date) -> tuple[date, date]:
    return date(d.year, 1, 1), date(d.year, 12, 31)


_BOUNDS_FN = {
    "day": _day_bounds,
    "week": _week_bounds,
    "month": _month_bounds,
    "year": _year_bounds,
}


def _bucket_label(period: str, start: date) -> str:
    if period == "day":
        return start.isoformat()
    if period == "week":
        iso_year, iso_week, _ = start.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if period == "month":
        return f"{start.year}-{start.month:02d}"
    return str(start.year)


def _step_back(period: str, bucket_start: date) -> date:
    """Return a reference date inside the previous bucket."""
    if period == "day":
        return bucket_start - timedelta(days=1)
    if period == "week":
        return bucket_start - timedelta(days=7)
    if period == "month":
        return bucket_start - timedelta(days=1)  # last day of the previous month
    return date(
        bucket_start.year - 1, 6, 15
    )  # any date in the prior year works since _year_bounds only reads .year


def build_buckets(
    period: str,
    count: int,
    store,
    today: date | None = None,
    today_view: DailyView | None = None,
) -> list[SavingsBucket]:
    """Build the last `count` buckets of the given period type, oldest first.

    `store` needs only `list_available_dates() -> list[str]` and
    `load_day(day: date) -> DailyView | None` (duck-typed to DailyViewStore).

    `today_view`, if given, is used only for `period="day"` and only for the
    bucket whose single date equals `today` and has no persisted snapshot yet
    (i.e. today, before the 23:55 rollover writes it to the store). It never
    overrides a persisted snapshot.
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"Unknown period type: {period!r}")

    bounds_fn = _BOUNDS_FN[period]
    available_dates = {date.fromisoformat(d) for d in store.list_available_dates()}

    reference_today = today or date.today()
    buckets: list[SavingsBucket] = []
    cursor = reference_today
    for _ in range(count):
        start, end = bounds_fn(cursor)
        days_in_bucket = sorted(d for d in available_dates if start <= d <= end)

        totals = DailyTotals()
        for day in days_in_bucket:
            view = store.load_day(day)
            if view is not None:
                totals = totals + DailyTotals.from_daily_view(view)
        day_count = len(days_in_bucket)

        if (
            period == "day"
            and today_view is not None
            and start == reference_today
            and reference_today not in available_dates
        ):
            totals = totals + DailyTotals.from_daily_view(today_view)
            day_count += 1

        buckets.append(
            SavingsBucket(
                label=_bucket_label(period, start),
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                day_count=day_count,
                totals=totals,
            )
        )
        cursor = _step_back(period, start)

    buckets.reverse()
    return buckets
