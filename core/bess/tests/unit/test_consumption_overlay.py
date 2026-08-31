"""Tests for the consumption forecast overlay (issue #428).

The overlay is a post-processing stage applied to whichever consumption
forecast strategy is configured. The user publishes a sparse list of blocks
describing what differs from their normal usage; BESS composes those onto the
base forecast.
"""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.consumption_overlay import (
    OverlayBlock,
    apply_overlay,
    parse_overlay_blocks,
    period_starts_from,
)
from core.bess.exceptions import ConsumptionOverlayError
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController

TZ = ZoneInfo("Europe/Stockholm")


def _period_starts(first: datetime, count: int) -> list[datetime]:
    """Quarter-hour period start timestamps, as the DP indexes them."""
    return [first + timedelta(minutes=15 * i) for i in range(count)]


# --- Composing blocks onto the base forecast --------------------------------


def test_add_block_spreads_its_energy_across_the_periods_it_covers() -> None:
    """An add block distributes its kWh over the periods its span overlaps."""
    starts = _period_starts(datetime(2026, 8, 27, 0, 0, tzinfo=TZ), 96)
    base = [1.0] * 96

    block = OverlayBlock(
        start=datetime(2026, 8, 27, 22, 0, tzinfo=TZ),
        end=datetime(2026, 8, 27, 23, 0, tzinfo=TZ),
        energy_kwh=4.0,
        mode="add",
    )

    result = apply_overlay(base, starts, [block])

    # 22:00-23:00 is periods 88..91 -- 4 kWh over 4 periods is +1.0 each.
    assert result.values[88:92] == [2.0, 2.0, 2.0, 2.0]
    # Nothing outside the span moved.
    assert result.values[:88] == [1.0] * 88
    assert result.values[92:] == [1.0] * 4
    assert result.clamped_periods == 0


def test_set_block_replaces_the_base_forecast_across_its_span() -> None:
    """A set block overwrites the base rather than adding to it.

    This is the "away for the week" / "force near-zero overnight" case Frank
    asked for: repeated subtractions cannot express it cleanly, because the
    user does not know what the baseline holds.
    """
    starts = _period_starts(datetime(2026, 8, 27, 0, 0, tzinfo=TZ), 96)
    base = [1.0] * 96

    block = OverlayBlock(
        start=datetime(2026, 8, 27, 2, 0, tzinfo=TZ),
        end=datetime(2026, 8, 27, 3, 0, tzinfo=TZ),
        energy_kwh=0.4,
        mode="set",
    )

    result = apply_overlay(base, starts, [block])

    # 02:00-03:00 is periods 8..11 -- 0.4 kWh over 4 periods is 0.1 each,
    # replacing the 1.0 that was there, not adding to it.
    assert result.values[8:12] == [0.1, 0.1, 0.1, 0.1]
    assert result.values[7] == 1.0
    assert result.values[12] == 1.0


def test_over_subtraction_clamps_at_zero_and_is_reported() -> None:
    """Subtracting more than the baseline holds cannot make consumption negative.

    "The EV is not home tonight, subtract the usual session" is the intended
    use, and on a low-baseline day it will occasionally over-subtract.
    Clamping keeps the forecast physical; the count is what lets the caller
    surface it instead of hiding it.
    """
    starts = _period_starts(datetime(2026, 8, 27, 0, 0, tzinfo=TZ), 96)
    base = [1.0] * 96

    block = OverlayBlock(
        start=datetime(2026, 8, 27, 18, 0, tzinfo=TZ),
        end=datetime(2026, 8, 27, 19, 0, tzinfo=TZ),
        energy_kwh=-6.0,
        mode="add",
    )

    result = apply_overlay(base, starts, [block])

    # 18:00-19:00 is periods 72..75, each losing 1.5 kWh from a 1.0 base.
    assert result.values[72:76] == [0.0, 0.0, 0.0, 0.0]
    assert result.clamped_periods == 4


def test_clamped_count_ignores_negatives_the_overlay_did_not_cause() -> None:
    """A positive add block is not blamed for pre-existing negative base periods.

    Issue #734: ``clamped_periods`` counted every negative in the composed
    array, including negatives the base forecast already held. A positive-only
    ``add`` block that touches unrelated periods would then be reported as
    having "subtracted more than the forecast held". Only periods the overlay
    itself drove negative should be attributed to it; the composed forecast is
    still floored to zero either way.
    """
    starts = _period_starts(datetime(2026, 9, 1, 0, 0, tzinfo=TZ), 96)
    base = [1.0] * 96
    for i in range(10, 16):  # the forecast source produced negatives here
        base[i] = -0.05

    block = OverlayBlock(
        start=datetime(2026, 9, 1, 6, 0, tzinfo=TZ),  # periods 24..27, disjoint
        end=datetime(2026, 9, 1, 7, 0, tzinfo=TZ),
        energy_kwh=0.25,
        mode="add",
    )

    result = apply_overlay(base, starts, [block])

    assert result.clamped_periods == 0
    assert result.values[10:16] == [0.0] * 6  # base negatives still floored


