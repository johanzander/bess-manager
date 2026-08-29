"""Unit tests for managed-load subtraction (issue #706)."""

import pytest

from core.bess.exceptions import ManagedLoadsError
from core.bess.managed_loads import subtract_managed_loads


def test_subtracts_one_managed_load_hour_by_hour() -> None:
    base_stats = [
        {"start": 1000, "change": 5.0},
        {"start": 2000, "change": 3.0},
        {"start": 3000, "change": 1.0},
    ]
    ev_stats = [
        {"start": 1000, "change": 2.0},
        {"start": 2000, "change": 0.0},
        {"start": 3000, "change": 0.5},
    ]

    adjusted, clamped = subtract_managed_loads(base_stats, [ev_stats])

    assert clamped == 0
    assert [e["change"] for e in adjusted] == pytest.approx([3.0, 3.0, 0.5])
    # start values are preserved unchanged
    assert [e["start"] for e in adjusted] == [1000, 2000, 3000]


def test_sums_multiple_managed_loads_for_the_same_hour() -> None:
    base_stats = [{"start": 1000, "change": 10.0}]
    car1 = [{"start": 1000, "change": 3.0}]
    car2 = [{"start": 1000, "change": 4.0}]

    adjusted, clamped = subtract_managed_loads(base_stats, [car1, car2])

    assert clamped == 0
    assert adjusted[0]["change"] == pytest.approx(3.0)  # 10 - 3 - 4


def test_clamps_negative_residual_to_zero_and_counts_it() -> None:
    # A managed load reporting more than the total load sensor for that hour
    # -- e.g. a sensor/entity mismatch -- must not go negative.
    base_stats = [
        {"start": 1000, "change": 1.0},
        {"start": 2000, "change": 5.0},
    ]
    ev_stats = [
        {"start": 1000, "change": 4.0},  # exceeds base -> clamp
        {"start": 2000, "change": 2.0},  # within base -> no clamp
    ]

    adjusted, clamped = subtract_managed_loads(base_stats, [ev_stats])

    assert clamped == 1
    assert [e["change"] for e in adjusted] == pytest.approx([0.0, 3.0])


def test_hours_with_no_matching_managed_load_entry_are_unaffected() -> None:
    base_stats = [
        {"start": 1000, "change": 5.0},
        {"start": 2000, "change": 5.0},
    ]
    # Managed load only reports for the first hour.
    ev_stats = [{"start": 1000, "change": 1.0}]

    adjusted, clamped = subtract_managed_loads(base_stats, [ev_stats])

    assert clamped == 0
    assert [e["change"] for e in adjusted] == pytest.approx([4.0, 5.0])


def test_base_entries_with_no_change_pass_through_unchanged() -> None:
    base_stats = [{"start": 1000, "change": None}]
    ev_stats = [{"start": 1000, "change": 2.0}]

    adjusted, clamped = subtract_managed_loads(base_stats, [ev_stats])

    assert clamped == 0
    assert adjusted == [{"start": 1000, "change": None}]


def test_malformed_managed_load_entry_raises_rather_than_silently_understating() -> (
    None
):
    base_stats = [{"start": 1000, "change": 5.0}]
    malformed = [{"start": 1000}]  # missing 'change'

    with pytest.raises(ManagedLoadsError):
        subtract_managed_loads(base_stats, [malformed])


def test_no_managed_loads_returns_base_stats_unchanged() -> None:
    base_stats = [{"start": 1000, "change": 5.0}]

    adjusted, clamped = subtract_managed_loads(base_stats, [])

    assert clamped == 0
    assert adjusted == base_stats
