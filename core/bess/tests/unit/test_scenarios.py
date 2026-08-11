"""
Test module for running tests with scenario files (DP-based, canonical for BESS).

This module contains tests that run the battery optimization algorithm on various
scenario files. These tests ensure the algorithm can process scenario files and
produce reasonable outputs.
"""

import json
import logging
import os
from pathlib import Path

import pytest

from core.bess.dp_battery_algorithm import (
    optimize_battery_schedule,
    print_optimization_results,
)
from core.bess.models import EconomicSummary, PeriodData
from core.bess.tests.helpers import (
    _scenario_inputs,
    assert_flow_coherence,
    assert_intent_absent,
    assert_intent_at_hour,
    assert_intent_present,
    assert_physical_constraints,
    assert_savings_positive,
    get_intent_distribution,
)

pytestmark = pytest.mark.slow

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_test_scenario(scenario_name):
    file_path = os.path.join(os.path.dirname(__file__), "data", f"{scenario_name}.json")
    with open(file_path) as f:
        scenario = json.load(f)
    return scenario


def get_all_scenario_files():
    """Get all scenario files from the data directory."""
    data_dir = Path(__file__).parent / "data"
    scenario_files = []

    if data_dir.exists():
        for file_path in data_dir.glob("*.json"):
            scenario_files.append(file_path.stem)  # filename without extension

    return sorted(scenario_files)


def build_scenario_inputs(scenario_name):
    """Load a scenario file and derive battery settings + buy/sell prices.

    Thin wrapper around helpers._scenario_inputs so every consumer of
    scenario files (this module and its several importers) shares one
    derivation path -- including the buy_price/sell_price direct-input and
    spot_multiplier handling added for debug-log-derived regression
    fixtures.
    """
    scenario = load_test_scenario(scenario_name)
    inputs = _scenario_inputs(scenario)
    return (
        scenario,
        inputs["battery_settings"],
        inputs["buy_price"],
        inputs["sell_price"],
        inputs["period_duration_hours"],
    )


def test_build_scenario_inputs_matches_shared_scenario_inputs_directly():
    """Safety net for delegating build_scenario_inputs to the shared
    helpers._scenario_inputs (#269 follow-up, avoids the two copies of this
    logic drifting apart again -- see
    docs/superpowers/specs/2026-07-25-debug-log-regression-fixtures-design.md):
    output must be identical to calling the shared helper directly, for a
    real existing fixture."""
    from core.bess.tests.helpers import _scenario_inputs

    scenario, battery_settings, buy_prices, sell_prices, dt = build_scenario_inputs(
        "realworld_2026_03_24_225535"
    )
    expected = _scenario_inputs(scenario)

    assert buy_prices == expected["buy_price"]
    assert sell_prices == expected["sell_price"]
    assert dt == expected["period_duration_hours"]
    assert battery_settings.max_soe_kwh == expected["battery_settings"].max_soe_kwh
    assert battery_settings.min_soe_kwh == expected["battery_settings"].min_soe_kwh


