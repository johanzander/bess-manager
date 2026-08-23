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

import math
import statistics
from dataclasses import dataclass

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


@dataclass(frozen=True)
class TerminalValueCurve:
    """Concave terminal valuation: `head_rate` up to `knee_kwh`, `tail_rate` above.

    The predecessor of this class was a single scalar applied to every kWh, and
    that shape -- not its calibration -- was the defect (#602). Because the row
    was one unbounded slope, the DP compared that slope against the best
    in-horizon export value and got an all-or-nothing answer: above
    ``max_sell * efficiency_discharge`` every kWh is worth holding, below it
    none are. Measured on #595's bundle, midnight SOE was flat at the floor
    (2.02 kWh) for every terminal value from 0.00 to 0.65, then swept the whole
    battery between 0.69 and 0.79 -- a 1.3e-5 change in the scalar moved
    midnight by 2.6 kWh. No scalar produced a moderate carry, so the parameter
    was not tunable in either direction.

    Concavity is what makes a moderate carry expressible at all: the first
    `knee_kwh` are priced above the export alternative (so the DP holds them)
    and everything above is priced below it (so the DP sells it). The decision
    then turns on `knee_kwh` -- a *quantity*, read from a load profile -- rather
    than on a price point-estimate. That matters because the point estimate is
    inherently high-variance: on #595's inputs the correct carry ranges from
    2.02 kWh ("tomorrow 20% cheaper") to 18.39 kWh ("20% pricier, no solar"),
    while the overnight load that sets the knee barely moves.
    """

    head_rate: float
    knee_kwh: float
    tail_rate: float = 0.0

    @classmethod
    def flat(cls, rate_per_kwh: float) -> "TerminalValueCurve":
        """The pre-#602 unbounded linear row: one rate, every kWh, no knee.

        Kept as an explicit constructor rather than a default so that the call
        sites which genuinely want the linear shape -- the tie-machinery rigs,
        which need a value gradient they can reason about analytically, and the
        #244/#246/#422 cap regressions, whose subject is the rate formula and
        not the quantity bound -- say so in one word instead of silently
        inheriting it.
        """
        return cls(head_rate=rate_per_kwh, knee_kwh=math.inf, tail_rate=0.0)

    def value(self, usable_kwh: float) -> float:
        """Total terminal value of `usable_kwh` above the floor."""
        usable = max(0.0, usable_kwh)
        head = min(usable, self.knee_kwh)
        return head * self.head_rate + (usable - head) * self.tail_rate


def knee_kwh_from_forecast(
    consumption_forecast: list[float],
    solar_forecast: list[float],
    battery_settings: BatterySettings,
) -> float:
    """Stored energy that will be consumed before PV takes over, in kWh.

    This is the quantity the concave terminal row bends at: run the next day's
    net load (consumption minus solar) forward from the terminal boundary and
    accumulate until solar first covers load. Energy up to that point genuinely
    displaces a purchase; energy beyond it is refilled by the PV that just
    arrived, so it is worth only what exporting it earns.

    Both arrays must start at the terminal boundary and share one resolution --
    the caller aligns them, because only the caller knows which day the horizon
    ends on. Divided by `efficiency_discharge` to convert covered *load* into
    the *stored* energy needed to cover it, which is what `V[horizon]` indexes.

    When solar never covers load -- every winter, and any overcast day -- the
    accumulation runs to the end of the array and the knee exceeds anything the
    battery can hold. The curve is then straight over its whole reachable
    range, i.e. this reduces to the pre-#602 linear row. That is deliberate and
    it is also correct: with no PV to refill it, every stored kWh really will be
    consumed and really does avoid a purchase, so there is no quantity at which
    the marginal value should drop. Measured on the January fixtures, the plans
    are unchanged (`historical_2025_01_05/12/13_*`). The consequence is that
    #602 is a growing-season fix, and the winter carry #381 asks for needs a
    differently-derived knee -- bounded by the next cheap charging window rather
    than by sunrise -- which is not in scope here and has no oracle behind it yet.
    """
    net = 0.0
    for consumption, solar in zip(consumption_forecast, solar_forecast, strict=False):
        if solar >= consumption:
            break
        net += consumption - solar
    return net / battery_settings.efficiency_discharge


def calculate_terminal_curve(
    buy_prices: list[float],
    sell_prices: list[float],
    consumption_forecast: list[float],
    solar_forecast: list[float],
    battery_settings: BatterySettings,
) -> TerminalValueCurve:
    """The production terminal row (#602).

    Two regimes, separated by whether the next day's PV ever covers its load.

    **PV crossover exists** -- the concave row this issue is about: the
    buy-median rate up to `knee_kwh`, nothing above. `cycle_cost_per_kwh` is not
    subtracted and the arbitrage-consistency cap is not applied, because the
    knee has taken over both their jobs. On wear: it is charged on charging only
    (`_compute_reward` bills STORE and the positive IDLE delta; `reward_discharge`
    has no wear term), so a kWh at the boundary has already paid its full
    round-trip wear and the old deduction billed it twice. On the cap: it exists
    to stop the DP holding charge for a bonus it will not collect, and a
    *quantity* bound does that better than a *rate* haircut -- it cannot hold
    more than the household will actually consume. The cap is also arithmetically
    incompatible with the knee: when it binds it sets the rate to exactly
    ``max_sell * efficiency_discharge``, which is precisely the hold-versus-export
    tie point, so the head segment would land on the tie instead of clearing it.

    **No PV crossover** -- every winter day, and any overcast one: the previous
    capped scalar, unchanged, via `calculate_terminal_value_per_kwh`. Without PV
    to refill the battery there is no quantity at which the marginal stored kWh
    stops being worth the buy price, so the knee runs past anything the battery
    can hold and the row is straight over its whole reachable range. That is not
    merely the old shape -- it is the old shape at an *uncapped* rate, which is
    #126/#244's hoarding bug exactly. Measured on #246's Belgian regression
    scenario (buy median 0.30, best export 0.16, no solar): the concave row
    exports 0.00 kWh at the evening peak and ends at 6.16 kWh, against the
    capped scalar's 0.70 kWh and 1.58 kWh. So the cap is still load-bearing
    wherever the knee cannot bind, and this is a domain distinction rather than
    a fallback -- a day with sun and a day without are different problems, and
    #602's evidence covers only the first.

    The winter carry #381 asks for needs a knee derived from the next cheap
    charging window rather than from sunrise. That is not in scope here and has
    no oracle behind it yet.

    `buy_prices` is the remaining optimization horizon, matching the median the
    previous formula took. Deliberately not the terminal day's overnight window,
    though that is where the energy is consumed: carried energy competes for the
    whole of the next day including its evening peak, and the narrower window
    measured worse against the #595 oracle (2.01 kWh against 4.37, where the
    horizon median gives 5.41).
    """
    if not _pv_covers_load(consumption_forecast, solar_forecast):
        return TerminalValueCurve.flat(
            calculate_terminal_value_per_kwh(buy_prices, sell_prices, battery_settings)
        )
    return TerminalValueCurve(
        head_rate=statistics.median(buy_prices) * battery_settings.efficiency_discharge,
        knee_kwh=knee_kwh_from_forecast(
            consumption_forecast, solar_forecast, battery_settings
        ),
        tail_rate=0.0,
    )


def _pv_covers_load(
    consumption_forecast: list[float], solar_forecast: list[float]
) -> bool:
    """Whether the next day's solar ever meets its own load."""
    return any(
        solar >= consumption
        for consumption, solar in zip(
            consumption_forecast, solar_forecast, strict=False
        )
    )
