"""Tests for the removed discharge profitability floor and the #240
flow-accounting fix, per docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.
"""

import pytest

from core.bess.dp_battery_algorithm import (
    _compute_reward,
    _create_idle_schedule,
    optimize_battery_schedule,
)
from core.bess.models import OptimizationResult
from core.bess.tests.helpers import make_battery_settings
from core.bess.tests.unit.test_scenarios import (
    build_scenario_optimizer_inputs,
    get_all_scenario_files,
)


def test_discharge_no_longer_blocked_by_cost_basis_floor():
    """The old cost_basis profitability floor (removed) used to veto a
    discharge outright by returning -inf whenever its value didn't clear a
    historical average cost -- even though IDLE, competing in the same
    max() in _run_dynamic_programming, already makes that comparison
    correctly via the forward-looking value function. _compute_reward must
    now always return a finite reward for a physically valid discharge."""
    settings = make_battery_settings()
    power = -1.0
    next_soe = 5.0 - (abs(power) * 1.0 / settings.efficiency_discharge)
    reward, _, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=0.5,
        battery_settings=settings,
        dt=1.0,
        buy_price=[0.6],
        sell_price=[0.5],
        solar_production=0.0,
        cost_basis=2.0,  # old floor would have blocked this: 2.0 >> ~0.57
    )
    assert reward != float(
        "-inf"
    ), "discharge was vetoed by a profitability floor that no longer exists"


def test_dp_never_plans_a_sub_resolution_export():
    """#497: the optimizer never produces a period that exports less than
    GRID_FLOW_RESOLUTION_KWH from the battery while also serving the home.

    Supersedes #240's version of this test, which asserted that
    `_compute_reward` zeroed the export *credit* for such an overshoot. That
    only ever patched the revenue: `battery_discharged` and `next_soe` still
    carried energy the hardware never moved, so the period's reported flows
    did not add up and the plan was not executable as written. The guarantee
    now lives one level up -- `_discharge_candidates` does not offer the
    action at all -- which is why this asserts on an optimized schedule
    rather than on a hand-built call to the reward function.

    The home consumption below is deliberately off the discharge rate grid
    (5 kW max -> 0.05 kW steps), so exact load cover is unreachable and the
    DP is maximally tempted to overshoot slightly.
    """
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    horizon = 6
    result = optimize_battery_schedule(
        buy_price=[2.0] * horizon,
        sell_price=[1.9] * horizon,  # high sell price: overshooting is tempting
        home_consumption=[1.234] * horizon,
        solar_production=[0.0] * horizon,
        initial_soe=15.0,
        battery_settings=settings,
        period_duration_hours=1.0,
    )

    offenders = [
        (pd.period, pd.energy.grid_exported, pd.energy.battery_to_home)
        for pd in result.period_data
        if 0
        < pd.energy.grid_exported - pd.energy.solar_to_grid - pd.energy.battery_to_grid
    ]
    assert not offenders, (
        f"periods export energy attributed to no source -- the DP proposed a "
        f"discharge the inverter cannot execute as commanded: {offenders}"
    )


def test_large_discharge_overshoot_still_credited_as_export():
    """A discharge that overshoots home_consumption by 0.01 kWh or more is a
    genuine deliberate export (BATTERY_EXPORT), not self-throttled
    load-following -- it must still be credited as export revenue."""
    settings = make_battery_settings()
    dt = 1.0
    home_consumption = 1.0
    power = -2.0  # discharges 2.0 kWh -- 1.0 kWh over consumption
    next_soe = 5.0 - (abs(power) * dt / settings.efficiency_discharge)
    reward, _, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=settings,
        dt=dt,
        buy_price=[1.0],
        sell_price=[0.8],
        solar_production=0.0,
        cost_basis=0.1,
    )
    # 1.0 kWh exported at sell_price=0.8, no import, no wear on discharge.
    assert reward == pytest.approx(0.8, abs=1e-9)


def test_run_dynamic_programming_returns_one_value():
    """policy is no longer used by any caller once Step 2 recomputes actions
    directly from V -- _run_dynamic_programming returns V only."""
    from core.bess.dp_battery_algorithm import _run_dynamic_programming

    settings = make_battery_settings()
    result = _run_dynamic_programming(
        horizon=3,
        buy_price=[1.0, 1.0, 1.0],
        sell_price=[0.8, 0.8, 0.8],
        home_consumption=[0.5, 0.5, 0.5],
        battery_settings=settings,
        dt=1.0,
        solar_production=[0.0, 0.0, 0.0],
        initial_soe=5.0,
    )
    import numpy as np

    assert isinstance(
        result, np.ndarray
    ), f"expected a bare V array, got {type(result)}"


