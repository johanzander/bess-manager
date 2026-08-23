# core/bess/tests/integration/test_plan_faithfulness.py

import pytest

from core.bess.simulation.verification import verify_plan_faithfulness
from core.bess.tests.helpers import make_battery_settings


def _controlled_scenario():
    """A scenario whose optimal plan uses only faithfully-executable actions:
    night grid-charge at a clear low price, evening discharge-to-grid at a clear
    high price, no fractional solar-storage. dt = 1.0h for simple arithmetic."""
    n = 6
    buy = [0.5, 0.5, 2.0, 2.0, 1.0, 1.0]
    sell = [0.4, 0.4, 1.8, 1.8, 0.9, 0.9]
    solar = [0.0] * n
    home = [0.5] * n
    return buy, sell, solar, home


def test_realized_equals_planned_on_controlled_scenario():
    bs = make_battery_settings()
    buy, sell, solar, home = _controlled_scenario()
    planned_cost, realized_cost, per_period = verify_plan_faithfulness(
        buy_price=buy,
        sell_price=sell,
        solar=solar,
        home=home,
        initial_soe=3.0,
        settings=bs,
        dt=1.0,
    )
    # cent-exact: faithful control reproduces the plan
    assert round(realized_cost, 2) == round(
        planned_cost, 2
    ), f"R={realized_cost} != P={planned_cost}; per-period deltas: {per_period}"


def test_identical_command_sequences_have_zero_delta():
    from core.bess.simulation.inverter_simulator import ControlCommand
    from core.bess.simulation.verification import ab_compare

    bs = make_battery_settings()
    n = 6
    buy = [1.0] * n
    sell = [0.8] * n
    solar = [0.5] * n
    home = [0.3] * n
    base = [ControlCommand("load_first", 0, False)] * n
    delta = ab_compare(
        base, base, solar, home, buy, sell, initial_soe=5.0, settings=bs, dt=1.0
    )
    assert delta == 0.0


