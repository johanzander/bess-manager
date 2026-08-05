"""Synthetic scenario coverage validation for the #450 tie detector (see
docs/superpowers/specs/2026-08-05-tie-detection-synthetic-validation-design.md).

Perturbs a fixed set of existing fixtures across price level, volatility,
solar, and battery size to measure the real financial impact of the tie
detector's known coverage blind spot -- not a theoretical worst-case bound.
"""

import pytest

from core.bess.tests.synthetic.measure_tie_coverage import measure_scenario
from core.bess.tests.synthetic.perturb_scenario import PerturbationParams, perturb_scenario
from core.bess.tests.unit.test_scenarios import load_test_scenario

pytestmark = pytest.mark.slow

# Fixed, version-controlled matrix: (base_fixture_name, seed, params).
# Every entry is deterministic -- re-running this list reproduces identical
# scenarios and identical measurements.
#
# Deliberately small (2*3*2*2*1*1 = 24 scenarios): full_horizon_reference_cost
# is expensive (a full-horizon adaptive PWL solve, not a narrow window), and
# fires on most of these since the large majority of scenarios flag zero
# windows. Widen this matrix later, informed by measured per-scenario
# runtime, rather than guessing a larger size upfront.
#
# Fixtures must be buy_price/sell_price-format (perturb_scenario does not
# support base_prices/price_data-format fixtures). Of the fixtures in this
# format, `regression_2026_07_25_090230` was excluded: it starts with
# initial_soe (1.65 kWh) below min_soe_kwh (1.8 kWh) -- a legitimate
# below-min recovery state -- which trips a ValueError in
# segment_reference_cost's pinned-terminal-row construction (it requires the
# pinned end SOE to fall within [min_soe, max_soe]) for 2 of 12
# price/volatility/solar combinations. That is a real gap in the reference
# solver's handling of below-min recovery trajectories, out of scope for
# this measurement-only task; tracked for follow-up rather than fixed here.
_BASE_FIXTURES = [
    "regression_2026_07_26_203726",
    "regression_2026_08_02_043728",
]
_PRICE_LEVELS = [0.5, 1.0, 2.5]  # low / baseline / winter-peak-like
_VOLATILITY_LEVELS = [0.0, 0.15]
_SOLAR_LEVELS = [0.0, 1.0]
_BATTERY_OVERRIDES = [None]
_SEEDS = [1]

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

# TIE_MISS_BUDGET_SEK is deliberately not enforced yet -- see Task 7 of
# docs/superpowers/plans/2026-08-05-tie-detection-synthetic-validation.md.
# This test currently only measures and reports; run it directly to produce
# the data that sets the real budget.
TIE_MISS_BUDGET_SEK = None


def test_synthetic_scenario_tie_coverage():
    aggregate_ratio_counts: dict[str, int] = {}
    worst_impact = 0.0
    worst_impact_scenario = None
    impacts_measured = 0

    for base_name, seed, params in _SCENARIO_MATRIX:
        base = load_test_scenario(base_name)
        scenario = perturb_scenario(base, seed=seed, params=params)
        measurement = measure_scenario(scenario)

        for bucket, count in measurement.margin_ratio_counts.items():
            aggregate_ratio_counts[bucket] = aggregate_ratio_counts.get(bucket, 0) + count

        if measurement.financial_impact_sek is not None:
            impacts_measured += 1
            if measurement.financial_impact_sek > worst_impact:
                worst_impact = measurement.financial_impact_sek
                worst_impact_scenario = (base_name, seed, params)

    print(f"\nAggregate margin-ratio distribution across {len(_SCENARIO_MATRIX)} scenarios:")
    for bucket, count in aggregate_ratio_counts.items():
        print(f"  {bucket}: {count}")
    print(f"Financial impact measured on {impacts_measured} zero-flag scenarios")
    print(f"Worst observed financial impact: {worst_impact:.6f} SEK ({worst_impact_scenario})")

    if TIE_MISS_BUDGET_SEK is not None:
        assert worst_impact <= TIE_MISS_BUDGET_SEK, (
            f"Worst observed missed-tie financial impact ({worst_impact:.6f} SEK, "
            f"scenario {worst_impact_scenario}) exceeds the budget "
            f"({TIE_MISS_BUDGET_SEK} SEK)"
        )