def test_set_block_covering_part_of_a_period_only_replaces_that_part() -> None:
    """A set block that starts or ends mid-period must not erase the whole period.

    Users author blocks in wall-clock terms ("away until 07:10"), which will
    not land on quarter-hour boundaries. Replacing the entire period would
    silently discard baseline load the block never claimed to cover.
    """
    starts = _period_starts(datetime(2026, 8, 27, 0, 0, tzinfo=TZ), 96)
    base = [1.0] * 96

    block = OverlayBlock(
        start=datetime(2026, 8, 27, 2, 0, tzinfo=TZ),
        end=datetime(2026, 8, 27, 2, 7, 30, tzinfo=TZ),
        energy_kwh=0.05,
        mode="set",
    )

    result = apply_overlay(base, starts, [block])

    # Period 8 is half covered: half the 1.0 base survives, plus the 0.05.
    assert result.values[8] == 0.55
    assert result.values[9] == 1.0


# --- Parsing the entity attribute -------------------------------------------


def test_parse_reads_blocks_with_defaulted_add_mode() -> None:
    """The declared shape: timestamped spans with a total energy for the span."""
    raw = [
        {
            "start": "2026-08-27T22:00:00+02:00",
            "end": "2026-08-28T06:00:00+02:00",
            "energy_kwh": 40.0,
        },
        {
            "start": "2026-08-27T09:00:00+02:00",
            "end": "2026-08-27T17:00:00+02:00",
            "energy_kwh": 1.0,
            "mode": "set",
        },
    ]

    blocks = parse_overlay_blocks(raw)

    assert len(blocks) == 2
    assert blocks[0].energy_kwh == 40.0
    assert blocks[0].mode == "add"
    assert blocks[0].start == datetime(
        2026, 8, 27, 22, 0, tzinfo=timezone(timedelta(hours=2))
    )
    assert blocks[1].mode == "set"


def test_parse_rejects_a_block_missing_its_end() -> None:
    """A malformed overlay fails loudly rather than degrading to a partial one.

    rules.md forbids silent fallbacks: half-applying a user's declared load is
    worse than telling them their template is broken.
    """
    raw = [{"start": "2026-08-27T22:00:00+02:00", "energy_kwh": 40.0}]

    with pytest.raises(ConsumptionOverlayError, match="end"):
        parse_overlay_blocks(raw)


def test_parse_rejects_an_unknown_mode() -> None:
    """Only add and set exist; a typo must not silently become one of them."""
    raw = [
        {
            "start": "2026-08-27T22:00:00+02:00",
            "end": "2026-08-27T23:00:00+02:00",
            "energy_kwh": 4.0,
            "mode": "replace",
        }
    ]

    with pytest.raises(ConsumptionOverlayError, match="replace"):
        parse_overlay_blocks(raw)


def test_parse_rejects_a_block_that_ends_before_it_starts() -> None:
    raw = [
        {
            "start": "2026-08-27T23:00:00+02:00",
            "end": "2026-08-27T22:00:00+02:00",
            "energy_kwh": 4.0,
        }
    ]

    with pytest.raises(ConsumptionOverlayError, match="after"):
        parse_overlay_blocks(raw)


def test_parse_rejects_a_naive_timestamp() -> None:
    """Without an offset the block's real position on the horizon is a guess."""
    raw = [
        {
            "start": "2026-08-27T22:00:00",
            "end": "2026-08-27T23:00:00",
            "energy_kwh": 4.0,
        }
    ]

    with pytest.raises(ConsumptionOverlayError, match="timezone"):
        parse_overlay_blocks(raw)


# --- Reaching the optimizer -------------------------------------------------
#
# The overlay applies in _gather_optimization_data, after the daily prediction
# cache and after the tomorrow-horizon extension. Applying it earlier -- inside
# _get_consumption_forecast -- would bake it into the cached array (so editing
# the overlay mid-day would do nothing until tomorrow) and would let the
# extension duplicate today's blocks onto tomorrow. These tests pin the seam,
# not just the arithmetic.


@pytest.fixture
def system_with_overlay(
    mock_controller: MockHomeAssistantController,
) -> BatterySystemManager:
    """A system on the 'fixed' strategy: 1.0 kWh/h, a flat 0.25 per period."""
    system = BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
    )
    system.home_settings.consumption_strategy = "fixed"
    system.home_settings.default_hourly = 1.0
    return system