@pytest.mark.parametrize("scenario_name", get_all_scenario_files())
def test_all_scenarios(scenario_name):
    """Test all scenario files with the battery optimization algorithm."""
    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs(scenario_name)
    )
    home_consumption = scenario["home_consumption"]
    solar_production = scenario["solar_production"]
    battery = scenario["battery"]

    # Determine the actual horizon from the scenario data -- use the
    # derived buy_prices (always present) rather than base_prices (only
    # present for non-regression fixtures using the markup-config path).
    horizon = len(buy_prices)

    # Validate that all arrays have the same length
    assert (
        len(home_consumption) == horizon
    ), f"home_consumption length {len(home_consumption)} != base_prices length {horizon}"
    assert (
        len(solar_production) == horizon
    ), f"solar_production length {len(solar_production)} != base_prices length {horizon}"

    # Run optimization.
    #
    # Pass `_scenario_inputs` through whole rather than re-listing keys
    # (changed 2026-08-11). Re-listing dropped three inputs the fixtures
    # actually set: `export_curtailment_active`, `initial_cost_basis` and
    # `home_settings`. That is the same defect `golden_capture.py` was fixed
    # for in Phase 1 -- its docstring even names the fixture -- and it was
    # left standing here, so the corpus's own canonical suite kept replaying
    # a different solve than the goldens did.
    #
    # It mattered most where it was least visible:
    # `regression_2026_08_08_143843` exists to pin #510's charge-early
    # tie-break *under the export-curtailment price floor*, sets
    # `export_curtailment_active: True`, and was asserted here with
    # curtailment OFF -- the one condition it was captured for.
    result = optimize_battery_schedule(**_scenario_inputs(scenario))

    # Validate results using new data structures
    assert isinstance(result.period_data, list)
    assert (
        len(result.period_data) == horizon
    )  # Use actual horizon instead of hardcoded 24
    assert isinstance(result.economic_summary, EconomicSummary)

    # Validate hourly data structure
    for i, hour_data in enumerate(result.period_data):
        assert isinstance(hour_data, PeriodData)
        assert hour_data.energy is not None
        assert hour_data.economic is not None
        assert hour_data.decision is not None
        assert hour_data.period == i  # Should match the index
        assert hour_data.data_source == "predicted"

    # Validate economic summary - use proper attribute access
    assert hasattr(result.economic_summary, "grid_only_cost")
    assert hasattr(result.economic_summary, "battery_solar_cost")
    assert hasattr(result.economic_summary, "grid_to_battery_solar_savings")
    assert result.economic_summary.grid_only_cost >= 0

    # Log results for debugging
    logger.info(f"Scenario: {scenario_name} (horizon: {horizon} hours)")
    logger.info(f"Grid-only cost: {result.economic_summary.grid_only_cost:.2f} SEK")
    logger.info(f"Optimized cost: {result.economic_summary.battery_solar_cost:.2f} SEK")
    logger.info(
        f"Savings: {result.economic_summary.grid_to_battery_solar_savings:.2f} SEK"
    )
    logger.info(
        f"Savings %: {result.economic_summary.grid_to_battery_solar_savings_pct:.1f}%"
    )

    # Print full optimization results for detailed analysis
    print_optimization_results(result, buy_prices, sell_prices)

    # Validate that the optimization is reasonable
    assert (
        result.economic_summary.grid_only_cost > 0
    ), "Grid-only cost should be positive"

    # Check if 'expected_results' exists in the test data
    if "expected_results" in scenario:
        expected_results = scenario["expected_results"]
        economic_results = result.economic_summary

        # Tolerance, not rounding to 1 decimal (changed 2026-08-11).
        #
        # `round(x, 1)` compared costs at 0.1 SEK, which is far coarser than
        # anything these fixtures actually vary by: measured across the 33
        # pinned fixtures, the median |actual - pinned| is 0.000002 SEK and 32
        # of 33 sit within 0.000005. The rounding was therefore not absorbing
        # float noise -- it was hiding whole behaviour changes. It hid a real
        # one: `regression_2026_08_08_143843` had drifted 0.0214 SEK from its
        # recorded value (an improvement, from a later grid/tie change nobody
        # re-pinned) and no test could see it.
        #
        # 0.001 SEK is ~500x the observed float spread and ~100x finer than
        # the old gate, so it stays quiet on numerical noise while a genuine
        # behavioural change has to be re-pinned deliberately -- which is the
        # point of a pin.
        COST_TOLERANCE_SEK = 0.001
        PCT_TOLERANCE = 0.01

        assert economic_results.grid_only_cost == pytest.approx(
            expected_results["base_cost"], abs=COST_TOLERANCE_SEK
        ), f"Grid-only cost mismatch: {economic_results.grid_only_cost:.6f} != {expected_results['base_cost']:.6f}"

        assert economic_results.battery_solar_cost == pytest.approx(
            expected_results["battery_solar_cost"], abs=COST_TOLERANCE_SEK
        ), f"Battery solar cost mismatch: {economic_results.battery_solar_cost:.6f} != {expected_results['battery_solar_cost']:.6f}"

        assert economic_results.grid_to_battery_solar_savings == pytest.approx(
            expected_results["base_to_battery_solar_savings"], abs=COST_TOLERANCE_SEK
        ), f"Savings mismatch: {economic_results.grid_to_battery_solar_savings:.6f} != {expected_results['base_to_battery_solar_savings']:.6f}"

        assert economic_results.grid_to_battery_solar_savings_pct == pytest.approx(
            expected_results["base_to_battery_solar_savings_pct"], abs=PCT_TOLERANCE
        ), f"Savings percentage mismatch: {economic_results.grid_to_battery_solar_savings_pct:.4f}% != {expected_results['base_to_battery_solar_savings_pct']:.4f}%"

    else:
        logger.info(
            f"No expected results for scenario {scenario_name}, skipping validation"
        )

    # Battery usage should be within physical constraints
    # Small tolerance for floating-point precision errors (e.g., np.arange producing 30.000000000000025)
    soe_tolerance = 1e-6
    # A scenario may legitimately start below min_soe_kwh (e.g. a live sensor
    # reading under Min SOC, see dp_battery_algorithm.py's _soe_floor()
    # docstring, #233) -- the effective lower bound is the fixture's own
    # starting point in that case, not the configured floor. For every
    # fixture that starts at/above its floor (all of them until #269's
    # regression_2026_07_25_090230), this is identical to min_soe_kwh --
    # zero behavior change.
    effective_min_soe_kwh = min(battery["min_soe_kwh"], battery["initial_soe"])
    for hour_data in result.period_data:
        # Access SOE directly - these are already in kWh
        soe_start_kwh = hour_data.energy.battery_soe_start  # Already in kWh
        soe_end_kwh = hour_data.energy.battery_soe_end  # Already in kWh

        # Validate SOE bounds in kWh (with tolerance for floating-point precision)
        assert (
            effective_min_soe_kwh - soe_tolerance
            <= soe_start_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE start {soe_start_kwh:.2f} kWh outside bounds [{effective_min_soe_kwh}, {battery['max_soe_kwh']}]"
        assert (
            effective_min_soe_kwh - soe_tolerance
            <= soe_end_kwh
            <= battery["max_soe_kwh"] + soe_tolerance
        ), f"SOE end {soe_end_kwh:.2f} kWh outside bounds [{effective_min_soe_kwh}, {battery['max_soe_kwh']}]"

        # Battery action should respect power limits - access through strategy field
        battery_action = hour_data.decision.battery_action
        if (
            battery_action and abs(battery_action) > 0.01
        ):  # Allow for small numerical errors
            # Add small tolerance for floating-point precision errors
            tolerance = 1e-10
            if battery_action > 0:  # Charging (positive)
                assert (
                    battery_action <= battery["max_charge_power_kw"] + tolerance
                ), f"Battery charging action {battery_action:.2f} kW exceeds max charge power {battery['max_charge_power_kw']} kW"
            else:  # Discharging (negative)
                assert (
                    abs(battery_action) <= battery["max_discharge_power_kw"] + tolerance
                ), f"Battery discharging action {abs(battery_action):.2f} kW exceeds max discharge power {battery['max_discharge_power_kw']} kW"

    # ── Flow coherence (unconditional) ──
    # Not gated on expected_behavior. Whether a period's flows add up is not a
    # per-fixture expectation a scenario author opts into -- it holds for every
    # plan or the plan is wrong. Gating it the way soe_within_bounds is gated
    # would silently exempt the three fixtures that declare no constraints
    # block, which is exactly the kind of hole this check exists to close.
    for pd in result.period_data:
        assert_flow_coherence(pd)

    # ── Behavioral assertions (from expected_behavior in scenario JSON) ──
    if "expected_behavior" in scenario:
        behavior = scenario["expected_behavior"]
        dist = get_intent_distribution(result)
        logger.info(f"Intent distribution: {dist}")

        for intent in behavior.get("intents_present", []):
            assert_intent_present(result, intent)

        for intent in behavior.get("intents_absent", []):
            assert_intent_absent(result, intent)

        if behavior.get("savings_positive"):
            assert_savings_positive(result)

        if behavior.get("constraints", {}).get("soe_within_bounds"):
            assert_physical_constraints(result, battery)
    else:
        logger.info(
            f"No expected_behavior for scenario {scenario_name}, skipping behavioral validation"
        )

    # ── Plan-faithfulness: R == P (#145) ──
    # Executing the optimizer's plan through the inverter simulator must reproduce
    # the planned economics within the DP's SoE/power-grid resolution. A larger gap
    # is a control-fidelity finding, not just discretization.
    from core.bess.simulation.inverter_simulator import (
        derive_control_command,
        simulate,
    )

    commands = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / period_duration_hours,
            battery_settings,
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands,
        solar_production,
        home_consumption,
        buy_prices,
        sell_prices,
        battery["initial_soe"],
        battery_settings,
        period_duration_hours,
    )
    planned_cost = result.economic_summary.battery_solar_cost
    gap = sim.realized_cost - planned_cost

    tol = max(0.5, 0.01 * abs(planned_cost))
    assert abs(gap) <= tol, (
        f"{scenario_name}: realized != planned — R={sim.realized_cost:.2f}, "
        f"P={planned_cost:.2f}, gap {gap:+.3f} SEK exceeds tolerance {tol:.2f}"
    )


