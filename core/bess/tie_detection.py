"""Pure-function detection of near-tied DP decisions (#450).

The grid DP snaps every continuation-value lookup to the nearest
SOE_STEP_KWH grid point, so the value it attributes to a candidate action
carries an error of up to `SOE_STEP_KWH / 2 * |dV/dSoE|` -- half a grid
step times the local marginal value of stored energy. Two candidates snap
independently, so the *differential* error that could reorder them is up
to a full `SOE_STEP_KWH * |dV/dSoE|`.

That product is exactly this module's epsilon: a period is near-tied when
the gap between its chosen action's value and the best behaviourally
distinct alternative's is smaller than the value noise grid-snapping can
inject. It is derived from the mechanical source of #450's bug rather
than being a hand-picked SEK figure, and it self-scales -- a period where
stored energy has little marginal value has correspondingly little to
gain or lose from a flipped decision.

The earlier formulation used the period's buy/sell price *spread* as a
stand-in for the shadow price. That stand-in was both too large (a spread
is a round-trip arbitrage margin, not a marginal value) and unrelated to
the actual lookup error, and flagged 50-100% of periods on every fixture.
The DP already computes dV/dSoE, so the stand-in is unnecessary.
"""

from dataclasses import dataclass

# Fraction of the worst-case grid-snap noise below which a margin counts as
# a tie. 1.0 would be the worst case itself -- two independent half-step
# snaps landing at opposite extremes -- which is far above the typical
# error and, measured across the fixture suite, flags 11% of periods even
# after candidate deduplication. 0.1 flags 1.0% while still catching #450's
# own reproduction case with roughly 2x headroom (its critical period's
# margin is 0.053 of the worst-case noise). Measured suite-wide flag rates:
# k=0.05 -> 0.6%, k=0.1 -> 1.0%, k=0.2 -> 2.2%, k=0.5 -> 6.0%, k=1.0 -> 10.7%.
TIE_NOISE_FACTOR = 0.1


@dataclass(frozen=True)
class Window:
    start: int
    end: int


def _epsilon_for_period(value_slope: float, soe_step_kwh: float) -> float:
    """Value noise (currency) that SOE_STEP_KWH grid-snapping can inject
    into a single period's action comparison, given the local marginal
    value of stored energy `value_slope` (dV/dSoE, currency per kWh)."""
    return TIE_NOISE_FACTOR * soe_step_kwh * abs(value_slope)


def detect_tie_windows(
    tie_margins: list[float],
    value_slopes: list[float],
    soe_step_kwh: float,
    pad: int = 2,
) -> list[Window]:
    horizon = len(tie_margins)
    if len(value_slopes) != horizon:
        raise ValueError(
            f"value_slopes has {len(value_slopes)} entries but tie_margins has "
            f"{horizon} -- they must be recorded per period in the same pass"
        )
    flagged = [
        t
        for t in range(horizon)
        if tie_margins[t] < _epsilon_for_period(value_slopes[t], soe_step_kwh)
    ]
    if not flagged:
        return []

    raw_windows: list[Window] = []
    for t in flagged:
        start = max(0, t - pad)
        end = min(horizon, t + pad + 1)
        raw_windows.append(Window(start=start, end=end))

    raw_windows.sort(key=lambda w: w.start)
    merged: list[Window] = [raw_windows[0]]
    for w in raw_windows[1:]:
        last = merged[-1]
        if w.start <= last.end:
            merged[-1] = Window(start=last.start, end=max(last.end, w.end))
        else:
            merged.append(w)
    return merged
