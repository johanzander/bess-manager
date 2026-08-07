import pytest

from core.bess.tie_detection import (
    TIE_NOISE_FACTOR,
    Window,
    detect_tie_windows,
    epsilon_for_period,
)

# dV/dSoE = 1.0 currency/kWh at every period, so epsilon is a flat
# TIE_NOISE_FACTOR * 0.05 -- comfortably between the "clear margin" and
# "near-tie" margins used below, whatever TIE_NOISE_FACTOR is set to.
SLOPE = 1.0
STEP = 0.05
CLEAR = 10.0
TIED = 1e-9


def _slopes(n: int) -> list[float]:
    return [SLOPE] * n


def test_no_ties_returns_empty_list():
    assert detect_tie_windows([CLEAR] * 10, _slopes(10), soe_step_kwh=STEP) == []


def test_isolated_tie_produces_single_padded_window():
    margins = [CLEAR] * 10
    margins[5] = TIED
    windows = detect_tie_windows(margins, _slopes(10), soe_step_kwh=STEP, pad=2)
    assert windows == [
        Window(start=3, end=8)
    ]  # 5-2 .. 5+2+1, clamped to bounds by construction here


def test_two_ties_close_together_merge_into_one_window():
    margins = [CLEAR] * 10
    margins[4] = TIED
    margins[5] = TIED
    windows = detect_tie_windows(margins, _slopes(10), soe_step_kwh=STEP, pad=2)
    assert len(windows) == 1
    assert windows[0].start <= 2 and windows[0].end >= 8


def test_two_ties_far_apart_stay_separate():
    margins = [CLEAR] * 20
    margins[2] = TIED
    margins[17] = TIED
    windows = detect_tie_windows(margins, _slopes(20), soe_step_kwh=STEP, pad=2)
    assert len(windows) == 2


def test_windows_clamped_to_horizon_bounds():
    margins = [CLEAR] * 5
    margins[0] = TIED
    margins[4] = TIED
    windows = detect_tie_windows(margins, _slopes(5), soe_step_kwh=STEP, pad=2)
    for w in windows:
        assert 0 <= w.start < w.end <= 5


def test_epsilon_scales_with_the_local_marginal_value_of_energy():
    """Epsilon is the value error SOE_STEP_KWH grid-snapping can inject, so
    it must scale with dV/dSoE -- a period where stored energy has no
    marginal value has nothing a flipped decision could cost (#450)."""
    assert epsilon_for_period(2.0, STEP) == pytest.approx(
        2 * epsilon_for_period(1.0, STEP)
    )
    assert epsilon_for_period(-1.0, STEP) == epsilon_for_period(1.0, STEP)
    assert epsilon_for_period(0.0, STEP) == 0.0
    assert epsilon_for_period(1.0, STEP) == pytest.approx(TIE_NOISE_FACTOR * STEP)


def test_zero_marginal_value_periods_are_never_flagged():
    """A flat value function means grid-snapping cannot mis-rank anything
    there, so even an exactly-zero margin is not an ambiguity worth an
    exact re-solve.

    This pins a KNOWN BLIND SPOT, not just an edge case: zero epsilon makes
    the strict `<` unfirable, so ~12.4% of periods across the fixture suite
    are excluded from tie detection by construction. If a #450-class report
    ever traces to a period with a flat local value function, this test is
    the assumption to revisit -- detect_tie_windows logs the per-solve count
    at debug level so that is at least observable in a bundle."""
    assert detect_tie_windows([0.0] * 6, [0.0] * 6, soe_step_kwh=STEP) == []


def test_mismatched_input_lengths_raise():
    with pytest.raises(ValueError, match="must be recorded per period"):
        detect_tie_windows([CLEAR] * 4, _slopes(3), soe_step_kwh=STEP)
