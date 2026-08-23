"""The sub-period discharge authorization is decided by the DP, not re-derived (#526).

`shadow_price` is a reading of the value-function interpolant below the current
state, which is undefined at or below the reserve floor, where no cell below exists.
The DP therefore skips the assignment when
start-of-period SoE has no cell below it, leaving the field at its `0.0` default — the
same value a genuinely worthless kWh produces. Consumers comparing
`buy_price >= shadow_price` cannot tell the two apart, and `0.0` satisfies
that inequality for any positive buy price, so the sub-period discharge ceiling was
opened on a value that was never computed.

These tests pin the authorization as an explicit DP output. They are built from real
optimizer-produced schedules rather than hand-assembled decisions, because the failure
mode is precisely that a branch is reachable by real DP output while a synthetic unit
test on the gate function looks fine.
"""

import pytest

from core.bess.dp_battery_algorithm import has_value_cell_below
from core.bess.tests.helpers import run_scenario
from core.bess.tests.unit.test_scenarios import (
    build_scenario_inputs,
    load_test_scenario,
)

# Both fixtures place the battery on its reserve floor for part of the horizon, which
# is what drives start-of-period SoE onto grid index 0 — the state where no shadow
# price is computable.
FLOOR_SOE_FIXTURES = [
    "realworld_2026_04_27_184643",
    "realworld_2026_04_11_004719",
]


def _floor_index_periods(result, settings):
    """Periods with no value-function cell below their start-of-period SoE.

    Asks the DP's own predicate rather than re-deriving the index rule: a
    test-side mirror of that arithmetic is exactly what went stale in #571,
    silently selecting a different set of periods than production priced.
    """
    return [
        pd
        for pd in result.period_data
        if not has_value_cell_below(pd.energy.battery_soe_start, settings)
    ]


@pytest.mark.parametrize("scenario_name", FLOOR_SOE_FIXTURES)
def test_floor_soe_period_does_not_authorize_intra_period_discharge(scenario_name):
    """A period with no computable shadow price must not authorize the gate.

    Before #526 these periods carried `shadow_price == 0.0` by default, which any
    positive buy price cleared, so the ceiling opened on absent data.
    """
    scenario = load_test_scenario(scenario_name)
    _, settings, _, _, _ = build_scenario_inputs(scenario_name)
    result = run_scenario(scenario)

    floor_periods = _floor_index_periods(result, settings)

    # Vacuity guard: if the fixture stops producing floor-SoE periods, this test
    # silently stops testing anything. That is the coverage gap #526 is about.
    assert floor_periods, (
        f"{scenario_name} no longer produces any start-of-period SoE at grid "
        "index 0 — this test no longer exercises the uncomputed-shadow-price "
        "branch and must be re-pointed at a fixture that does"
    )

    unauthorized = [
        pd for pd in floor_periods if pd.decision.intra_period_discharge_allowed
    ]
    assert not unauthorized, (
        f"{len(unauthorized)} of {len(floor_periods)} floor-SoE periods in "
        f"{scenario_name} authorized sub-period discharge despite having no "
        "computable shadow price"
    )


@pytest.mark.parametrize("scenario_name", FLOOR_SOE_FIXTURES)
def test_computed_periods_authorize_on_the_economics(scenario_name):
    """Where a shadow price IS computed, the authorization follows the economics.

    Guards against the fix degenerating into "never authorize": the decision must
    still be the buy-vs-hold comparison for every period the DP could evaluate.

    #683: that comparison carries no efficiency factor. `shadow_price` is priced
    per kWh *delivered*, the same unit as `buy_price` -- covering dE consumes
    dE/eta of SoE, which would later have delivered dE anyway, so eta cancels on
    both sides.
    """
    scenario = load_test_scenario(scenario_name)
    _, settings, buy_prices, _, _ = build_scenario_inputs(scenario_name)
    result = run_scenario(scenario)

    floor_periods = {id(pd) for pd in _floor_index_periods(result, settings)}

    evaluated = 0
    for period, pd in enumerate(result.period_data):
        if id(pd) in floor_periods or period >= len(buy_prices):
            continue
        evaluated += 1
        expected = buy_prices[period] >= pd.decision.shadow_price
        assert pd.decision.intra_period_discharge_allowed is expected, (
            f"period {period} of {scenario_name}: authorization "
            f"{pd.decision.intra_period_discharge_allowed} disagrees with "
            f"buy {buy_prices[period]:.4f} >= shadow "
            f"{pd.decision.shadow_price:.4f}"
        )

    assert (
        evaluated
    ), f"{scenario_name} produced no periods with a computed shadow price"


def test_idle_guardrail_schedule_does_not_authorize_discharge():
    """The guardrail idle schedule has no value function, so it authorizes nothing.

    `_create_idle_schedule` is the numerical safety net returned when the optimized
    plan scores worse than doing nothing. It builds decisions without any `V`, so
    there is no dV/dSoE to authorize against — and on a sunny all-IDLE day
    `classify_strategic_intent` can label periods SOLAR_EXPORT, which IS a
    gate-consulting intent. Before #526 those periods carried the `0.0` default and
    opened the ceiling to 100 on a value nothing had computed.

    This test would pass on the field default alone, so it also asserts the
    reachability that makes the case matter: that a gate-consulting intent really
    is produced on this path.
    """
    from core.bess.dp_battery_algorithm import _create_idle_schedule
    from core.bess.tests.helpers import make_battery_settings

    horizon = 24
    settings = make_battery_settings()
    # Midday solar well above consumption, so the idle schedule exports and
    # classify_strategic_intent labels those periods SOLAR_EXPORT.
    solar = [0.0] * 6 + [4.0] * 12 + [0.0] * 6
    home = [0.5] * horizon

    result = _create_idle_schedule(
        horizon=horizon,
        buy_price=[1.5] * horizon,
        sell_price=[0.5] * horizon,
        home_consumption=home,
        solar_production=solar,
        initial_soe=settings.max_soe_kwh,  # full: solar cannot be absorbed, it exports
        battery_settings=settings,
        dt=1.0,
        currency="SEK",
    )

    gate_consulting = [
        pd
        for pd in result.period_data
        if pd.decision.strategic_intent in ("SOLAR_EXPORT", "SOLAR_STORAGE")
    ]
    assert gate_consulting, (
        "guardrail idle schedule produced no gate-consulting intent — this test "
        "no longer covers the path where the missing authorization would matter"
    )

    authorized = [
        pd for pd in gate_consulting if pd.decision.intra_period_discharge_allowed
    ]
    assert not authorized, (
        f"{len(authorized)} guardrail idle periods authorized sub-period discharge "
        "despite the path having no value function"
    )
