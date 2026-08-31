"""Consumption forecast overlay — user-declared changes to expected load.

Issue #428. BESS optimizes against a consumption forecast; it does not model
loads. The overlay is how a user tells BESS about the loads their forecast
cannot know: an EV session tonight, a pool pump they are skipping, a week
away from home.

It is a post-processing stage on whichever consumption strategy is
configured, not a strategy of its own — so it composes with ``ha_statistics``,
``load_power_7d_avg``, ``sensor`` and ``fixed`` identically, and an install with
no overlay entity keeps exactly the forecast it has today.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .exceptions import ConsumptionOverlayError
from .time_utils import INTERVAL_MINUTES

PERIOD_DURATION = timedelta(minutes=INTERVAL_MINUTES)

VALID_MODES = ("add", "set")


@dataclass(frozen=True)
class OverlayBlock:
    """One declared change to expected consumption over a time span.

    Attributes:
        start: When the block begins (timezone-aware).
        end: When the block ends (timezone-aware, after ``start``).
        energy_kwh: Total energy across the whole span, apportioned to the
            periods the span overlaps. Not a per-period value.
        mode: ``"add"`` to add to the base forecast (a load that will happen
            on top of normal usage, or negative for one that will not), or
            ``"set"`` to replace the base forecast across the span.

    """

    start: datetime
    end: datetime
    energy_kwh: float
    mode: str


@dataclass
class OverlayResult:
    """The composed forecast, plus what had to be corrected to produce it."""

    values: list[float]
    clamped_periods: int


def parse_overlay_blocks(raw: object) -> list[OverlayBlock]:
    """Parse the overlay entity's ``blocks`` attribute into blocks.

    Args:
        raw: The attribute value as Home Assistant returned it.

    Returns:
        The declared blocks, in the order given.

    Raises:
        ConsumptionOverlayError: If the value is not a list of well-formed
            blocks. Every failure is explicit — nothing is skipped or
            defaulted past a missing field.

    """
    if not isinstance(raw, list):
        raise ConsumptionOverlayError(
            f"overlay blocks must be a list, got {type(raw).__name__}"
        )

    blocks = []
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConsumptionOverlayError(
                f"overlay block {position} must be a mapping, "
                f"got {type(entry).__name__}"
            )

        start = _parse_timestamp(entry, "start", position)
        end = _parse_timestamp(entry, "end", position)
        if end <= start:
            raise ConsumptionOverlayError(
                f"overlay block {position}: end ({end.isoformat()}) must be "
                f"after start ({start.isoformat()})"
            )

        if "energy_kwh" not in entry:
            raise ConsumptionOverlayError(
                f"overlay block {position} is missing 'energy_kwh'"
            )
        try:
            energy_kwh = float(entry["energy_kwh"])
        except (TypeError, ValueError) as e:
            raise ConsumptionOverlayError(
                f"overlay block {position}: 'energy_kwh' is not a number "
                f"({entry['energy_kwh']!r})"
            ) from e

        mode = entry.get("mode", "add")
        if mode not in VALID_MODES:
            raise ConsumptionOverlayError(
                f"overlay block {position}: unknown mode {mode!r}, "
                f"expected one of {VALID_MODES}"
            )

        blocks.append(
            OverlayBlock(start=start, end=end, energy_kwh=energy_kwh, mode=mode)
        )

    return blocks


def _parse_timestamp(entry: dict, field: str, position: int) -> datetime:
    """Parse one ISO-8601 field, requiring an explicit UTC offset."""
    if field not in entry:
        raise ConsumptionOverlayError(f"overlay block {position} is missing '{field}'")

    try:
        parsed = datetime.fromisoformat(str(entry[field]))
    except ValueError as e:
        raise ConsumptionOverlayError(
            f"overlay block {position}: '{field}' is not an ISO-8601 timestamp "
            f"({entry[field]!r})"
        ) from e

    if parsed.tzinfo is None:
        raise ConsumptionOverlayError(
            f"overlay block {position}: '{field}' has no timezone offset "
            f"({entry[field]!r}) — the block's position on the horizon would "
            f"be a guess"
        )

    return parsed


def period_starts_from(day_start: datetime, count: int) -> list[datetime]:
    """Period start timestamps stepping in *real* time from ``day_start``.

    The DP's grid is a contiguous run of quarter-hours, which is why a
    fall-back day has 100 periods rather than 96. Wall-clock arithmetic
    (``day_start + timedelta(minutes=15 * i)``) does not produce that grid: on
    the fall-back day it steps straight over the repeated local hour, so every
    period after the fold is an hour late and the day's last four indices
    collide with the next day's first four. Stepping in UTC and converting
    back gives the grid the period count already implies.

    Args:
        day_start: Midnight of the first day in the horizon, timezone-aware.
        count: Number of periods to produce.

    Returns:
        ``count`` timestamps, 15 real minutes apart, in ``day_start``'s zone.

    """
    tz = day_start.tzinfo
    anchor = day_start.astimezone(UTC)
    return [(anchor + PERIOD_DURATION * i).astimezone(tz) for i in range(count)]


def apply_overlay(
    base: list[float],
    period_starts: list[datetime],
    blocks: list[OverlayBlock],
) -> OverlayResult:
    """Compose overlay blocks onto a base consumption forecast.

    Args:
        base: Base forecast, kWh per period.
        period_starts: Start timestamp of each period in ``base``, same
            length and order — build them with ``period_starts_from``, which
            is what makes the DST fall-back day come out right.
        blocks: Declared changes. Blocks outside the horizon contribute
            nothing.

    Returns:
        The composed forecast and the number of periods whose value had to be
        clamped to zero.

    """
    values = list(base)

    for block in blocks:
        span = (block.end - block.start).total_seconds()
        overlaps = [
            _overlap_seconds(start, block) for start in period_starts[: len(values)]
        ]
        covered = sum(overlaps)
        if covered <= 0:
            continue

        for index, overlap in enumerate(overlaps):
            if overlap <= 0:
                continue
            share = block.energy_kwh * (overlap / span)
            if block.mode == "set":
                # Replace only the covered fraction of the period, so a block
                # that starts mid-period does not erase the rest of it.
                fraction = overlap / PERIOD_DURATION.total_seconds()
                values[index] = values[index] * (1 - fraction) + share
            else:
                values[index] += share

    # Attribute a clamp to the overlay only where the overlay itself drove the
    # period below zero. A negative the base forecast already held (and the
    # overlay left alone, or nudged upward) is not the overlay over-subtracting
    # — counting it produced a false "subtracted more than the forecast held"
    # warning for positive-only blocks (issue #734).
    clamped_periods = sum(
        1 for index, value in enumerate(values) if value < 0.0 and value < base[index]
    )
    values = [max(0.0, value) for value in values]

    return OverlayResult(values=values, clamped_periods=clamped_periods)


def _overlap_seconds(period_start: datetime, block: OverlayBlock) -> float:
    """Seconds of ``block`` falling inside the period starting at ``period_start``.

    ``period_end`` must be derived the same way ``period_starts_from`` builds
    the grid -- by stepping in real (UTC) time, not by adding a timedelta to a
    local-zone datetime. Naive ``period_start + PERIOD_DURATION`` disagrees
    with the grid across a DST fall-back: on the repeated local hour it can
    land ahead of the *next* grid point (inflating overlap) or behind the
    period's own start (silently zeroing it out via the ``max(0.0, ...)``
    floor below).
    """
    period_end = (period_start.astimezone(UTC) + PERIOD_DURATION).astimezone(
        period_start.tzinfo
    )
    latest_start = max(period_start, block.start)
    earliest_end = min(period_end, block.end)
    return max(0.0, (earliest_end - latest_start).total_seconds())
