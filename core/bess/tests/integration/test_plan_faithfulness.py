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


# Per-fixture gap between what executing the plan actually costs (R, via the
# inverter simulator) and what the optimizer predicted it would cost (P), in
# SEK. Measured on 2026-08-08 at 18bccae4.
#
# A nonzero entry means the optimizer's predicted savings for that day are
# wrong by that amount -- it is a defect budget, not a target. Almost all of
# the positive mass is #497 (the plan books export revenue that load-following
# hardware never earns, so R comes out more expensive than P). The one negative
# entry runs the other way and has a different, still-undiagnosed cause.
#
# Regenerate deliberately, never reflexively: a shrinking number is a fix, a
# growing one is a regression, and either way the diff that moved it should say
# why in its description.
PLAN_EXECUTION_GAP_SEK = {
    "historical_2024_08_16_high_spread_no_solar": -0.0330,
    "historical_2025_01_05_no_spread_no_solar": +0.0000,
    "historical_2025_01_12_evening_peak_no_solar": +0.0658,
    "historical_2025_01_13_night_low_no_solar": +0.0236,
    "historical_2025_06_02_high_solar_export": +0.1495,
    "realworld_2026_03_24_225535": +0.0000,
    "realworld_2026_04_11_004719": +0.0055,
    "realworld_2026_04_19_084608": +0.0000,
    "realworld_2026_04_22_202249": +0.0401,
    "realworld_2026_04_24_090423": +0.0270,
    "realworld_2026_04_27_184643": +0.0000,
    "realworld_2026_04_27_211212": +0.7313,
    "realworld_2026_04_29_195900": +0.0443,
    "realworld_2026_04_29_220919": +0.5591,
    "realworld_2026_07_13_155212": +0.0326,
    "regression_2026_07_25_090230": +0.0139,
    "regression_2026_07_26_203726": +0.0255,
    "regression_2026_08_02_043728": +0.0894,
    "regression_2026_08_06_466": +0.0033,
    "regression_frank_debug_before": +0.0453,
    "synthetic_2024_08_16_high_spread_with_solar": +0.0000,
    "synthetic_2025_01_12_evening_peak_with_solar": +0.2408,
    "synthetic_clear_sky_ac_clipping": +0.1945,
    "synthetic_consumption_efficient": +0.1499,
    "synthetic_consumption_ev_charging": +0.4498,
    "synthetic_consumption_high_no_solar": +0.0000,
    "synthetic_extreme_negative_prices": +0.0000,
    "synthetic_extreme_volatility": +0.0000,
    "synthetic_historical_2024_08_16_high_spread_with_solar": +0.0000,
    "synthetic_historical_2025_01_12_evening_peak_with_solar": +0.0000,
    "synthetic_seasonal_spring": +0.0000,
    "synthetic_seasonal_summer": +0.1939,
    "synthetic_seasonal_winter": +0.4498,
}

# Enough slack to absorb float jitter, far below the smallest gap that means
# anything (0.0033 SEK) -- so a real movement in any fixture still fails.
GAP_PIN_TOLERANCE_SEK = 0.001


@pytest.mark.slow
def test_realized_matches_planned_across_all_fixtures():
    """Pin R-vs-P per fixture across the whole corpus.

    ``test_scenarios_are_plan_faithful_realized_equals_planned`` above checks
    two hand-built 6-period scenarios under a 0.10 SEK band, which is loose
    enough that a systematic per-period mismodel passes unnoticed -- #497 lived
    there for months. This runs the same R-vs-P comparison over every fixture
    in ``core/bess/tests/unit/data`` and pins each result, so any change to the
    optimizer's economics has to account for its effect on plan faithfulness
    explicitly.
    """
    from core.bess.tests.helpers import run_scenario_realized
    from core.bess.tests.unit.test_scenarios import (
        get_all_scenario_files,
        load_test_scenario,
    )

    discovered = set(get_all_scenario_files())
    pinned = set(PLAN_EXECUTION_GAP_SEK)
    assert discovered == pinned, (
        "Fixture corpus and the pinned gap table have drifted apart. Added "
        f"fixtures with no pin: {sorted(discovered - pinned)}. Pinned entries "
        f"with no fixture: {sorted(pinned - discovered)}. A new fixture must "
        "record its own plan-execution gap -- silently exempting it is how a "
        "mismodel gets in unmeasured."
    )

    drifted = []
    for name in sorted(discovered):
        result, realized = run_scenario_realized(load_test_scenario(name))
        planned = result.economic_summary.battery_solar_cost
        gap = realized - planned
        expected = PLAN_EXECUTION_GAP_SEK[name]
        if abs(gap - expected) > GAP_PIN_TOLERANCE_SEK:
            drifted.append(
                f"  {name}: gap {gap:+.4f} SEK, pinned {expected:+.4f} "
                f"(moved {gap - expected:+.4f})"
            )

    assert not drifted, (
        "Plan-execution gap moved on "
        f"{len(drifted)} fixture(s).\n"
        "Toward zero means plan faithfulness improved -- update the pin and say "
        "so in the PR. Away from zero means the optimizer now predicts savings "
        "it cannot deliver.\n" + "\n".join(drifted)
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
    locks in the physical behavior the #240 reward-model fix
    (core/bess/dp_battery_algorithm.py's _compute_reward) now assumes:
    before that fix, the plan credited export revenue for energy that was
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