def test_small_export_only_discharge_classified_as_battery_export():
    """A discharge with zero home-deficit coverage and a small (but
    meaningfully nonzero) export must be classified BATTERY_EXPORT, not
    LOAD_SUPPORT -- LOAD_SUPPORT maps to load_first, which physically cannot
    export at all (core/bess/simulation/inverter_simulator.py's mode_to_power
    caps load_first delivery at max(0, home-solar), i.e. zero when solar
    already covers home). Mislabeling this as LOAD_SUPPORT makes the plan
    unrealizable: real/simulated hardware delivers zero instead of the
    planned export, and that zero triggers passive solar charging instead
    (_state_transition's IDLE branch), a much larger, unplanned action.
    Regression for the R == P failures traced on
    realworld_2026_04_27_211212 period 42 during Task 8's fixture
    regeneration."""
    from core.bess.models import EnergyData
    from core.bess.strategic_intent import classify_strategic_intent

    energy_data = EnergyData(
        solar_production=3.5,
        home_consumption=0.2,
        battery_charged=0.0,
        battery_discharged=0.05,
        grid_imported=0.0,
        grid_exported=3.35,
        battery_soe_start=7.68,
        battery_soe_end=7.63,
    )
    intent = classify_strategic_intent(power=-0.2, energy_data=energy_data)
    assert (
        intent == "BATTERY_EXPORT"
    ), f"expected BATTERY_EXPORT for a 100%-export discharge, got {intent}"


@pytest.mark.slow
@pytest.mark.parametrize("scenario_name", get_all_scenario_files())
def test_dp_output_never_worse_than_all_idle_schedule(scenario_name):
    """The numerical safety net in optimize_battery_schedule always returns
    whichever of (DP schedule, all-IDLE schedule) is cheaper -- so the
    optimizer's returned cost must never exceed the all-IDLE baseline,
    across every pinned fixture. This is the property the whole redesign
    rests on (docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md).

    Skipped where export curtailment is active: there, production deliberately
    judges the guardrail at the floored `reward_sell_price` -- the objective
    the DP was actually asked to optimize -- and the returned schedule carries
    #507's curtailed-period reporting adjustment, which `_create_idle_schedule`
    (real prices, no such adjustment) does not. Comparing the two at real
    prices is not the invariant the guardrail enforces, so a pass or a failure
    here would say nothing about it either way.
    """
    scenario, inputs = build_scenario_optimizer_inputs(scenario_name)
    if inputs.get("export_curtailment_active"):
        pytest.skip(
            "curtailment-active fixture: production compares the guardrail at "
            "reward_sell_price, not at the real sell_price this test uses"
        )
    battery_settings = inputs["battery_settings"]
    buy_prices = inputs["buy_price"]
    sell_prices = inputs["sell_price"]
    dt = inputs["period_duration_hours"]
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]
    horizon = len(buy_prices)

    result = optimize_battery_schedule(**inputs)
    idle_result = _create_idle_schedule(
        horizon=horizon,
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        dt=dt,
        currency="SEK",
    )
    # Both sides are credited for energy left at the boundary, because that is
    # the objective the DP actually optimized (#602). Comparing raw in-horizon
    # cost would make every plan that deliberately carries energy look worse
    # than doing nothing -- it forgoes in-horizon export revenue to hold value
    # past the boundary, which is the entire point. Pre-#602 the capped scalar
    # was small enough that no plan carried enough for the omission to show;
    # `synthetic_seasonal_spring` now carries 23.62 kWh and the raw comparison
    # reads 48.24 against all-IDLE's 44.47 while the credited one reads 24.68.
    # This mirrors the guardrail's own comparison in `optimize_battery_schedule`,
    # which nets the same term on both sides for the same reason.
    curve = inputs.get("terminal_curve")
    min_soe = battery_settings.min_soe_kwh

    def credited(schedule: OptimizationResult) -> float:
        cost = schedule.economic_summary.battery_solar_cost
        if curve is None:
            return float(cost)
        usable = schedule.period_data[-1].energy.battery_soe_end - min_soe
        return float(cost - curve.value(usable))

    assert credited(result) <= credited(idle_result) + 1e-6, (
        f"{scenario_name}: DP schedule cost {credited(result):.4f} exceeds "
        f"all-IDLE cost {credited(idle_result):.4f} (both credited for "
        f"boundary energy)"
    )


def test_compute_reward_credits_export_threshold_free():
    """_compute_reward has no export-credit threshold (#497): it prices
    whatever flows _ac_flows reports. Keeping sub-resolution overshoots out
    of the plan is _discharge_is_unexecutable's job, applied to the action
    set before anything is priced -- so this reward, computed for an action
    the DP can never propose, still credits the export rather than zeroing
    it (the old #240/#320 self-throttle band is gone, not relocated here)."""
    from core.bess.dp_battery_algorithm import _compute_reward
    from core.bess.tests.helpers import make_battery_settings

    settings = make_battery_settings()
    dt = 1.0
    home_consumption = 1.0
    power = -1.05  # 0.05 kWh overshoot -- inside the old self-throttle band
    next_soe = 5.0 - (abs(power) * dt / settings.efficiency_discharge)
    reward, _, _ = _compute_reward(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=settings,
        dt=dt,
        buy_price=[1.0],
        sell_price=[1.0],
        solar_production=0.0,
        cost_basis=0.1,
    )
    # 0.05 kWh exported at sell_price=1.0, no import, no wear on discharge --
    # this must now be credited as a real export, not zeroed.
    assert reward == pytest.approx(
        0.05, abs=1e-9
    ), f"expected 0.05 kWh export credited at sell_price, got reward={reward}"