def test_solar_storage_mode_stores_all_surplus():
    """IDLE/SOLAR_STORAGE: load_first + no discharge stores surplus via passive charging.

    After the grid-charging-during-surplus fix, mode_to_power returns 0.0 for
    load_first + no discharge (regardless of surplus). _state_transition's IDLE branch
    then performs passive solar charging (solar fills battery, no grid draw). The old
    code returned surplus/dt which went through the STORE branch; that used to be
    equivalent (grid_to_battery was gated to 0), but after removing the surplus gate
    the STORE branch would add grid top-up — incorrect for load_first hardware.
    """
    from core.bess.simulation.inverter_simulator import (
        ControlCommand,
        mode_to_power,
        simulate,
    )

    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("load_first", discharge_rate_pct=0, grid_charge=False)

    # mode_to_power returns 0.0; _state_transition IDLE branch does the solar charging.
    assert mode_to_power(cmd, solar=5.0, home=0.5, soe=5.0, settings=bs, dt=1.0) == 0.0

    sim = simulate(
        [cmd],
        solar_production=[5.0],
        home_consumption=[0.5],
        buy_price=[1.0],
        sell_price=[1.0],
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    stored = sim.period_data[0].energy.battery_soe_end - 5.0
    assert (
        stored > 4.0
    ), f"load_first should store ~all 4.5 kWh surplus via IDLE passive charging, got {stored:.2f}"


def test_forecast_robustness_more_solar_than_planned():
    """Task 7 / #145: optimize on a solar FORECAST, then execute against HIGHER
    actual solar. The binary store/export model must be forecast-robust — bonus
    solar is captured/exported, never wasted — so realized is at least as good as
    the forecast plan (lower or equal cost)."""
    from core.bess.simulation.verification import realized_under_solar_error

    bs = make_battery_settings()
    n = 6
    buy = [1.0, 1.0, 2.0, 2.0, 1.0, 1.0]
    sell = [0.8, 0.8, 1.8, 1.8, 0.9, 0.9]
    home = [0.3] * n
    forecast_solar = [1.0] * n
    actual_solar = [2.0] * n  # reality beats the forecast

    planned, realized = realized_under_solar_error(
        forecast_solar=forecast_solar,
        actual_solar=actual_solar,
        buy_price=buy,
        sell_price=sell,
        home=home,
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    # more actual solar than forecast → realized cost no worse than planned (bonus
    # solar exported/stored, no phantom export booked against the forecast)
    assert (
        realized <= planned + 1e-6
    ), f"forecast not robust: realized {realized} > planned {planned}"


def test_scenarios_are_plan_faithful_realized_equals_planned():
    """Scenarios verify R (realized), not just P (plan): executing the optimizer's
    plan through the inverter simulator must reproduce the planned economics to
    within the DP's SoE-grid resolution. A larger gap is a control-fidelity
    finding (#145).

    The optimizer models power=0 as passive solar charging (matching load_first
    hardware behavior), so solar scenarios are included and must pass.
    """
    from core.bess.tests.helpers import run_scenario_realized

    scenarios = {
        "grid_charge_arbitrage": {
            "base_prices": [0.5, 0.5, 2.0, 2.0, 1.0, 1.0],
            "home_consumption": [0.5] * 6,
            "solar_production": [0.0] * 6,
            "battery": _battery(initial_soe=3.0),
        },
        "solar_day": {
            "base_prices": [0.5, 0.5, 1.0, 1.0, 0.8, 0.8],
            "home_consumption": [0.5] * 6,
            "solar_production": [1.5, 1.8, 1.9, 1.7, 0.5, 0.0],
            "battery": _battery(initial_soe=5.0),
        },
    }
    # Tolerance reflects the DP's 0.1 kWh SoE-grid resolution: the plan trajectory
    # is reconstructed continuously, but the policy LOOKUP still snaps SoE to the
    # grid, leaving a sub-öre-per-period residual on solar-storage days.
    #
    # These two scenarios are 6 periods long, so a 0.10 SEK band is loose enough
    # to hide a real per-period mismodel -- it did exactly that for #497, whose
    # phantom export runs ~0.03 SEK/period. The corpus-wide pin in
    # test_realized_matches_planned_across_all_fixtures is what actually
    # constrains this; these two stay as a fast, readable smoke check.
    GRID_RESOLUTION_TOLERANCE = 0.10  # SEK, for these short scenarios
    for name, sc in scenarios.items():
        result, realized = run_scenario_realized(sc)
        planned = result.economic_summary.battery_solar_cost
        assert abs(realized - planned) <= GRID_RESOLUTION_TOLERANCE, (
            f"{name}: R={realized:.4f} != P={planned:.4f} "
            f"(gap {realized - planned:+.4f} exceeds grid-resolution tolerance)"
        )


# Executing an optimizer plan must cost exactly what the optimizer said it
# would. Not "within a tolerance" -- exactly.
#
# This was a 33-entry table of per-fixture gaps when it was written, totalling
# 3.57 SEK of predicted savings the hardware could not deliver. #497 removed
# the cause: the DP no longer proposes discharges the inverter cannot execute
# as commanded, so there is nothing left for execution to diverge from and the
# table collapsed to a single equality. Any future gap is a real finding, and
# there is no band for one to hide in.
PLAN_EXECUTION_TOLERANCE_SEK = 0.001  # float-accumulation slack only

# The one surviving pinned gap, with a cause distinct from #497 (see TODO.md's
# "From #502" entry): #507 stopped the *plan* charging the honest price for
# periods BSM will curtail to zero at runtime, but the inverter simulator has
# no model of PV export-limit curtailment, so *execution* still pays it. On
# main this fixture pinned +0.0693 (that #502 share plus #497's +0.0490
# phantom-export share); #497's fix removed its share, leaving exactly the
# simulator's curtailment blindness. Goes to zero when the simulator learns
# curtailment -- delete the entry then.
KNOWN_PLAN_EXECUTION_GAP_SEK = {
    # #502: simulator can't curtail. Re-measured at #512's finer grid (the
    # curtailment-affected export volume shifts slightly with the plan);
    # was +0.0203 under the 0.2 kW / 0.05 kWh grid.
    "regression_2026_08_08_143843": +0.0214,
    # `regression_2026_08_17_624`'s +0.0016 entry lived here between #629 and
    # #630 and is now gone: that fixture's gap is +0.000000. The cause was not
    # the SOE-grid snapping this entry described -- the forward replay carries
    # continuous SoE, and period 32's SoE was held bit-exactly, which snapping
    # would not produce. The DP was choosing the SOLAR_EXPORT-below-max bypass
    # (#313) for a surplus too small to classify SOLAR_EXPORT, so the derived
    # IDLE command absorbed what the plan exported. See
    # `_solar_export_bypass_is_unexecutable` and
    # `test_subfloor_solar_export_is_never_planned` below (#630).
}


@pytest.mark.slow
def test_realized_matches_planned_across_all_fixtures():
    """R == P exactly, on every fixture in the corpus.

    `test_scenarios_are_plan_faithful_realized_equals_planned` above checks two
    hand-built 6-period scenarios under a 0.10 SEK band -- loose enough that a
    systematic per-period mismodel passes unnoticed, which is how #497 survived
    for months. This runs the same comparison over every fixture in
    `core/bess/tests/unit/data`, with no per-fixture exemptions: a new fixture
    is covered the moment it is added, and cannot be quietly excluded.
    """
    from core.bess.tests.helpers import run_scenario_realized
    from core.bess.tests.unit.test_scenarios import (
        get_all_scenario_files,
        load_test_scenario,
    )

    gaps = []
    for name in sorted(get_all_scenario_files()):
        result, realized = run_scenario_realized(load_test_scenario(name))
        planned = result.economic_summary.battery_solar_cost
        expected = KNOWN_PLAN_EXECUTION_GAP_SEK.get(name, 0.0)
        if abs((realized - planned) - expected) > PLAN_EXECUTION_TOLERANCE_SEK:
            gaps.append(
                f"  {name}: R={realized:.4f} P={planned:.4f} "
                f"(gap {realized - planned:+.4f} SEK, expected {expected:+.4f})"
            )

    assert not gaps, (
        f"{len(gaps)} fixture(s) plan a cost their own execution does not "
        f"reproduce. The optimizer is predicting savings the hardware cannot "
        f"deliver:\n" + "\n".join(gaps)
    )


def test_subfloor_solar_export_is_never_planned():
    """Regression for issue #630.

    The DP offers a "hold SoE, export this period's own solar surplus"
    candidate (the SOLAR_EXPORT-below-max bypass, #313). It is only executable
    where `classify_strategic_intent` will actually label the period
    SOLAR_EXPORT, because that intent is what writes charge rate 0 and stops
    the inverter absorbing the surplus. Below the classifier's
    `FLOW_NOISE_FLOOR_KWH`, the period falls through to IDLE instead, whose
    command is `load_first` at charge rate 100 -- so the plan books export
    revenue on energy the hardware puts in the battery. Same shape as #282 on
    the discharge side, which `_residual_cover_p` already gates against.

    The scenario is built to make the bypass the DP's honest choice, so the
    plan is wrong for a real economic reason rather than by accident:

    - period 0's surplus is 0.0099 kWh, just under the 0.01 kWh floor
    - periods 1-2 carry enough surplus to fill the battery to `max_soe`
      regardless, so the marginal value of storing period 0's surplus is only
      the export it displaces later (sell 0.2), not its evening value
    - selling it now at 0.5 therefore beats storing it, by more than the
      cycle cost
    - a larger discharge-and-refill at period 0 is unprofitable
      (0.5 sell - 0.4 cycle - 0.2 displaced export < 0), so the DP has no
      reason to reach for a discharge candidate instead

    `terminal_value_per_kwh` is pinned to 0.0 so the leftover-SoE term cannot
    quietly change which candidate wins as prices are tuned.

    Measured on the pre-fix code: R=2.404206 P=2.401236, gap +0.002970 SEK --
    three times `PLAN_EXECUTION_TOLERANCE_SEK`.
    """
    from core.bess.tests.helpers import run_scenario_realized

    scenario = {
        "buy_price": [1.2, 1.2, 1.2, 3.0, 3.0, 3.0],
        "sell_price": [0.5, 0.2, 0.2, 0.2, 0.2, 0.2],
        "solar_production": [0.5099, 2.0, 2.0, 0.0, 0.0, 0.0],
        "home_consumption": [0.5, 0.5, 0.5, 6.0, 6.0, 6.0],
        "battery": {
            "max_soe_kwh": 20.0,
            "min_soe_kwh": 2.2,
            "max_charge_power_kw": 10.0,
            "max_discharge_power_kw": 10.0,
            "efficiency_charge": 0.97,
            "efficiency_discharge": 0.97,
            "cycle_cost_per_kwh": 0.40,
            "initial_soe": 19.0,
        },
    }

    result, realized = run_scenario_realized(scenario)
    planned = result.economic_summary.battery_solar_cost

    # The outcome that matters: executing this plan costs what it said it would.
    assert abs(realized - planned) <= PLAN_EXECUTION_TOLERANCE_SEK, (
        f"plan books a cost its own execution does not reproduce: "
        f"R={realized:.6f} P={planned:.6f} gap={realized - planned:+.6f}"
    )

    # The mechanism, so a future regression is diagnosable and not just red:
    # period 0 must absorb its sub-floor surplus, because that is what the
    # command derived for it does.
    p0 = result.period_data[0].energy
    assert p0.grid_exported == pytest.approx(0.0, abs=1e-9), (
        f"period 0 plans a {p0.grid_exported:.5f} kWh export below the "
        f"classifier's noise floor -- the derived command absorbs it instead"
    )


def _battery(initial_soe):
    return {
        "max_soe_kwh": 20.0,
        "min_soe_kwh": 2.2,
        "max_charge_power_kw": 10.0,
        "max_discharge_power_kw": 10.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "cycle_cost_per_kwh": 0.40,
        "initial_soe": initial_soe,
    }


def test_below_min_soe_charges_from_real_solar_instead_of_holding_at_negative_price():
    """Regression for issue #269 (Frank-Leysen, 2026-07-25 ~09:02 CEST, v9.9.0b23,
    Growatt MOD 5000TL3-XH GEN4). Values below are read verbatim from the
    optimizer's own `input_data` in his debug bundle
    (bess-debug-2026-07-25-090230.md), the full 60-period (15h) horizon of the
    latest run (2026-07-25 09:00-24:00 CEST): SOE starts at 1.65 kWh, below
    `min_soe_kwh=1.8`, with real solar surplus in the morning and a negative
    sell price for the first 36 periods, followed by a clearly profitable
    evening price window (buy up to 0.394, sell up to 0.161 EUR/kWh) that
    makes an early-charged battery valuable later in the horizon.

    Before the fix, `_idle_battery_flows` (and the vectorized IDLE branch in
    `_compute_reward_grid`) zeroed the real charging credit for any period
    starting below `min_soe_kwh`, while the wear-cost term still charged the
    real SOE delta -- making genuine solar-charging look artificially
    unprofitable. SOE stayed pinned at 1.65 kWh for periods 0-8 despite free
    solar and a negative sell price throughout, only starting to rise once
    the DP's own bookkeeping (elsewhere) inconsistently let it through --
    exactly what the reporter observed (SOLAR_EXPORT at 11% SOC, 0% charge
    rate, sell price negative). After the fix, charging starts immediately.
    """
    from core.bess.dp_battery_algorithm import optimize_battery_schedule
    from core.bess.settings import BatterySettings
    from core.bess.simulation.inverter_simulator import derive_control_command, simulate

    buy_price = [
        0.221830,
        0.221830,
        0.221830,
        0.221830,
        0.209751,
        0.209751,
        0.209751,
        0.209751,
        0.207065,
        0.207065,
        0.207065,
        0.207065,
        0.203452,
        0.203452,
        0.203452,
        0.203452,
        0.199418,
        0.199418,
        0.199418,
        0.199418,
        0.215262,
        0.215262,
        0.215262,
        0.215262,
        0.207723,
        0.207723,
        0.207723,
        0.207723,
        0.209654,
        0.209654,
        0.209654,
        0.209654,
        0.221367,
        0.221367,
        0.221367,
        0.221367,
        0.310994,
        0.310994,
        0.310994,
        0.310994,
        0.378145,
        0.378145,
        0.378145,
        0.378145,
        0.393805,
        0.393805,
        0.393805,
        0.393805,
        0.392155,
        0.392155,
        0.392155,
        0.392155,
        0.388358,
        0.388358,
        0.388358,
        0.388358,
        0.382448,
        0.382448,
        0.382448,
        0.382448,
    ]
    sell_price = [
        -0.001406,
        -0.001406,
        -0.001406,
        -0.001406,
        -0.012807,
        -0.012807,
        -0.012807,
        -0.012807,
        -0.015342,
        -0.015342,
        -0.015342,
        -0.015342,
        -0.018752,
        -0.018752,
        -0.018752,
        -0.018752,
        -0.022560,
        -0.022560,
        -0.022560,
        -0.022560,
        -0.007605,
        -0.007605,
        -0.007605,
        -0.007605,
        -0.014721,
        -0.014721,
        -0.014721,
        -0.014721,
        -0.012899,
        -0.012899,
        -0.012899,
        -0.012899,
        -0.001843,
        -0.001843,
        -0.001843,
        -0.001843,
        0.082753,
        0.082753,
        0.082753,
        0.082753,
        0.146133,
        0.146133,
        0.146133,
        0.146133,
        0.160915,
        0.160915,
        0.160915,
        0.160915,
        0.159357,
        0.159357,
        0.159357,
        0.159357,
        0.155774,
        0.155774,
        0.155774,
        0.155774,
        0.150195,
        0.150195,
        0.150195,
        0.150195,
    ]
    home_consumption = [
        0.135000,
        0.135000,
        0.135000,
        0.135000,
        0.200000,
        0.200000,
        0.200000,
        0.200000,
        0.165000,
        0.165000,
        0.165000,
        0.165000,
        0.150000,
        0.150000,
        0.150000,
        0.150000,
        0.170000,
        0.170000,
        0.170000,
        0.170000,
        0.210000,
        0.210000,
        0.210000,
        0.210000,
        0.245000,
        0.245000,
        0.245000,
        0.245000,
        0.230000,
        0.230000,
        0.230000,
        0.230000,
        0.215000,
        0.215000,
        0.215000,
        0.215000,
        0.220000,
        0.220000,
        0.220000,
        0.220000,
        0.185000,
        0.185000,
        0.185000,
        0.185000,
        0.175000,
        0.175000,
        0.175000,
        0.175000,
        0.175000,
        0.175000,
        0.175000,
        0.175000,
        0.145000,
        0.145000,
        0.145000,
        0.145000,
        0.105000,
        0.105000,
        0.105000,
        0.105000,
    ]
    solar_production = [
        0.518850,
        0.518850,
        0.518850,
        0.518850,
        0.646525,
        0.646525,
        0.646525,
        0.646525,
        0.766500,
        0.766500,
        0.766500,
        0.766500,
        0.841175,
        0.841175,
        0.841175,
        0.841175,
        0.787525,
        0.787525,
        0.787525,
        0.787525,
        0.679750,
        0.679750,
        0.679750,
        0.679750,
        0.668000,
        0.668000,
        0.668000,
        0.668000,
        0.664400,
        0.664400,
        0.664400,
        0.664400,
        0.589475,
        0.589475,
        0.589475,
        0.589475,
        0.449925,
        0.449925,
        0.449925,
        0.449925,
        0.277025,
        0.277025,
        0.277025,
        0.277025,
        0.117725,
        0.117725,
        0.117725,
        0.117725,
        0.009350,
        0.009350,
        0.009350,
        0.009350,
        0.000000,
        0.000000,
        0.000000,
        0.000000,
        0.000000,
        0.000000,
        0.000000,
        0.000000,
    ]
    initial_soe = 1.65
    initial_cost_basis = 0.035
    dt = 0.25
    bs = BatterySettings(
        total_capacity=15,
        min_soc=12,
        max_soc=100,
        max_charge_power_kw=5,
        max_discharge_power_kw=5,
        charging_power_rate=40,
        cycle_cost_per_kwh=0.035,
        efficiency_charge=0.97,
        efficiency_discharge=0.95,
        inverter_max_ac_power_kw=0,
        inverter_ac_power_margin=0.05,
    )
    assert bs.min_soe_kwh == pytest.approx(1.8)

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        initial_cost_basis=initial_cost_basis,
        battery_settings=bs,
        period_duration_hours=dt,
    )

    # Below min_soe_kwh with real solar surplus every period, storing costs
    # only wear (0.035 EUR/kWh); the DP should recognize that and put real
    # energy into the battery well before the crossover the bug produced
    # (previously stuck flat at 1.65 kWh through period 8 / #269 comment).
    total_charged_first_20 = sum(
        pd.energy.battery_charged for pd in result.period_data[:20]
    )
    assert total_charged_first_20 > 5.0, (
        "optimizer should charge substantially from the available real solar "
        "surplus while below min_soe_kwh instead of holding-and-exporting at a "
        f"negative sell price; got total_charged={total_charged_first_20:.3f} kWh "
        "over the first 20 periods"
    )
    soe_above_floor = next(
        (pd for pd in result.period_data if pd.energy.battery_soe_end > bs.min_soe_kwh),
        None,
    )
    assert soe_above_floor is not None and soe_above_floor.period <= 4, (
        "SOE should recover above min_soe_kwh within the first few periods given "
        f"real solar surplus every period; recovered at period "
        f"{soe_above_floor.period if soe_above_floor else 'never'}"
    )

    # Exercise the real DP-produced schedule through the inverter simulator
    # (not a hand-built command sequence) so this also proves the plan the
    # fix produces is faithfully executable, per docs/agents/simulator.md.
    commands = [
        derive_control_command(
            pd.decision.strategic_intent, pd.decision.battery_action / dt, bs
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands,
        solar_production,
        home_consumption,
        buy_price,
        sell_price,
        initial_soe,
        bs,
        dt,
    )
    assert sim.realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=0.05
    ), f"R={sim.realized_cost} != P={result.economic_summary.battery_solar_cost}"


def test_load_support_self_throttles_discretization_overshoot():
    """#240 regression: load-first hardware never exports a discharge that
    overshoots home_consumption -- it self-throttles to the actual deficit,
    regardless of what a coarser discretized plan might have assumed. This
    locks in the physical behavior the DP now accounts for by excluding
    such discharges from its action set outright (#497,
    core/bess/action_selector.py's _discharge_is_unexecutable; the
    earlier #240 fix instead zeroed the export credit in _compute_reward):
    before that, the plan credited export revenue for energy that was
    never actually exported, breaking R == P for these periods -- a case
    the existing hand-crafted plan-faithfulness scenarios were deliberately
    designed to avoid (see their own docstrings), so nothing else covers it.
    """
    from core.bess.simulation.inverter_simulator import ControlCommand, simulate

    bs = make_battery_settings()
    home = 1.15
    solar = 0.0
    cmd = ControlCommand("load_first", discharge_rate_pct=100, grid_charge=False)
    sim = simulate(
        [cmd],
        solar_production=[solar],
        home_consumption=[home],
        buy_price=[1.0],
        sell_price=[1.0],
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    assert sim.period_data[0].energy.grid_exported == pytest.approx(0.0, abs=1e-9), (
        "load_first should never export -- it self-throttles to the actual "
        "home deficit, matching the #240-fixed reward model's assumption"
    )