def test_hybrid_wiring_is_no_op_when_no_ties_detected(caplog):
    """A fixture with no near-tied periods must produce output identical to
    what the grid DP alone produced -- this is the core latency and
    stability guarantee of the hybrid design (#450): when detect_tie_windows
    returns nothing, none of the PWL machinery runs and the pinned
    expected_results below stay exactly as they were before the wiring.

    Fixture swapped from synthetic_consumption_efficient after the tie
    detector's recalibration (#450): that fixture does now flag one window
    (a no-op resolve), so it no longer exercises the fast path. This one
    flags none, and the pinned values below are the grid DP's own output."""

    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs("synthetic_consumption_ev_charging")
    )
    with caplog.at_level(logging.INFO, logger="core.bess.dp_battery_algorithm"):
        result = optimize_battery_schedule(
            buy_price=buy_prices,
            sell_price=sell_prices,
            home_consumption=scenario["home_consumption"],
            solar_production=scenario["solar_production"],
            initial_soe=scenario["battery"]["initial_soe"],
            battery_settings=battery_settings,
            period_duration_hours=period_duration_hours,
        )

    # Pinned costs alone would keep passing if the detector drifted and this
    # fixture started resolving windows that happen to be no-ops -- which is
    # exactly what happened to the fixture this test used to use. Assert the
    # fast path was actually taken, not just that the numbers came out right.
    assert not [
        r for r in caplog.records if "Near-tied DP decisions detected" in r.getMessage()
    ], "fixture now trips the tie detector -- it no longer exercises the fast path"

    assert result.economic_summary.battery_solar_cost == pytest.approx(
        158.2466715789474, abs=1e-4
    )
    assert result.economic_summary.grid_to_battery_solar_savings == pytest.approx(
        62.8678, abs=1e-3
    )


