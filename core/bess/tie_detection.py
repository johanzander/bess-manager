"""Pure-function detection of near-tied DP decisions (#450).

The grid DP's SOE_STEP_KWH grid-snapping introduces noise into its
continuation-value lookups roughly on the order of
SOE_STEP_KWH/2 * (a representative shadow price). Rather than tune an
arbitrary SEK threshold, epsilon is derived from that same grid step,
scaled by the period's own price spread (buy - sell) as the closest
available stand-in for the local shadow price magnitude -- keeping the
threshold principled and self-scaling across fixtures with very
different price levels.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    start: int
    end: int


def _epsilon_for_period(
    buy_price: float, sell_price: float, soe_step_kwh: float
) -> float:
    price_spread = max(abs(buy_price - sell_price), 0.01)
    return soe_step_kwh * price_spread


def detect_tie_windows(
    tie_margins: list[float],
    buy_price: list[float],
    sell_price: list[float],
    soe_step_kwh: float,
    pad: int = 2,
) -> list[Window]:
    horizon = len(tie_margins)
    flagged = [
        t
        for t in range(horizon)
        if tie_margins[t]
        < _epsilon_for_period(buy_price[t], sell_price[t], soe_step_kwh)
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
