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


def pv_covers_load(consumption: float, solar: float) -> bool:
    """Whether this period is a genuine PV crossover: real PV meeting a real load.

    Every knee derivation in this module scans a net-load series and stops at
    the first period where "PV has taken over the house". The bare test for
    that -- ``solar >= consumption`` -- also fires on ``0.0 >= 0.0``, i.e. on a
    period with *no forecast load at all*. Those are not rare: an empty HA
    Recorder statistics bucket and a managed-load subtraction clamped at zero
    (`managed_loads.subtract_managed_loads`) both leave a forecast hour at
    exactly 0.0 kWh, and overnight -- where solar is also 0.0 -- is where they
    are most likely. Read as a crossover, one such period at the terminal
    boundary collapses the whole terminal row (#715).

    A no-load period is missing data, not a takeover: it must not end the scan
    (this predicate) and it must not contribute net load either (the scanners
    ``continue`` past ``consumption <= 0`` before accumulating). Requiring
    ``consumption > 0`` here also implies ``solar > 0`` at a real crossover,
    since ``solar >= consumption > 0``.
    """
    return consumption > 0 and solar >= consumption


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
    # `strict=False` is deliberate and must stay: the two arrays legitimately
    # differ in length. `_get_consumption_forecast` hardcodes 96 on every
    # strategy branch, while `_fetch_tomorrow_solar_forecast`'s no-sensor
    # fallback sizes itself to `get_period_count(tomorrow)` -- 92 on DST spring,
    # 100 on DST fall. `strict=True` would raise there, i.e. crash the optimizer
    # twice a year for every install without a solar sensor, which is worse than
    # the truncation it would replace: that path yields an all-zero solar array,
    # so the day has no PV crossover and takes the capped regime at either
    # length. The real defect is the 96-vs-period-count mismatch upstream, not
    # the zip.
    net = 0.0
    for consumption, solar in zip(consumption_forecast, solar_forecast, strict=False):
        if consumption <= 0:
            # No forecast load: a data gap, not a period. It is neither the PV
            # crossover nor real net load, so skip it entirely -- accumulating
            # `consumption - solar` here would subtract any stray solar and
            # understate the knee (#715).
            continue
        if pv_covers_load(consumption, solar):
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

    Two regimes, separated by whether the knee can bind at all -- that is, by
    whether the household's pre-dawn need is smaller than the battery.

    **Knee binds** -- the concave row this issue is about. The head segment is
    priced at the avoided purchase, `median(buy) * efficiency_discharge`: what
    the household does not have to buy tomorrow because it carried the energy.

    A known limitation, deliberately left: that rate still decides *whether* to
    carry, where the knee decides *how much*. Measured on #595's fixture the
    carry swings the full knee between head rates of 0.70 and 0.75, so a ~12%
    move in the rate is still binary. Flooring the rate at the export
    alternative (`max(median(buy), max(sell)) * efficiency_discharge`) removes
    that threshold and was tried -- but it prices terminal energy above what the
    DP can buy at inside the horizon, which turns the terminal row into an
    arbitrage target: on `synthetic_seasonal_spring` (median buy 1.05, best sell
    1.90) the floored rate of 1.805 made the DP charge 40.6 kWh to bank 23.6
    against a credit of 42.64 SEK. That is #126/#244's fictitious bonus, at
    scale. Valuing carried energy by an avoided purchase keeps the estimate tied
    to a cost the household would really pay; valuing it by a speculative future
    export price does not.

    `cycle_cost_per_kwh` is not subtracted, and the arbitrage-consistency cap is
    not applied. On wear: it is charged on charging only (`_compute_reward`
    bills STORE and the positive IDLE delta; `reward_discharge` has no wear
    term), so a kWh at the boundary has already paid its full round-trip wear
    and the old deduction billed it twice. This is load-bearing, not tidying --
    `head_rate - cycle_cost` is 0.4098 on #595's fixture, far below the ~0.72
    the carry needs, so keeping the deduction leaves the knee inert. On the cap:
    when it binds it sets the rate to `max_sell * efficiency_discharge -
    cycle_cost`, *strictly below* the crossover, which guaranteed the DP
    preferred exporting everything over holding any of it. That is the
    mechanism behind the all-or-nothing midnight SOE, and it is why the cap
    cannot coexist with a quantity bound. Its premise -- that terminal energy
    can only be monetised by export -- was always wrong: terminal energy is
    monetised by self-consumption, which is exactly the value #381 reports
    missing (#126, #244, #246, #359, #422).

    **Knee cannot bind** -- when the pre-dawn need exceeds what the battery can
    hold, which is every winter day and any overcast one: the previous capped
    scalar, unchanged. There the row would be straight over its whole reachable
    range *and* uncapped, which is #126/#244's hoarding bug exactly. Measured on
    #246's Belgian regression scenario (buy median 0.30, best export 0.16, no
    solar): the concave row exports 0.00 kWh at the evening peak and ends at
    6.16 kWh, against the capped scalar's 0.70 and 1.58. So the cap is still
    load-bearing wherever the quantity bound is not, and this is a domain
    distinction rather than a fallback -- a day whose need the battery can cover
    and one whose it cannot are different problems, and #602's evidence covers
    only the first.

    **Both** conditions are required, because each catches what the other
    misses. Testing only "does PV ever cover load" is a leaky proxy for a
    binding knee: `realworld_2026_03_24_225535` has a crossover and a knee of
    32.07 kWh against a 28.5 kWh pack, so it would take the concave branch and
    get an uncapped rate over an unbounded reachable range -- the configuration
    this split exists to prevent. Testing only the capacity bound misses the
    other side: on #246's Belgian scenario the knee is 12.0 kWh against 13.5
    usable, so it binds arithmetically, but with no sun at all the "PV refills
    the pack above the knee" premise the tail rate rests on is simply absent,
    and the DP holds ~89% of the pack at an uncapped rate. The knee must bind
    *and* the premise behind it must hold.

    The scan stops at the *first* crossover, so it reserves only for the dark
    stretch before the sun arrives and never for the following evening. That is
    the right stopping point in the case this was built for -- past sunrise the
    PV refills the pack, and the next evening is served from that refill inside
    a horizon that by then has real prices for it. It understates the need on a
    day whose sun covers load briefly but never builds a surplus to recharge
    from: the crossover exists, so the day takes the concave path, with a knee
    that assumes a refill it will not get. Thin winter sun, i.e. the same gap as
    below rather than a separate one.

    The winter carry #381 asks for needs a knee derived from the next cheap
    charging window rather than from sunrise. That is not in scope here and has
    no oracle behind it yet, so on those days this keeps the valuation #381's
    own analysis found wanting.
    """
    return curve_from_knee(
        buy_prices,
        sell_prices,
        knee_kwh_from_forecast(consumption_forecast, solar_forecast, battery_settings),
        pv_refills=any(
            pv_covers_load(consumption, solar)
            for consumption, solar in zip(
                consumption_forecast, solar_forecast, strict=False
            )
        ),
        battery_settings=battery_settings,
    )


def knee_kwh_from_trailing_darkness(
    consumption: list[float],
    solar: list[float],
    battery_settings: BatterySettings,
) -> float:
    """Knee for a horizon with no forecast beyond its own boundary.

    `knee_kwh_from_forecast` needs arrays describing the day *after* the
    boundary. Two callers do not have one and never will: the pinned scenario
    corpus, whose fixtures carry only the horizon they were captured over, and
    the forecast-robustness harness, which optimizes and executes one horizon
    against itself. What both do have is the dark stretch immediately *before*
    the boundary, which stands in for the one immediately after it.

    Walking backwards is the point, and a forward scan is wrong: most horizons
    start mid-morning with the sun already up, so a forward scan finds "solar
    covers load" in the first period and returns a knee of zero. That is how
    `regression_2026_08_15_084345` -- #602's own repro, captured at 08:43 --
    silently recorded `knee = 0.0` and stopped exercising the change it exists
    to pin.

    The scan ends where solar *covers load*, mirroring the forward version,
    rather than where solar becomes nonzero. Ending on any nonzero reading lets
    a single 0.003 kWh dusk crumb stop it immediately and zero the whole
    terminal row: `realworld_2026_04_27_184643` recorded `knee = 0.0` against a
    head rate of 1.863 that way, i.e. no terminal row at all across the entire
    battery. It uses `pv_covers_load` for the same reason the forward scan does
    -- a zero-load period is a data gap, not a crossover (#715).

    Two limits, neither fixable from the data these callers have. The mirror
    assumption is weakest exactly where it is used -- a boundary at midnight has
    a *short* trailing dark stretch where the real forward one runs to sunrise.
    And a horizon ending in daylight has no trailing dark stretch at all, so its
    knee is genuinely zero.
    """
    net = 0.0
    for consumed, produced in zip(reversed(consumption), reversed(solar), strict=True):
        if consumed <= 0:
            continue  # no-load period: a data gap, skip it entirely (#715)
        if pv_covers_load(consumed, produced):
            break
        net += consumed - produced
    return net / battery_settings.efficiency_discharge


def curve_from_knee(
    buy_prices: list[float],
    sell_prices: list[float],
    knee_kwh: float,
    *,
    pv_refills: bool,
    battery_settings: BatterySettings,
) -> TerminalValueCurve:
    """Rates and regime for an already-derived knee.

    Split out so the two knee derivations -- forward from real forecasts in
    production, backward from trailing darkness where no forecast beyond the
    boundary exists -- cannot drift on the *economics*, only on the quantity
    each is able to measure. Reconstructing the rates at a second site is how
    the corpus came to replay a `tail_rate` of 0.0 against a capture that used
    a nonzero one.
    """
    usable_capacity = battery_settings.max_soe_kwh - battery_settings.min_soe_kwh
    if knee_kwh >= usable_capacity or not pv_refills:
        return TerminalValueCurve.flat(
            calculate_terminal_value_per_kwh(buy_prices, sell_prices, battery_settings)
        )

    efficiency = battery_settings.efficiency_discharge
    max_sell = max(sell_prices)
    export_prices_vary = max_sell > min(sell_prices)
    head_rate = statistics.median(buy_prices) * efficiency
    tail_rate = min(sell_prices) * efficiency if export_prices_vary else 0.0

    # Concavity is the property this whole row exists to have, and it is
    # `head_rate > tail_rate` -- nothing else. Neither rate is floored at zero
    # (a negative tail is normal and pinned: `synthetic_extreme_negative_prices`
    # records -0.285), so on a day priced deeply enough below zero the head can
    # fall to or under the tail. Buy carries markup and VAT while sell carries a
    # tax reduction, so a sufficiently negative spot drives the buy median under
    # a still-positive sell floor -- head under tail, and the row is *convex*.
    #
    # A convex terminal row is worse than no fix at all: convexity makes the
    # extremes dominate, so the DP goes back to carrying everything or nothing,
    # which is #602's original defect wearing the new shape. Flooring the head
    # at zero does not prevent it (0 < tail is still convex); only comparing the
    # two rates does.
    #
    # When it cannot be concave there is no knee to express -- no reason to
    # value the first kWh above the last -- so this is the same "the quantity
    # bound cannot bind" case handled above, and it takes the same capped
    # scalar. No fixture in the corpus reaches this today (checked: no negative
    # head, no head under tail), so it is a guard, not a behaviour change.
    if head_rate <= tail_rate:
        return TerminalValueCurve.flat(
            calculate_terminal_value_per_kwh(buy_prices, sell_prices, battery_settings)
        )

    return TerminalValueCurve(
        head_rate=head_rate, knee_kwh=knee_kwh, tail_rate=tail_rate
    )