def test_466_near_tied_evening_periods_discharge_instead_of_idle():
    """Replays the exact optimizer input recorded in #466's debug bundle
    (bess-debug-2026-08-06-110152.md, run at optimization_period 44, horizon
    52 starting 11:00). Pre-fix, periods 32 (19:00, buy 0.7235/sell 0.2419)
    and 45 (22:15, buy 0.6683/sell 0.1977) sat IDLE despite ~0.1675 kWh of
    home load and a clearly profitable discharge spread -- a near-tied DP
    decision resolved toward the "do nothing" action. The risk-aware
    load-covering tie-break (#466) should now prefer LOAD_SUPPORT at both.

    Reproduction was verified against the bundle: replaying this same input
    through the pre-fix source (commit c1013fe9) reproduces the bundle's own
    reported economics exactly (grid_only_cost 5.764893562499999,
    battery_solar_cost -2.094315584625) with periods 32 and 45 IDLE."""

    scenario, battery_settings, buy_prices, sell_prices, period_duration_hours = (
        build_scenario_inputs("regression_2026_08_06_466")
    )
    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=scenario["battery"]["initial_soe"],
        initial_cost_basis=scenario["battery"]["initial_cost_basis"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
    )

    assert_intent_at_hour(result, 45, "LOAD_SUPPORT")  # 22:15

    # Period 32 (19:00) tracks the grid resolution, correctly each time
    # (same story as test_idle_tie_break's guardrail test): IDLE under #497's
    # rule at the 0.2 kW grid because its 0.0431 kWh deficit sat below the
    # smallest commandable discharge (0.05 kWh), back to LOAD_SUPPORT at
    # #512's finer grid, whose halved classification threshold makes a
    # smaller under-covering discharge commandable and executable exactly as
    # planned. Realized cost on this fixture improved 0.0181 SEK at the
    # finer grid, with R == P still exact.
    assert_intent_at_hour(result, 32, "LOAD_SUPPORT")  # 19:00

    expected = scenario["expected_results"]
    assert result.economic_summary.battery_solar_cost == pytest.approx(
        expected["battery_solar_cost"], abs=1e-3
    )


