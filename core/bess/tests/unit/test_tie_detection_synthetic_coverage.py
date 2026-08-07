"""Synthetic scenario coverage validation for the #450 tie detector (see
docs/superpowers/specs/2026-08-05-tie-detection-synthetic-validation-design.md).

Perturbs a fixed set of existing fixtures across price level, volatility,
solar, and battery size to measure the real financial impact of the tie
detector's known coverage blind spot -- not a theoretical worst-case bound.
"""

import pytest

from core.bess.exceptions import PWLEndSoeOutOfRangeError
from core.bess.tests.synthetic.measure_tie_coverage import measure_scenario
from core.bess.tests.synthetic.perturb_scenario import (
    PerturbationParams,
    perturb_scenario,
)
from core.bess.tests.unit.test_scenarios import load_test_scenario

pytestmark = pytest.mark.slow

# Fixed, version-controlled matrix: (base_fixture_name, seed, params).
# Every entry is deterministic -- re-running this list reproduces identical
# scenarios and identical measurements.
#
# 4*3*2*2*2*1 = 96 DISTINCT scenarios, measured at ~66s total -- inside the
# 30-90s budget for this suite's addition to the existing slow suite (all 96
# run the hybrid DP; 4 then fail the reference solve as infeasible, see
# below, leaving 92 measured). A first pass at 192 measured
# 132.59s, well over budget, so the matrix is held at 96 measured solves --
# runtime tracks the number of entries, so the question is only which axes
# spend them.
#
# The seed axis is deliberately a single value. `perturb_scenario` consumes
# its seeded RNG only inside `if params.volatility_jitter:`, so seeds are
# indistinguishable at jitter 0.0 and merely resample the same distribution
# at a fixed non-zero jitter. Spending the budget on a second *volatility
# level* instead makes every one of the 96 entries a distinct scenario and
# adds a real axis (flat-vs-jittered prices) rather than a second draw of an
# existing one. An earlier revision paired `_VOLATILITY_LEVELS = [0.0]` with
# two seeds, which silently measured 48 distinct scenarios twice.
#
# Fixtures must be buy_price/sell_price-format (perturb_scenario does not
# support base_prices/price_data-format fixtures); of the fixtures in the
# current suite, only these four qualify.
_BASE_FIXTURES = [
    "regression_2026_07_25_090230",
    "regression_2026_07_26_203726",
    "regression_2026_08_02_043728",
    "regression_frank_debug_before",
]
_PRICE_LEVELS = [0.5, 1.0, 2.5]  # low / baseline / winter-peak-like
_VOLATILITY_LEVELS = [0.0, 0.15]  # flat / +-15% per-period price jitter
_SOLAR_LEVELS = [0.0, 1.0]
_BATTERY_OVERRIDES = [None, 10.0]  # None = fixture's own capacity
_SEEDS = [1]  # see the axis discussion above -- seeds only matter with jitter

_SCENARIO_MATRIX = [
    (
        base,
        seed,
        PerturbationParams(
            price_level_multiplier=price,
            volatility_jitter=volatility,
            solar_scale=solar,
            battery_capacity_override_kwh=battery,
        ),
    )
    for base in _BASE_FIXTURES
    for price in _PRICE_LEVELS
    for volatility in _VOLATILITY_LEVELS
    for solar in _SOLAR_LEVELS
    for battery in _BATTERY_OVERRIDES
    for seed in _SEEDS
]

# `regression_2026_07_25_090230` starts with initial_soe (1.65 kWh) below
# min_soe_kwh (1.8 kWh) -- a legitimate below-min recovery state (production
# logs a warning and works to restore charge). On a handful of this
# fixture's perturbations, the near-miss segment's end-of-window SOE is
# still below min_soe during that recovery, and `segment_reference_cost`'s
# pinned-terminal-row construction hard-requires the pinned end SOE to fall
# within [min_soe, max_soe] -- so it raises ValueError instead of measuring.
# That is a real gap in the reference solver's handling of below-min
# recovery trajectories, out of scope for this measurement-only task to fix.
# Rather than drop the whole fixture -- its other perturbations measure
# normally and contribute real data points -- each scenario that hits it is
# caught individually, by the solver's own `PWLEndSoeOutOfRangeError` type
# (never by matching a substring of its prose message), and counted/printed
# as infeasible below. The counts asserted at the end of the test are what
# keeps that skip honest: if a regression ever made most of the matrix
# unmeasurable, the budget gate alone would still pass on the survivors.

# Ratio below this is treated as a "genuinely close call" for the
# blind/distant/close breakdown printed below -- not a detector threshold
# (that is 1.0 exactly; see `best_near_miss_ratio`), just a reporting cutoff
# to separate "this near miss was in the right neighbourhood" from "this was
# the least-far of a set of scenarios nowhere close to being flagged".
_CLOSE_CALL_RATIO = 5.0

# TIE_MISS_BUDGET_SEK is now enforced: 0.05 SEK, based on the worst observed
# financial impact of 0.017188 SEK across the 96 distinct scenarios of this
# matrix (giving ~3x safety margin). When worst_impact exceeds this budget, the
# assertion below fails.
TIE_MISS_BUDGET_SEK = 0.05

