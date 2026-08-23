"""
Test module for running tests with scenario files (DP-based, canonical for BESS).

This module contains tests that run the battery optimization algorithm on various
scenario files. These tests ensure the algorithm can process scenario files and
produce reasonable outputs.
"""

import json
import logging
import math
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
    assert_intent_at_hour,
    assert_physical_constraints,
    assert_savings_positive,
    get_intent_distribution,
    scenario_terminal_curve,
)

pytestmark = pytest.mark.slow

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_every_fixture_declares_a_terminal_value():
    """A fixture without an explicit terminal value silently runs the DP at 0.0.

    `optimize_battery_schedule` defaults `terminal_value_per_kwh` to 0.0, and at
    0.0 the terminal-row branch in `dp_battery_algorithm` never executes at all
    -- `V[horizon]` stays all zeros. Every fixture here used to fall through to
    that default, so the whole pinned corpus was blind to the terminal value in
    both directions: it could neither regress it nor validate it, which is how
    #345's terminal-value fix went green without a single fixture reaching the
    code path (TODO.md).

    Measured when the corpus was retrofitted: applying #602's candidate change
    (dropping the double `cycle_cost` deduction) moves 28 of 38 fixtures, one by
    11.45 kWh of boundary SOE and 33 SEK. At the old 0.0 default it moved none.
    That gap is what this guard protects -- a fixture added without a declared
    terminal value quietly re-opens it for itself.
    """
    missing = [
        name
        for name in get_all_scenario_files()
        if "terminal_value_per_kwh" not in load_test_scenario(name)
        or "terminal_knee_kwh" not in load_test_scenario(name)
        or "terminal_tail_rate" not in load_test_scenario(name)
    ]
    assert missing == [], (
        f"fixtures without a declared terminal value: {missing}. Run "
        "`.venv/bin/python scripts/capture_scenario_terminal_values.py`."
    )


def test_recorded_terminal_values_still_match_the_production_formula():
    """A change to the terminal-value formula must reach the pinned corpus.

    Fixtures record `terminal_value_per_kwh` as an explicit number so a reader
    can see what a scenario runs at. That transparency costs something this
    test buys back: a recorded constant does not move when
    `core/bess/terminal_value.py` changes, so without this guard a formula
    change would leave all 38 fixtures replaying their old values and the
    economics pins would stay green -- the same blindness the retrofit set out
    to remove, in a new form.

    Caught by mutation, not by inspection: dropping the double `cycle_cost`
    deduction (#602's candidate change) left `test_all_scenarios` at 43 passed
    until this existed. With it, the same mutation reddens this test first,
    which forces the re-capture that then moves 28 of 38 fixtures' economics.

    A fixture that must pin a *specific* terminal value regardless of the
    formula -- because its defect lives in how that input is computed upstream
    -- does not belong in this corpus; give it a standalone test where the
    intent is visible.
    """
    stale = []
    for name in get_all_scenario_files():
        scenario = load_test_scenario(name)
        curve = scenario_terminal_curve(scenario)
        recorded = scenario["terminal_value_per_kwh"]
        recorded_knee = scenario["terminal_knee_kwh"]
        if abs(recorded - curve.head_rate) > 1e-9:
            stale.append(f"{name}: recorded={recorded} computed={curve.head_rate}")
        else:
            # A null knee records the no-PV-crossover regime, whose curve is
            # flat (an infinite knee) -- JSON has no infinity, so absence is
            # how that regime is written down.
            computed_knee = None if math.isinf(curve.knee_kwh) else curve.knee_kwh
            drifted = (recorded_knee is None) != (computed_knee is None) or (
                recorded_knee is not None
                and computed_knee is not None
                and abs(recorded_knee - computed_knee) > 1e-9
            )
            if drifted:
                stale.append(
                    f"{name}: recorded knee={recorded_knee} computed={computed_knee}"
                )
            # `tail_rate` is checked too, not just head and knee. Without it a
            # fixture can replay a curve that differs from the production one on
            # the field the reconstruction is most likely to get wrong -- it is
            # the only one with a dataclass default, so omitting it fails silent
            # rather than loud.
            elif abs(scenario["terminal_tail_rate"] - curve.tail_rate) > 1e-9:
                stale.append(
                    f"{name}: recorded tail={scenario['terminal_tail_rate']} "
                    f"computed={curve.tail_rate}"
                )

    assert stale == [], (
        "recorded terminal values no longer match the production formula:\n  "
        + "\n  ".join(stale)
        + "\nIf the formula change is deliberate, re-capture and re-pin:\n"
        "  .venv/bin/python scripts/capture_scenario_terminal_values.py\n"
        "  .venv/bin/python scripts/capture_scenario_expected_results.py\n"
        "  .venv/bin/python scripts/capture_selector_goldens.py\n"
        "  PYTHONPATH=. .venv/bin/python scripts/capture_vpp_baseline.py "
        "--repin-current"
    )


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