def test_466_sunrise_crossover_covers_residual_load_instead_of_idle():
    """Replays the exact optimizer input recorded in #466's second debug
    bundle (bess-debug-2026-08-07-232503.md, run at optimization_period 93,
    horizon 99 starting 23:15). The sunrise-crossover periods 27-30
    (06:00-06:45) forecast solar 0.1461 kWh against home 0.1675 kWh -- an
    ~86 W residual, below the smallest discharge the percent lattice can
    command even at #512's finer grid (0.1 kW). Pre-fix those periods sat
    IDLE and imported the residual at ~0.64 SEK/kWh while the battery held
    4.34 kWh above reserve at a local shadow price of ~0.55 -- i.e. the
    DP's own economics said covering it was cheaper (buy * eta_discharge =
    0.607 > 0.549), but no executable action expressed it: sub-residual
    lattice candidates do not exist, and every overshooting one is removed
    by #497's executable-only rule.

    Post-fix the residual-cover candidate (discharge exactly the forecast
    net load, no export) is in the action space, so these periods plan
    LOAD_SUPPORT with zero grid flows. Executability is asserted per
    period rather than assumed: load-first delivers min(actual load,
    ceiling), which at forecast equals the planned residual exactly, so
    R == P holds to numerical noise -- the invariant #282/#497 exist to
    protect and the reason this candidate plans a delivery rather than a
    rate-step command."""
    from core.bess.simulation.inverter_simulator import (
        derive_control_command,
        simulate,
    )

    scenario = load_test_scenario("regression_bess_debug_2026_08_07")
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)
    dt = inp["period_duration_hours"]
    commands = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / dt,
            inp["battery_settings"],
            intra_period_discharge_allowed=pd.decision.intra_period_discharge_allowed,
        )
        for pd in result.period_data
    ]
    sim = simulate(
        commands,
        inp["solar_production"],
        inp["home_consumption"],
        inp["buy_price"],
        inp["sell_price"],
        scenario["battery"]["initial_soe"],
        inp["battery_settings"],
        dt,
    )

    for t in range(27, 31):  # 06:00, 06:15, 06:30, 06:45
        assert_intent_at_hour(result, t, "LOAD_SUPPORT")
        pd = result.period_data[t]
        assert pd.energy.grid_imported == pytest.approx(0.0, abs=1e-6), (
            f"period {t}: expected residual fully covered from battery, "
            f"got grid import {pd.energy.grid_imported:.4f} kWh"
        )
        assert pd.energy.grid_exported == pytest.approx(0.0, abs=1e-6), (
            f"period {t}: residual-cover must not export, "
            f"got {pd.energy.grid_exported:.4f} kWh"
        )
        # Executed exactly as planned (R == P per period).
        rp = sim.period_data[t]
        assert rp.decision.battery_action == pytest.approx(
            pd.decision.battery_action, abs=1e-6
        ), (
            f"period {t}: simulator delivered {rp.decision.battery_action:.4f} "
            f"kWh vs planned {pd.decision.battery_action:.4f} kWh"
        )
        assert rp.economic.hourly_cost == pytest.approx(
            pd.economic.hourly_cost, abs=1e-6
        )

    # Whole-horizon R == P: the cover candidate plans delivery, not a
    # rate-step command, so execution reproduces the planned economics.
    assert sim.realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=1e-6
    )