def test_overlay_shapes_the_consumption_the_optimizer_receives(
    system_with_overlay: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A declared EV session reaches full_consumption, not just the parser."""
    system = system_with_overlay
    period_count = time_utils.get_period_count(time_utils.today())

    block = OverlayBlock(
        start=time_utils.period_index_to_timestamp(88),
        end=time_utils.period_index_to_timestamp(92),
        energy_kwh=4.0,
        mode="add",
    )
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: [block]
    )

    result = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result is not None
    _, data = result

    consumption = data["full_consumption"]
    # Base is a flat 0.25/period; the block adds 1.0 to each of 88..91.
    assert consumption[88:92] == pytest.approx([1.25] * 4)
    assert consumption[87] == pytest.approx(0.25)
    assert consumption[92] == pytest.approx(0.25)


def test_no_overlay_entity_leaves_the_forecast_untouched(
    system_with_overlay: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No overlay configured is a legitimate state, not a degraded one.

    This is what keeps the feature free of a cold start: an install that never
    configures an overlay entity keeps exactly the forecast it has today.
    """
    system = system_with_overlay
    period_count = time_utils.get_period_count(time_utils.today())
    monkeypatch.setattr(system.controller, "get_consumption_overlay_blocks", lambda: [])

    result = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result is not None
    _, data = result

    assert data["full_consumption"] == pytest.approx([0.25] * period_count)


def test_a_block_declared_for_tomorrow_lands_on_tomorrow(
    system_with_overlay: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The extension duplicates today's 96 values; the overlay must not follow.

    With a horizon spanning midnight, applying the overlay before the
    extension would replicate a today block onto tomorrow and drop a tomorrow
    block entirely. Both halves are asserted here.
    """
    system = system_with_overlay
    today_periods = time_utils.get_period_count(time_utils.today())
    period_count = today_periods + 8  # horizon runs two hours into tomorrow

    tomorrow_block = OverlayBlock(
        start=time_utils.period_index_to_timestamp(today_periods + 4),
        end=time_utils.period_index_to_timestamp(today_periods + 8),
        energy_kwh=4.0,
        mode="add",
    )
    monkeypatch.setattr(
        system.controller,
        "get_consumption_overlay_blocks",
        lambda: [tomorrow_block],
    )

    result = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result is not None
    _, data = result

    consumption = data["full_consumption"]
    # The block lands on tomorrow's 01:00-02:00 ...
    assert consumption[today_periods + 4 : today_periods + 8] == pytest.approx(
        [1.25] * 4
    )
    # ... and today's corresponding periods are untouched.
    assert consumption[4:8] == pytest.approx([0.25] * 4)


def test_editing_the_overlay_takes_effect_without_waiting_for_tomorrow(
    system_with_overlay: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A date-cached strategy must not bake the overlay into its cached day.

    'ha_statistics' and 'load_power_7d_avg' average whole calendar days, so
    their forecast is cached until the date rolls over. The overlay is not
    that kind of value: the user edits it precisely because today changed.
    Applying it inside _get_consumption_forecast would trap it in that cache.
    """
    system = system_with_overlay
    system.home_settings.consumption_strategy = "ha_statistics"
    monkeypatch.setattr(system, "_get_ha_statistics_forecast", lambda: [0.25] * 96)
    period_count = time_utils.get_period_count(time_utils.today())

    def _block(period: int) -> OverlayBlock:
        return OverlayBlock(
            start=time_utils.period_index_to_timestamp(period),
            end=time_utils.period_index_to_timestamp(period + 4),
            energy_kwh=4.0,
            mode="add",
        )

    blocks = [_block(88)]
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: blocks
    )

    result_first = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result_first is not None
    _, first = result_first
    assert first["full_consumption"][88:92] == pytest.approx([1.25] * 4)

    # The user moves the EV session earlier, same day.
    blocks[:] = [_block(60)]

    result_second = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result_second is not None
    _, second = result_second
    assert second["full_consumption"][60:64] == pytest.approx([1.25] * 4)
    assert second["full_consumption"][88:92] == pytest.approx([0.25] * 4)


# --- Review findings --------------------------------------------------------


def test_period_starts_stay_contiguous_across_the_dst_fall_back_hour() -> None:
    """The overlay's grid must be real time, not wall-clock arithmetic.

    On the fall-back day the local clock repeats 02:00-03:00, so
    `day_start + timedelta(minutes=15*i)` skips a real hour: index 11 lands at
    UTC 00:45 and index 12 at UTC 02:00, pushing everything after it an hour
    late, and today's last four indices land on tomorrow's midnight. A block
    declared for tomorrow would then be counted twice.
    """
    day_start = datetime(2026, 10, 25, 0, 0, tzinfo=TZ)

    starts = period_starts_from(day_start, 100)

    # Compared in UTC: two local timestamps either side of the fold are equal
    # to each other in their own zone (same tzinfo compares naive, ignoring
    # fold), so only the instants tell the truth here.
    instants = [s.astimezone(UTC) for s in starts]
    assert len(set(instants)) == 100
    deltas = {
        (instants[i + 1] - instants[i]).total_seconds()
        for i in range(len(instants) - 1)
    }
    assert deltas == {900.0}
    # The repeated local hour is stepped through, not skipped.
    assert instants[11].strftime("%H:%M") == "00:45"
    assert instants[12].strftime("%H:%M") == "01:00"
    # 100 periods is 25 real hours: the day ends at tomorrow's midnight local.
    assert (instants[-1] - instants[0]).total_seconds() == 99 * 900


def test_apply_overlay_delivers_full_energy_across_the_dst_fall_back_hour() -> None:
    """`apply_overlay` itself must agree with `period_starts_from`'s grid.

    The earlier fix made `period_starts_from` step in real (UTC) time, but
    `apply_overlay` measures each period's overlap with
    `period_start + PERIOD_DURATION` -- wall-clock arithmetic on a
    `zoneinfo`-aware datetime, which silently disagrees with the grid across
    the repeated local hour. A block spanning the fold must still deliver
    exactly its declared energy, not overshoot into one period and vanish
    from the next few.
    """
    day_start = datetime(2026, 10, 25, 0, 0, tzinfo=TZ)
    starts = period_starts_from(day_start, 100)
    base = [0.0] * 100

    # 8 kWh across 01:30-03:30 UTC, straddling the 02:00-03:00 local repeat.
    block = OverlayBlock(
        start=datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        end=datetime(2026, 10, 25, 3, 30, tzinfo=UTC),
        energy_kwh=8.0,
        mode="add",
    )

    result = apply_overlay(base, starts, [block])

    assert result.clamped_periods == 0
    assert sum(result.values) == pytest.approx(8.0)

    # `set` mode must fully replace every period the block spans (2 hours /
    # 8 periods of 8 kWh -> 1 kWh each), including the ones on the far side
    # of the fold -- not leave them at the base value because overlap under
    # the bug measured as zero or negative, and not clamp from a fraction
    # driven past 1.0 by an inflated overlap.
    set_block = OverlayBlock(
        start=block.start, end=block.end, energy_kwh=8.0, mode="set"
    )
    set_result = apply_overlay([9.0] * 100, starts, [set_block])
    assert set_result.clamped_periods == 0
    covered = [
        v
        for start, v in zip(starts, set_result.values, strict=True)
        if block.start <= start.astimezone(UTC) < block.end
    ]
    assert len(covered) == 8
    assert all(v == pytest.approx(1.0) for v in covered)


def test_a_malformed_overlay_is_recorded_as_a_runtime_failure(
    system_with_overlay: BatterySystemManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken template must reach the dashboard, not just the log.

    The error propagates into update_battery_schedule's blanket handler, which
    logs and returns False. Without a recorded failure the schedule silently
    freezes at the last good one and the user has no signal at all.
    """
    system = system_with_overlay
    period_count = time_utils.get_period_count(time_utils.today())

    def _raise() -> list[OverlayBlock]:
        raise ConsumptionOverlayError("overlay block 0: unknown mode 'replace'")

    monkeypatch.setattr(system.controller, "get_consumption_overlay_blocks", _raise)

    with pytest.raises(ConsumptionOverlayError):
        system._gather_optimization_data(
            period=0,
            current_soc=50.0,
            prepare_next_day=False,
            period_count=period_count,
        )

    assert system._runtime_failure_tracker.has_active_failure("CONSUMPTION_OVERLAY")


def test_removing_the_offending_block_clears_the_clamp_warning(
    system_with_overlay: BatterySystemManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the over-subtracting block must dismiss its banner.

    The no-blocks short circuit returned before the dismiss, so the only way
    to clear a clamp warning was to add a different, non-clamping block.
    """
    system = system_with_overlay
    period_count = time_utils.get_period_count(time_utils.today())

    blocks = [
        OverlayBlock(
            start=time_utils.period_index_to_timestamp(72),
            end=time_utils.period_index_to_timestamp(76),
            energy_kwh=-6.0,
            mode="add",
        )
    ]
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: blocks
    )

    system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert system._runtime_failure_tracker.has_active_failure(
        "CONSUMPTION_OVERLAY_CLAMPED"
    )

    blocks.clear()

    system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert not system._runtime_failure_tracker.has_active_failure(
        "CONSUMPTION_OVERLAY_CLAMPED"
    )