# Coverage floors on the measurement itself, not on the economics. The budget
# assertion alone can be satisfied by a single surviving data point, so a
# regression that made most of the matrix unmeasurable (a solver raise on more
# perturbations, a near-miss selector that stopped forming ratios) would pass
# silently while the suite had effectively stopped measuring. Set with real
# headroom around the current 86-measured / 4-infeasible split so ordinary
# fixture drift does not trip them, but a collapse does.
_MIN_IMPACTS_MEASURED = 75
_MAX_INFEASIBLE_SCENARIOS = 10


def test_synthetic_scenario_tie_coverage():
    aggregate_ratio_counts: dict[str, int] = {}
    worst_impact: float | None = None
    worst_impact_scenario = None
    impacts_measured = 0
    blind_scenarios = 0  # every period had zero epsilon -- nothing could ever form
    # Not fully blind (some periods have a real slope), but no period yielded
    # a formable ratio anyway -- e.g. every non-flat period had an infinite
    # margin. Distinct from "blind"; kept separate rather than folded in so
    # a reader can see the two blind-spot causes tie_detection.py itself
    # distinguishes (`blind_zero_epsilon` vs `blind_inf_margin`).
    no_ratio_not_blind = 0
    distant_scenarios = 0  # formable ratio, but >= _CLOSE_CALL_RATIO away from 1.0
    close_scenarios = 0  # formable ratio < _CLOSE_CALL_RATIO -- a genuine near miss
    infeasible_scenarios: list[tuple[str, int, PerturbationParams]] = []

    for base_name, seed, params in _SCENARIO_MATRIX:
        base = load_test_scenario(base_name)
        scenario = perturb_scenario(base, seed=seed, params=params)
        try:
            measurement = measure_scenario(scenario)
        except PWLEndSoeOutOfRangeError:
            infeasible_scenarios.append((base_name, seed, params))
            continue

        for bucket, count in measurement.margin_ratio_counts.items():
            aggregate_ratio_counts[bucket] = (
                aggregate_ratio_counts.get(bucket, 0) + count
            )

        if measurement.zero_epsilon_periods == measurement.total_periods:
            blind_scenarios += 1
        elif measurement.near_miss_ratio is None:
            no_ratio_not_blind += 1
        elif measurement.near_miss_ratio < _CLOSE_CALL_RATIO:
            close_scenarios += 1
        else:
            distant_scenarios += 1

        if measurement.financial_impact_sek is not None:
            impacts_measured += 1
            if worst_impact is None or measurement.financial_impact_sek > worst_impact:
                worst_impact = measurement.financial_impact_sek
                worst_impact_scenario = (base_name, seed, params)

    print(
        f"\nAggregate margin-ratio distribution across {len(_SCENARIO_MATRIX)} scenarios:"
    )
    for bucket, count in aggregate_ratio_counts.items():
        print(f"  {bucket}: {count}")

    print(
        f"\nInfeasible (below-floor initial SOE, PWLEndSoeOutOfRangeError caught): "
        f"{len(infeasible_scenarios)} of {len(_SCENARIO_MATRIX)} scenarios"
    )
    for base_name, seed, params in infeasible_scenarios:
        print(f"  {base_name} seed={seed} {params}")

    measured_scenarios = len(_SCENARIO_MATRIX) - len(infeasible_scenarios)
    print(
        f"\nNear-miss ratio breakdown across {measured_scenarios} measured scenarios:"
        f"\n  fully detector-blind (zero epsilon everywhere): {blind_scenarios}"
        f"\n  no formable ratio, not fully blind (infinite margin everywhere non-flat): "
        f"{no_ratio_not_blind}"
        f"\n  distant near miss (ratio >= {_CLOSE_CALL_RATIO}x threshold): {distant_scenarios}"
        f"\n  close near miss (ratio < {_CLOSE_CALL_RATIO}x threshold): {close_scenarios}"
    )

    print(
        f"\nFinancial impact measured on {impacts_measured} of {measured_scenarios} "
        "scenarios (the remainder had no formable near-miss ratio to measure a "
        "delta for)"
    )
    if worst_impact is None:
        print(
            "Worst observed financial impact: none measured (no scenario had a formable ratio)"
        )
    else:
        print(
            f"Worst observed financial impact: {worst_impact:.6f} SEK ({worst_impact_scenario})"
        )

    assert len(infeasible_scenarios) <= _MAX_INFEASIBLE_SCENARIOS, (
        f"{len(infeasible_scenarios)} of {len(_SCENARIO_MATRIX)} scenarios were "
        f"skipped as infeasible (limit {_MAX_INFEASIBLE_SCENARIOS}) -- the suite "
        "is measuring far less of its matrix than it was calibrated on, so the "
        "budget assertion below is no longer meaningful evidence"
    )
    assert impacts_measured >= _MIN_IMPACTS_MEASURED, (
        f"financial impact was measured on only {impacts_measured} scenarios "
        f"(floor {_MIN_IMPACTS_MEASURED}) -- the budget assertion below would "
        "pass on the survivors while the suite had effectively stopped "
        "measuring coverage"
    )

    if TIE_MISS_BUDGET_SEK is not None:
        assert worst_impact is not None and worst_impact <= TIE_MISS_BUDGET_SEK, (
            f"Worst observed missed-tie financial impact ({worst_impact} SEK, "
            f"scenario {worst_impact_scenario}) exceeds the budget "
            f"({TIE_MISS_BUDGET_SEK} SEK)"
        )