def test_idle_below_floor_does_not_fabricate_soe():
    """#233: when the period starts below min_soe_kwh (e.g. a live sensor
    reading below the configured Min SOC, as happens in demo mode or with an
    external controller), the final safety clamp in _state_transition must
    not raise next_soe up to the floor with zero real energy stored. Before
    the fix, an IDLE action with no solar surplus jumped soe straight to
    min_soe_kwh in a single period -- a fabricated number, not one backed by
    actual charging."""
    from core.bess.dp_battery_algorithm import _state_transition
    from core.bess.tests.helpers import make_battery_settings

    settings = (
        make_battery_settings()
    )  # min_soc=11%, total_capacity=20 -> min_soe_kwh=2.2
    below_floor_soe = 1.0  # below min_soe_kwh=2.2

    next_soe = _state_transition(
        soe=below_floor_soe,
        power=0.0,  # IDLE
        battery_settings=settings,
        dt=1.0,
        solar_production=0.0,  # no surplus -- nothing can charge the battery
        home_consumption=1.0,
    )

    assert next_soe == pytest.approx(below_floor_soe, abs=1e-9), (
        f"expected next_soe to stay at {below_floor_soe} (no real charging "
        f"occurred), but it was raised to {next_soe} -- energy was fabricated "
        f"by the min_soe_kwh floor clamp"
    )


def test_state_transition_grid_below_floor_matches_scalar():
    """#233: _state_transition_grid must mirror _state_transition's fix for
    bit-identical parity (see #236), even though its current DP-search
    callers never populate soe below min_soe_kwh."""
    import numpy as np

    from core.bess.dp_battery_algorithm import _state_transition, _state_transition_grid
    from core.bess.tests.helpers import make_battery_settings

    settings = make_battery_settings()
    below_floor_soe = 1.0

    scalar_next_soe = _state_transition(
        soe=below_floor_soe,
        power=0.0,
        battery_settings=settings,
        dt=1.0,
        solar_production=0.0,
        home_consumption=1.0,
    )

    grid_next_soe = _state_transition_grid(
        soe=np.array([[below_floor_soe]]),
        power=np.array([[0.0]]),
        battery_settings=settings,
        dt=1.0,
        solar_production=0.0,
        home_consumption=1.0,
    )

    assert grid_next_soe[0, 0] == pytest.approx(scalar_next_soe, abs=1e-9)


def test_best_action_recovers_from_below_floor_start():
    """#233 code-review follow-up: once _state_transition stopped
    fabricating a jump to min_soe_kwh, _best_action_at_continuous_state's
    consider() closure still used the pre-fix bounds check
    (`next_soe < min_soe_kwh`), which now silently rejects every candidate
    -- including plain IDLE -- whenever a period can't fully cross back
    above the floor in one step. Every candidate falls through to the
    function's defaults (best_reward=0.0), fabricating a zero-cost period
    even though grid import to cover home load is genuinely happening.
    Regression test: with a real arbitrage spread and initial_soe below
    min_soe_kwh, the optimizer must find nonzero savings, not freeze at
    the starting SOE for the whole horizon."""
    from core.bess.dp_battery_algorithm import optimize_battery_schedule
    from core.bess.tests.helpers import make_battery_settings

    settings = make_battery_settings(
        total_capacity=20.0, min_soc=25.0, max_charge_power_kw=5.0
    )  # min_soe_kwh = 5.0
    buy_price = [0.2, 1.0, 0.2, 1.0, 0.2, 1.0]
    sell_price = [0.1, 0.8, 0.1, 0.8, 0.1, 0.8]
    home_consumption = [0.2] * 6
    solar_production = [0.0] * 6

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=4.5,  # below min_soe_kwh=5.0
        battery_settings=settings,
        period_duration_hours=1.0,
    )

    assert result.economic_summary.grid_to_battery_solar_savings > 0.0, (
        "optimizer found zero savings starting below the SOE floor -- "
        "every candidate action was likely rejected by a stale bounds "
        "check that doesn't account for a below-floor starting soe"
    )
    first_period = result.period_data[0]
    assert (
        first_period.energy.battery_soe_start != first_period.energy.battery_soe_end
        or first_period.energy.grid_imported > 0
    ), "expected either real charging or accounted grid import in period 0"
