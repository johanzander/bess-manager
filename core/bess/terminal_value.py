"""End-of-horizon terminal value: what a kWh left in the battery is worth.

The DP's horizon ends at a wall-clock boundary, not at a natural end of the
world -- energy still in the battery there has real value tomorrow. This module
owns the single estimate of that value, so production, the forecast-robustness
harness and the pinned scenario corpus all price the boundary identically.

Previously this formula existed twice: once in
``BatterySystemManager._calculate_terminal_value`` and once hand-cloned in
``core/bess/simulation/verification.py``. A third copy was about to appear in
the test helper when the pinned fixtures were retrofitted off
``terminal_value_per_kwh = 0.0``. Two copies of an economic formula is two
objectives; the harness would then judge plans by a different one than
production optimizes against.
"""

import statistics

from core.bess.settings import BatterySettings


def calculate_terminal_value_per_kwh(
    buy_prices: list[float],
    sell_prices: list[float],
    battery_settings: BatterySettings,
) -> float:
    """Value per kWh of usable energy remaining at the horizon boundary.

    Estimate value from the median buy price (over whatever horizon window the
    caller passed in) adjusted for efficiency and cycle cost ("avoid a future
    purchase"), capped at the best achievable in-horizon export value
    ("arbitrage-consistency cap"). This applies at either horizon boundary,
    midnight-today or midnight-tomorrow: the caller already truncates
    buy_prices/sell_prices to the current optimization window, so the
    median/cap formula reflects genuine future price uncertainty beyond that
    window regardless of where it ends (#345).

    ``sell_prices`` is expected to be scoped by the caller to the terminal
    boundary's own calendar day, not the full remaining horizon (#422): on a
    48h-extended horizon, using the full window lets an already-committed
    near-term peak (e.g. today's still-upcoming best sell slot) inflate the cap
    for a later, economically unrelated day's terminal energy, making the DP
    hold charge through that day's own (lower) export opportunities instead of
    exporting into them. ``buy_prices`` is unaffected -- it feeds a median,
    which is already resistant to a single-period outlier.

    The cap is required because cycle cost is only ever charged on charging,
    never on discharge (see ``_compute_reward``): an uncapped buy-median
    terminal value can exceed the best real, known export price already visible
    inside today's horizon, which makes the DP hold charge to chase a fictitious
    future bonus instead of exporting now (#126, #244). The cap is
    self-calibrating from data the DP already has, so it collapses on
    wide-spread contracts (e.g. Belgian ENTSO-e/Belpex) without needing a
    market-specific threshold, and stays inert on ordinary/Nordic-shaped markets
    where the best in-horizon peak is already above the buy-median estimate
    (#246, supersedes #245).

    The cap is skipped when the export tariff is fixed. It bounds terminal value
    by an export opportunity the DP would forgo by holding charge, but on a flat
    sell curve ``max(sell_prices)`` is not an opportunity to forgo -- it is the
    price available in every period, including the current one, which each
    period's reward already prices in. Applying it there double-counts the
    immediate export alternative and makes storing surplus solar for
    post-horizon use arithmetically impossible for *any* future price, since the
    cap forces
    ``terminal <= sell * efficiency_discharge < sell < sell / efficiency_charge``
    -- the round-trip breakeven that storing has to clear (#359).

    Args:
        buy_prices: Buy price array from the optimization period onwards
        sell_prices: Sell price array, scoped to the terminal boundary's own day
        battery_settings: Supplies efficiency_discharge and cycle_cost_per_kwh

    Returns:
        Terminal value per kWh (floored at 0.0)

    Raises:
        statistics.StatisticsError / ValueError: if either price array is empty
            -- see `terminal_value_breakdown` on why this is not defaulted.
    """
    return float(
        terminal_value_breakdown(buy_prices, sell_prices, battery_settings)[
            "terminal_value"
        ]
    )


def terminal_value_breakdown(
    buy_prices: list[float],
    sell_prices: list[float],
    battery_settings: BatterySettings,
) -> dict[str, float | bool]:
    """The same estimate, with the intermediate terms that produced it.

    Callers that log or diagnose the terminal value use this rather than
    recomputing `buy_based`/`sell_cap` alongside the result -- a recomputed log
    line is free to drift from the value actually handed to the DP, which is
    precisely the failure this module exists to prevent.

    Returns a plain dict (no new type): `terminal_value`, `buy_based`,
    `sell_cap`, `cap_applied`, `median_buy`, `max_sell`.

    Empty prices raise (from `statistics.median`/`max`) rather than yielding a
    zero terminal value. There is no meaningful valuation of a boundary with no
    price data behind it, and a silent 0.0 here would read downstream as "this
    energy is worthless" -- a real answer -- instead of "we could not compute
    one". `BatterySystemManager._calculate_terminal_value` short-circuits the
    empty case before calling, because a horizon with no remaining periods is
    an expected state there; the forecast-robustness harness has no such state,
    and must not inherit the exemption.
    """
    median_price = statistics.median(buy_prices)
    max_sell_price = max(sell_prices)
    buy_based = max(
        0.0,
        median_price * battery_settings.efficiency_discharge
        - battery_settings.cycle_cost_per_kwh,
    )
    sell_cap = max(
        0.0,
        max_sell_price * battery_settings.efficiency_discharge
        - battery_settings.cycle_cost_per_kwh,
    )
    export_prices_vary = max_sell_price > min(sell_prices)
    return {
        "terminal_value": min(buy_based, sell_cap) if export_prices_vary else buy_based,
        "buy_based": buy_based,
        "sell_cap": sell_cap,
        "cap_applied": export_prices_vary,
        "median_buy": median_price,
        "max_sell": max_sell_price,
    }