def build_scenario_optimizer_inputs(scenario_name):
    """Load a scenario file and return `(scenario, full optimizer kwargs)`.

    Use this, not `build_scenario_inputs`, whenever the next thing you do is
    call `optimize_battery_schedule` (changed 2026-08-11).

    `build_scenario_inputs` returns five of the eleven keys `_scenario_inputs`
    produces, so every caller that wanted to run the optimizer had to rebuild
    the argument list by hand -- and each of them dropped the same fixture
    inputs on the floor: `initial_cost_basis`, `export_curtailment_active` and
    `home_settings`. A fixture then replayed under conditions it was never
    captured under, silently, while its pins stayed green. `golden_capture.py`
    was fixed for exactly this in Phase 1 and the copies here were left
    standing.

    Returning the kwargs whole removes the hand-listing step that caused it:
    `optimize_battery_schedule(**inputs)` cannot drop an input, and a new
    optimizer argument reaches these call sites without touching them.
    """
    scenario = load_test_scenario(scenario_name)
    return scenario, _scenario_inputs(scenario)


def build_scenario_inputs(scenario_name):
    """Load a scenario file and derive battery settings + buy/sell prices.

    Thin wrapper around helpers._scenario_inputs so every consumer of
    scenario files (this module and its several importers) shares one
    derivation path -- including the buy_price/sell_price direct-input and
    spot_multiplier handling added for debug-log-derived regression
    fixtures.

    For the four values it returns only. If you are about to call
    `optimize_battery_schedule`, use `build_scenario_optimizer_inputs`
    instead -- see its docstring for what hand-listing the arguments cost.
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

        # Energy throughput, not just money (added 2026-08-11, audit Pass 3
        # F3). 27 fixtures have carried these two values since they were
        # written and no test ever read them -- measured at the time of
        # wiring, all 27 were still accurate to <0.001 kWh, so this pins
        # what was already true rather than re-pinning anything.
        #
        # Worth asserting because the four scalars above are all money, and
        # money is lossy: two plans can cost the same to within a fraction of
        # an öre while cycling the battery differently -- the same energy
        # bought at a different hour, or a round trip added and another
        # removed. Wear is charged per kWh stored, so throughput is a
        # physical quantity the cost pins genuinely cannot express.
        # 27 of the 33 fixtures carry these. The 6 that do not are all
        # debug-log-derived regression fixtures (`regression_*`), whose
        # generator records economics but not throughput -- so this is
        # conditional on the key rather than on a default, which would
        # silently pin 0.0 for them.
        ENERGY_TOLERANCE_KWH = 0.001
        if "total_charged" in expected_results:
            total_charged = sum(pd.energy.battery_charged for pd in result.period_data)
            assert total_charged == pytest.approx(
                expected_results["total_charged"], abs=ENERGY_TOLERANCE_KWH
            ), f"Total charged mismatch: {total_charged:.6f} != {expected_results['total_charged']:.6f} kWh"
        if "total_discharged" in expected_results:
            total_discharged = sum(
                pd.energy.battery_discharged for pd in result.period_data
            )
            assert total_discharged == pytest.approx(
                expected_results["total_discharged"], abs=ENERGY_TOLERANCE_KWH
            ), f"Total discharged mismatch: {total_discharged:.6f} != {expected_results['total_discharged']:.6f} kWh"

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

        # `intents_present` / `intents_absent` are no longer asserted here
        # (changed 2026-08-11, audit Pass 3 F5). They were existence checks:
        # `intents_present` passed on a single period out of up to 134, so it
        # could only detect an intent class disappearing outright, and several
        # `intents_absent` entries could not fail at all -- SOLAR_STORAGE
        # declared absent on a fixture with no solar is unfalsifiable by
        # construction, not a guarantee.
        #
        # Every period's intent is now pinned exactly, for all 36 fixtures
        # (2168 periods), by the `intents` field in the action-selector
        # goldens. That is strictly stronger and it is deterministic: a
        # reclassification fails by name and period instead of surviving
        # because one other period still carries the intent. The keys remain
        # in the fixtures as scenario documentation.
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

    _, inputs = build_scenario_optimizer_inputs("synthetic_consumption_ev_charging")
    with caplog.at_level(logging.INFO, logger="core.bess.dp_battery_algorithm"):
        result = optimize_battery_schedule(**inputs)

    # Pinned costs alone would keep passing if the detector drifted and this
    # fixture started resolving windows that happen to be no-ops -- which is
    # exactly what happened to the fixture this test used to use. Assert the
    # fast path was actually taken, not just that the numbers came out right.
    assert not [
        r for r in caplog.records if "Near-tied DP decisions detected" in r.getMessage()
    ], "fixture now trips the tie detector -- it no longer exercises the fast path"

    # Re-pinned when the fixture corpus was retrofitted off
    # `terminal_value_per_kwh = 0.0` onto its production-computed value: this
    # fixture runs at 2.4481 SEK/kWh, which moves the grid DP's own output by
    # -0.030 SEK. The fast-path guarantee this test exists to protect is
    # unchanged -- the assertion above still shows no tie window is detected.
    #
    # Re-pinned again by Phase 4b (#352): -0.07996 SEK, the exact-cover
    # candidate changing what this fixture plans. The fast-path assertion
    # above is what this test is for and is unaffected -- the detector still
    # flags nothing.
    assert result.economic_summary.battery_solar_cost == pytest.approx(
        158.13671158, abs=1e-4
    )
    # Savings = grid_only_cost - battery_solar_cost, so this moves with it.
    assert result.economic_summary.grid_to_battery_solar_savings == pytest.approx(
        62.97779, abs=1e-3
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

    scenario, inputs = build_scenario_optimizer_inputs("regression_2026_08_06_466")
    result = optimize_battery_schedule(**inputs)

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


def test_352_low_rate_export_is_not_planned_when_exact_cover_exists():
    """#352 Shape B, on the reporter's own hardware data: a period whose
    house load falls between two lattice steps must not be planned as a
    partial-rate export.

    Replays `regression_2026_08_12_202906` (Growatt MIN, 15 kW battery, from
    the 2026-08-12 bundle). Period 99 needs 0.700 kWh over 15 minutes --
    2.80 kW -- and the percent lattice offers 18% (2.70 kW) or 19% (2.85
    kW). Pre-fix the DP chose 3.30 kW: it under-covers at 2.70 (importing
    0.025 kWh at buy 3.92) and over-covers above it, so over-covering was
    the cheaper error. That is what classified the period BATTERY_EXPORT,
    which is what wrote `grid_first` at a sub-load rate -- and `grid_first`
    does not load-follow, so the reporter's evening oven load was imported
    while the battery sat at 10.2 kWh.

    The export was never the goal (design doc section 2, "the root cause is a
    missing candidate"): 0.125 kWh at sell 2.63 against 2.925 kWh of
    forfeited load-following headroom. On ceiling hardware exact cover *is*
    commandable -- 19% is a ceiling, so it delivers min(2.85, 2.80) = 2.80
    exactly -- so the fix is that the candidate exists, not that the export
    is vetoed.

    Asserts the outcome (flows and realized cost), not the written command:
    a rate assertion would stay green if the plan still exported and only
    the mapping changed.
    """
    from core.bess.simulation.inverter_simulator import (
        derive_control_command,
        simulate,
    )

    scenario = load_test_scenario("regression_2026_08_12_202906")
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)
    dt = inp["period_duration_hours"]

    pd = result.period_data[99]
    assert pd.energy.battery_to_grid == pytest.approx(0.0, abs=1e-6), (
        f"period 99: planned a {pd.energy.battery_to_grid:.4f} kWh export "
        f"against {pd.energy.home_consumption:.4f} kWh of home consumption -- "
        f"the commitment shape #352 reports. Intent "
        f"{pd.decision.strategic_intent}, action "
        f"{pd.decision.battery_action:.4f} kWh"
    )
    assert pd.energy.grid_imported == pytest.approx(0.0, abs=1e-6), (
        f"period 99: the battery holds enough to cover the house exactly; "
        f"got {pd.energy.grid_imported:.4f} kWh imported"
    )
    assert pd.energy.battery_to_home == pytest.approx(
        pd.energy.home_consumption, abs=1e-6
    )

    # R == P over the whole horizon: the cover plan is a ceiling command,
    # and a ceiling that rounds DOWN would under-deliver it (539 of 1377
    # corpus deficits round down under nearest-rounding -- design doc
    # section 2). This is the assertion that catches that.
    commands = [
        derive_control_command(
            p.decision.strategic_intent,
            p.decision.battery_action / dt,
            inp["battery_settings"],
            intra_period_discharge_allowed=p.decision.intra_period_discharge_allowed,
        )
        for p in result.period_data
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
    assert sim.realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=1e-6
    )


def test_352_fix_must_not_refuse_the_arbitrage_remainder():
    """The adversarial pin the design requires alongside the #352 fix, and
    the case that refuted an earlier answer to it (design doc section 6).

    25 kWh available above reserve, a 10 kW export cap, three hourly periods
    priced 2.00 / 4.00 / 5.00 SEK/kWh and no house load. The optimum is
    **5, 10, 10**: every exporting period at the cap except one, which takes
    the remainder in the *cheapest* hour. That 50%-rate period is a
    partial-rate committing export and it is legitimate arbitrage -- a rule
    that fixes #352 by refusing partial-rate exports moves 4.5 kWh into the
    0.50 SEK/kWh hour and loses 7% of the revenue.

    This is why #352 is fixed by *adding* the missing cover candidate rather
    than by a materiality veto: adding a candidate cannot refuse this plan.
    Stated as revenue rather than "unchanged" so a regression reports a
    number.
    """
    settings_kwargs = {
        "max_soe_kwh": 28.0,
        "min_soe_kwh": 3.0,
        "max_charge_power_kw": 10.0,
        "max_discharge_power_kw": 10.0,
        "efficiency_charge": 1.0,
        "efficiency_discharge": 1.0,
        "cycle_cost_per_kwh": 0.0,
        "initial_soe": 28.0,
    }
    scenario = {
        "period_duration_hours": 1.0,
        "buy_price": [2.0, 4.0, 5.0],
        "sell_price": [2.0, 4.0, 5.0],
        "home_consumption": [0.0, 0.0, 0.0],
        "solar_production": [0.0, 0.0, 0.0],
        "battery": settings_kwargs,
    }
    result = optimize_battery_schedule(**_scenario_inputs(scenario))

    discharged = [p.energy.battery_discharged for p in result.period_data]
    assert discharged[1:] == pytest.approx(
        [10.0, 10.0], abs=1e-6
    ), f"the two expensive hours must export at the cap; got {discharged}"
    assert 0.0 < discharged[0] < 10.0, (
        f"the energy-limited remainder must stay in the cheapest hour at a "
        f"partial rate -- a rule that refuses partial-rate exports pushes it "
        f"into a dearer hour or forfeits it; got {discharged}"
    )
    # Measured on this branch, not asserted as "unchanged": 4.9 rather than
    # the analytic 5.0 because the state grid leaves 0.1 kWh above reserve,
    # which is pre-existing and independent of this fix.
    revenue = sum(p.economic.export_revenue for p in result.period_data)
    assert revenue == pytest.approx(99.80, abs=1e-6), (
        f"planned export revenue {revenue:.2f} SEK; 4.9*2 + 10*4 + 10*5 = "
        f"99.80 is what this energy budget buys at the optimum"
    )


def test_exact_cover_is_delivered_in_the_round_down_band():
    """A cover plan whose ceiling rounds DOWN under nearest-rounding must
    still be delivered exactly (Phase 4b).

    This is the half of the fix the #352 reproduction does not exercise. At
    that fixture's period 99 the deficit (2.80 kW on a 0.15 kW step) happens
    to round *up*, so a cover plan survives nearest-rounding there by luck.
    Across the corpus 539 of 1377 house deficits round down, and for those a
    nearest-rounded ceiling sits below the plan and the inverter delivers
    less than planned -- silently, since `min(ceiling, load)` never reports
    a shortfall.

    Built to land squarely in that band: a 10 kW battery has a 0.1 kW step,
    and a 1.22 kW deficit is 12.2 steps -- nearest gives 12 (1.20 kW), a
    0.02 kW under-delivery, while ceil gives 13 (1.30 kW), which the ceiling
    throttles back to exactly 1.22. Asserted as realized-vs-planned cost
    through the inverter simulator, not as the percent written, so it holds
    the outcome rather than the mapping.
    """
    from core.bess.simulation.inverter_simulator import (
        derive_control_command,
        simulate,
    )

    scenario = {
        "period_duration_hours": 1.0,
        # Expensive to import, worthless to export, and only enough stored
        # energy for the three periods: covering the house exactly is the
        # only sensible action, so the DP has no reason to choose anything
        # else and the test pins the delivery rather than the choice.
        "buy_price": [3.0, 3.0, 3.0],
        "sell_price": [0.0, 0.0, 0.0],
        "home_consumption": [1.22, 1.22, 1.22],
        "solar_production": [0.0, 0.0, 0.0],
        "battery": {
            "max_soe_kwh": 20.0,
            "min_soe_kwh": 2.0,
            "max_charge_power_kw": 10.0,
            "max_discharge_power_kw": 10.0,
            "efficiency_charge": 1.0,
            "efficiency_discharge": 1.0,
            "cycle_cost_per_kwh": 0.0,
            "initial_soe": 6.0,
        },
    }
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)

    # The period must be planning *exactly* the deficit from the battery --
    # not merely ending up with the house covered, which a large export
    # would also produce as a by-product and which would make the
    # realized-cost assertion below pass without exercising the ceiling at
    # all.
    covered = [
        t
        for t, p in enumerate(result.period_data)
        if p.energy.battery_discharged == pytest.approx(1.22, abs=1e-6)
        and p.energy.battery_to_home == pytest.approx(1.22, abs=1e-6)
        and p.energy.grid_exported == pytest.approx(0.0, abs=1e-6)
    ]
    # At least one, not all three: how many periods choose exact cover is an
    # incidental DP outcome (terminal value moves it), while "a cover plan in
    # the round-down band is delivered exactly" is the property under test.
    # Non-empty is still the discriminating assertion -- under nearest
    # rounding no covering ceiling exists at 1.22 kW, the candidate is
    # withdrawn entirely, and this list goes empty.
    assert covered, (
        "no period planned exact cover at 1.22 kW, so this test pins "
        "nothing. Got "
        + str(
            [
                (p.decision.strategic_intent, p.energy.battery_discharged)
                for p in result.period_data
            ]
        )
    )

    commands = [
        derive_control_command(
            p.decision.strategic_intent,
            p.decision.battery_action / inp["period_duration_hours"],
            inp["battery_settings"],
            intra_period_discharge_allowed=p.decision.intra_period_discharge_allowed,
        )
        for p in result.period_data
    ]
    sim = simulate(
        commands,
        inp["solar_production"],
        inp["home_consumption"],
        inp["buy_price"],
        inp["sell_price"],
        scenario["battery"]["initial_soe"],
        inp["battery_settings"],
        inp["period_duration_hours"],
    )
    for t in covered:
        assert sim.period_data[t].energy.battery_discharged == pytest.approx(
            result.period_data[t].energy.battery_discharged, abs=1e-6
        ), (
            f"period {t}: planned "
            f"{result.period_data[t].energy.battery_discharged:.4f} kWh but "
            f"the written ceiling delivers "
            f"{sim.period_data[t].energy.battery_discharged:.4f} -- the "
            f"ceiling rounded below the plan"
        )
    assert sim.realized_cost == pytest.approx(
        result.economic_summary.battery_solar_cost, abs=1e-6
    )


def test_grid_charge_plan_is_deliverable_by_the_written_command():
    """Phase 4c: a planned grid charge must be a quantity the written command
    can actually deliver.

    The charge rate is written as an integer percent of `max_charge_power_kw`
    scaled from the plan's own action (`_compute_charge_rate`), and until 4c
    that scaling rounded to *nearest*. A planned power landing between two
    steps therefore rounded **down** and the inverter charged less than the
    plan assumed -- the charge-side twin of the discharge defect #352 fixed.

    Measured across the corpus before the fix: 4 of 493 charging periods
    under-deliver, worst `synthetic_extreme_volatility` period 13 at
    -0.0288 kWh (plan 0.4488 kWh, command 7% = 0.4200 kWh). Small, and worth
    fixing structurally rather than economically: the realized-*cost* gap is
    0.00000 on every affected fixture, so `test_realized_matches_planned_across_all_fixtures`
    stays green while the plan is not actually executable. Energy fidelity is
    what this asserts, because money cannot see it.

    **Only where a grid top-up is planned.** SOLAR_STORAGE writes a flat 100%
    (`INTENT_TO_CONTROL`), so its plan is never scaled and never rounds --
    311 of the corpus's 323 off-lattice charging periods are SOLAR_STORAGE
    and are correct as they stand. Quantizing those too would discard 3.70
    kWh of solar the battery can demonstrably store.
    """
    from core.bess.dp_schedule import DPSchedule
    from core.bess.growatt_min_controller import GrowattMinController
    from core.bess.simulation.inverter_simulator import (
        derive_control_command,
    )

    scenario = load_test_scenario("synthetic_extreme_volatility")
    inp = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inp)
    dt = inp["period_duration_hours"]

    commands = [
        derive_control_command(
            p.decision.strategic_intent,
            p.decision.battery_action / dt,
            inp["battery_settings"],
            intra_period_discharge_allowed=p.decision.intra_period_discharge_allowed,
        )
        for p in result.period_data
    ]

    grid_charging = [
        t
        for t, p in enumerate(result.period_data)
        if p.decision.strategic_intent == "GRID_CHARGING"
        and p.energy.battery_charged > 1e-6
    ]
    assert grid_charging, "fixture plans no grid charging -- pins nothing"

    # Asserted against what the written command can deliver, not against the
    # simulator's `battery_charged` -- deliberately, and this is the documented
    # exception to "assert the outcome, not the command".
    #
    # `simulate()` derives its flows from `_period_flows`, the same record the
    # DP uses, and that computes charge throughput from
    # `max_charge_power_kw` (the binary-store-physics assumption noted at
    # dp_battery_algorithm.py:974) rather than from the commanded rate. So the
    # simulator reproduces the plan by construction on this quantity and
    # cannot disagree with it -- `sim.period_data[t].energy.battery_charged`
    # equals the plan even when the command is 7% of nominal. Closing that
    # blindness *is* 4c; until then the only faithful comparison is against
    # the command itself. `mode_to_power` already models it correctly
    # (returns 0.42 kW for a 7% command); it is `_period_flows` that discards
    # it.
    # Both the production write path and the simulator's mirror of it: the
    # rate the *controller* computes is what reaches hardware, and the
    # simulator's copy has to agree or plan and execution drift apart again
    # (#282/#497). An earlier version of this test checked only the
    # simulator and stayed green when the controller was mutated back to
    # nearest-rounding.
    actions = [p.decision.battery_action for p in result.period_data]
    controller = GrowattMinController(battery_settings=inp["battery_settings"])
    controller.strategic_intents = [
        p.decision.strategic_intent for p in result.period_data
    ]
    controller.current_schedule = DPSchedule(
        actions=actions,
        state_of_energy=[p.energy.battery_soe_end for p in result.period_data],
        prices=list(inp["buy_price"][: len(actions)]),
    )
    max_charge = inp["battery_settings"].max_charge_power_kw

    for t in grid_charging:
        planned = result.period_data[t].energy.battery_charged
        written_pct = controller.get_period_settings(t)["charge_rate"]
        assert written_pct == commands[t].charge_rate_pct, (
            f"period {t}: the controller writes {written_pct}% but the "
            f"simulator models {commands[t].charge_rate_pct}% -- the two "
            f"charge mappings have drifted"
        )
        deliverable = (written_pct / 100) * max_charge * dt
        assert deliverable >= planned - 1e-6, (
            f"period {t}: planned {planned:.4f} kWh of charge but the written "
            f"command ({written_pct}% of {max_charge:.1f} kW) can deliver "
            f"only {deliverable:.4f} kWh -- the plan is not a quantity the "
            f"integer-percent charge lattice can express"
        )


def test_import_capped_grid_charge_command_stays_under_the_fuse():
    """Phase 4c, the import-capped half: where the house fuse is what limits
    a grid charge, the *plan* comes down to the lattice instead of the
    command going up to the plan.

    Rounding a charge command up is safe only because the battery's own
    remaining room binds above it -- the inverter stops when full. When
    `import_cap_kwh` (#429) is what limited the plan, nothing binds above the
    command, and rounding up would draw more from the grid than the fuse
    allows. So `execution_model.lattice_grid_charge` floors the planned grid
    top-up onto the lattice first, and the round-up is then a no-op.

    Constructed because **no corpus fixture reaches this path**: every one of
    them runs with power monitoring off, so `import_cap_kwh` is None and the
    flooring never fires. Without this test the function added for it has no
    coverage at all -- which is exactly what review round 1 caught.

    1-phase, 230 V, 20 A fuse -> a 4.6 kWh/period cap on a 6 kW battery,
    whose 1% step is 0.06 kW. 4.6 is 76.67 steps: off the lattice. Floored to
    76 steps = 4.56 kWh, which the 76% command delivers exactly. Unfloored,
    the plan would be 4.6 and `ceil(76.67) = 77%` would command 4.62 kWh --
    **over the fuse**, which is the failure this pins.
    """
    from core.bess.dp_battery_algorithm import _effective_import_cap_kwh
    from core.bess.dp_schedule import DPSchedule
    from core.bess.growatt_min_controller import GrowattMinController

    # 24 hourly periods: `DPSchedule` derives its period length as
    # `24 / len(actions)`, so a shorter horizon would make the controller
    # scale the rate against the wrong hour length.
    scenario = {
        "period_duration_hours": 1.0,
        # Cheap early, expensive late: grid-charge hard, then export.
        "buy_price": [0.1] * 12 + [5.0] * 12,
        "sell_price": [0.05] * 12 + [4.9] * 12,
        "home_consumption": [0.0] * 24,
        "solar_production": [0.0] * 24,
        "home": {
            "power_monitoring_enabled": True,
            "max_fuse_current": 20,
            "voltage": 230,
            "phase_count": 1,
        },
        "battery": {
            "max_soe_kwh": 40.0,
            "min_soe_kwh": 2.0,
            "max_charge_power_kw": 6.0,
            "max_discharge_power_kw": 6.0,
            "efficiency_charge": 1.0,
            "efficiency_discharge": 1.0,
            "cycle_cost_per_kwh": 0.0,
            "initial_soe": 2.0,
        },
    }
    inp = _scenario_inputs(scenario)
    dt = inp["period_duration_hours"]
    cap_kwh = _effective_import_cap_kwh(inp.get("home_settings"), dt)
    assert cap_kwh == pytest.approx(
        4.6, abs=1e-9
    ), f"scenario no longer produces the intended off-lattice cap: {cap_kwh}"

    result = optimize_battery_schedule(**inp)
    controller = GrowattMinController(battery_settings=inp["battery_settings"])
    controller.strategic_intents = [
        p.decision.strategic_intent for p in result.period_data
    ]
    controller.current_schedule = DPSchedule(
        actions=[p.decision.battery_action for p in result.period_data],
        state_of_energy=[p.energy.battery_soe_end for p in result.period_data],
        prices=list(inp["buy_price"]),
    )
    max_charge = inp["battery_settings"].max_charge_power_kw

    capped = [
        t
        for t, p in enumerate(result.period_data)
        if p.decision.strategic_intent == "GRID_CHARGING"
        and p.energy.grid_to_battery > 1e-6
    ]
    assert capped, "scenario plans no grid charging -- pins nothing"

    for t in capped:
        planned = result.period_data[t].energy.battery_charged
        written_pct = controller.get_period_settings(t)["charge_rate"]
        commanded = (written_pct / 100) * max_charge * dt
        assert commanded <= cap_kwh + 1e-9, (
            f"period {t}: the written command ({written_pct}% of "
            f"{max_charge:.1f} kW = {commanded:.4f} kWh) exceeds the house "
            f"import cap of {cap_kwh:.4f} kWh -- rounding a charge up is only "
            f"safe when the battery's own room binds above it"
        )
        assert commanded == pytest.approx(planned, abs=1e-6), (
            f"period {t}: planned {planned:.4f} kWh but the command delivers "
            f"{commanded:.4f} -- an import-capped plan must be exactly "
            f"expressible, since it can be neither exceeded nor rounded up"
        )
