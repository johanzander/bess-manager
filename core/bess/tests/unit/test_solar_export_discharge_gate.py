"""SOLAR_EXPORT intra-period discharge gate (shadow-price).

The optimizer plans power=0 (hold) for SOLAR_EXPORT periods, mapping to
load_first + discharge_rate=0. But discharge_rate=0 is a hardware register that
blocks the battery from covering an intra-period solar dip. Whether it SHOULD
cover the dip is an economic question: cover from battery only when the stored
energy is worth less than buying from grid right now, i.e.

    buy_price >= shadow_price

where shadow_price is the marginal opportunity value of stored energy priced
per kWh *delivered* (#683), persisted per period on DecisionData. Both sides are
therefore in the same unit and no efficiency factor appears: covering dE consumes
dE/eta of SoE, which would later have delivered dE anyway, so eta cancels.

See docs/superpowers/specs/2026-06-27-solar-export-discharge-rate-design.md.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import (
    _interpolate_value,
    _record_marginal_value,
    _value_of_delivering_below,
    optimize_battery_schedule,
)
from core.bess.dp_constants import SOE_STEP_KWH
from core.bess.execution_model import intra_period_discharge_gate
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import make_battery_settings, run_scenario

PERIOD = 20  # Arbitrary test period (quarter-hour slot)

ISSUE_571_FIXTURE = Path(__file__).parent / "data" / "regression_2026_08_13_145213.json"


def _authorize(cell_slope: float, buy_price: float, eff_d: float):
    """Run `_record_marginal_value` against a value function whose SoE-cell slope
    is `cell_slope` at the sampled state, and return the decision.

    The parameter is the slope per kWh of *SoE*. What the DP records is the value
    given up per kWh *delivered* (#683), which on a linear V_row is exactly
    `cell_slope / eff_d` -- delivering one step costs `1/eff_d` steps of SoE. The
    tests below assert that conversion explicitly rather than passing the recorded
    number in, so the unit the gate compares against is stated, not assumed.

    The buy-vs-hold comparison moved into the DP (#526), so the boundary test
    below drives it where it now lives rather than through a standalone gate
    function that could no longer tell a computed zero from an absent one.
    """
    settings = make_battery_settings(efficiency_discharge=eff_d)
    decision = DecisionData(strategic_intent="SOLAR_EXPORT")
    # A SoE one grid step above the floor lands on index 1, so V is linear over
    # the span the delivery consumes and its cell slope is exactly `cell_slope`.
    soe = settings.min_soe_kwh + SOE_STEP_KWH
    V = np.array([[0.0, cell_slope * SOE_STEP_KWH]])
    _record_marginal_value(
        decision,
        V=V,
        t=0,
        soe=soe,
        battery_settings=settings,
        buy_price_t=buy_price,
    )
    return decision


def test_intra_period_discharge_authorization_boundary():
    """The DP authorizes iff buy >= shadow; equality discharges (>=).

    #683: both sides are per kWh delivered, so no efficiency factor appears in the
    rule -- and it appears here only in converting the constructed SoE-cell slope
    into the delivered-kWh price the DP actually records.
    """
    eff_d = 0.95
    # stored energy worth less than buying now -> cover from battery
    decision = _authorize(cell_slope=1.0, buy_price=2.0, eff_d=eff_d)
    assert decision.shadow_price == pytest.approx(1.0 / eff_d)
    assert decision.intra_period_discharge_allowed is True
    assert intra_period_discharge_gate(decision.intra_period_discharge_allowed) == 100

    # stored energy worth more (reserved for a peak) -> hold, buy from grid
    decision = _authorize(cell_slope=4.0, buy_price=0.5, eff_d=eff_d)
    assert decision.shadow_price == pytest.approx(4.0 / eff_d)
    assert decision.intra_period_discharge_allowed is False
    assert intra_period_discharge_gate(decision.intra_period_discharge_allowed) == 0

    # Exact equality -> discharge (>=). Note this case is NOT a behaviour change:
    # a cell slope of eff_d prices delivery at exactly 1.0, and the old
    # `buy * eff_d >= shadow` rule evaluated 0.95 >= 0.95 -> True on the same
    # inputs. It is pinned because `>=` is what makes an exact tie discharge, and
    # a `>` would silently change that.
    decision = _authorize(cell_slope=eff_d, buy_price=1.0, eff_d=eff_d)
    assert decision.shadow_price == pytest.approx(1.0)
    assert decision.intra_period_discharge_allowed is True
    assert intra_period_discharge_gate(decision.intra_period_discharge_allowed) == 100


def test_no_computable_shadow_price_does_not_authorize():
    """#526: at the bottom grid level the backward difference does not exist,
    so there is nothing to authorize -- absence must not read as permission,
    even at a buy price that would clear any computed shadow price."""
    settings = make_battery_settings(efficiency_discharge=0.95)
    decision = DecisionData(strategic_intent="SOLAR_EXPORT")

    _record_marginal_value(
        decision,
        V=np.array([[0.0, 10.0]]),
        t=0,
        soe=settings.min_soe_kwh,  # grid index 0 -- no cell below it
        battery_settings=settings,
        buy_price_t=99.0,
    )

    assert decision.shadow_price == 0.0  # never computed, still the default
    assert decision.intra_period_discharge_allowed is False
    assert intra_period_discharge_gate(decision.intra_period_discharge_allowed) == 0


@pytest.mark.parametrize("offset_steps", [1.5, 2.0])
def test_gate_price_stays_on_the_policys_interpolant(offset_steps):
    """#571's standing guard: the gate's value estimate must BE a reading of
    `_interpolate_value`, not a second implementation that can drift from it.

    Checked at a strictly-interior SoE and at an exact grid point, because
    those are the two cases the old `round()` arithmetic got differently wrong.

    This restates the implementation deliberately -- that is the whole point of
    a structural pin. #571 was not a wrong formula but a *second* formula, and
    what stops that recurring is an assertion a re-implementation must break.
    #683 only widened the span read: a whole delivery's worth of SoE
    (`SOE_STEP_KWH / eta`) rather than a fraction of one cell.
    """
    settings = make_battery_settings()
    V_row = np.array([0.0, 1.0, 3.0, 4.0])  # deliberately non-linear
    soe = settings.min_soe_kwh + offset_steps * SOE_STEP_KWH

    soe_consumed = SOE_STEP_KWH / settings.efficiency_discharge
    expected = (
        _interpolate_value(V_row, soe, settings)
        - _interpolate_value(V_row, soe - soe_consumed, settings)
    ) / SOE_STEP_KWH

    assert _value_of_delivering_below(V_row, soe, settings) == pytest.approx(expected)


def test_no_cell_below_the_floor_has_no_price_to_read():
    """At and below the bottom grid level there is no removable kWh, so there
    is nothing to price -- `None`, which #526 requires to read as "no
    authorization" rather than "worthless"."""
    settings = make_battery_settings()
    V_row = np.array([0.0, 1.0, 3.0, 4.0])

    assert _value_of_delivering_below(V_row, settings.min_soe_kwh, settings) is None
    assert (
        _value_of_delivering_below(V_row, settings.min_soe_kwh - 1.0, settings) is None
    )

    # A battery resting ON the floor does not always land on a clean 0.0: the
    # subtraction leaves a sub-picowatt-hour positive residue in several
    # fixtures. Same physical state, so it must reach the same answer -- a
    # one-sided slope is discontinuous here, and #526 is what breaks otherwise.
    a_hair_above_floor = np.nextafter(settings.min_soe_kwh, np.inf)
    assert a_hair_above_floor > settings.min_soe_kwh  # guard: really is above
    assert _value_of_delivering_below(V_row, a_hair_above_floor, settings) is None


def test_single_level_value_row_has_no_price_to_read():
    """A one-level `V_row` has no cell at all, so there is nothing to price.

    Without the explicit `len(V_row) < 2` guard, `_interpolate_value` returns
    `V_row[0]` at both ends (its below-floor extrapolation has a zero gradient
    with nothing to extrapolate from), so the difference is a computed `0.0`.
    That is the #526 failure mode exactly: a zero shadow price clears any
    positive buy price and opens the gate on a value that was never computed,
    and unlike the missing-field default it survives every `None` check
    downstream. Asserted directly rather than through a schedule because a
    production battery always has >= 2 grid levels, so no scenario reaches it.
    """
    settings = make_battery_settings()

    assert (
        _value_of_delivering_below(np.array([5.0]), settings.max_soe_kwh, settings)
        is None
    )


def _shadow_price_at_start_soe(initial_soe: float) -> float:
    """dV/dSoE the DP records for period 0 when the battery starts at `initial_soe`.

    Real data from issue #571's debug bundle, run through the real optimizer.
    Only the forward pass depends on `initial_soe`, so `V[0, :]` -- the row the
    shadow price is read from -- is identical across these runs; the only thing
    that varies is which part of that row the recording samples.
    """
    scenario = json.loads(ISSUE_571_FIXTURE.read_text())
    scenario["battery"]["initial_soe"] = initial_soe
    return run_scenario(scenario).period_data[0].decision.shadow_price


def test_shadow_price_is_continuous_in_soe():
    """#571's guard, re-pinned to continuity by #683.

    #571 was a *discontinuity*: `_record_marginal_value` snapped with `round()`
    while `_interpolate_value` (which the policy walks) floors, so a state in the
    lower half of a cell was priced off the cell below -- a value-function region
    the battery is not in. On this bundle that put a 0.013 EUR/kWh step in the
    middle of a cell, forming an isolated 25 Wh window where the gate closed, and
    the gate reads this number raw.

    #571 pinned that by asserting the price is *constant* within a cell, which was
    true of a one-cell backward difference. #683 replaced that estimator with one
    that prices a whole delivery (`SOE_STEP_KWH / eta` of SoE, spanning just over
    one cell), and the result is genuinely continuous rather than piecewise
    constant -- so constancy is no longer the right pin, and monotonicity is not
    true either (the measured sweep reverses direction at 9.8750 -> 9.8800).

    Continuity is pinned by *resolution scaling*, which needs no arbitrary
    threshold: sample the same interval four times as finely and the largest
    step between neighbours must fall by a factor of four. A jump cannot shrink,
    so #571's defect floors the ratio at 1.0 while a continuous price gives 4.0.
    Measured on this fixture: 4.00 with the fix, 1.00 with the pre-#683
    estimator restored.
    """
    min_soe = json.loads(ISSUE_571_FIXTURE.read_text())["battery"]["min_soe_kwh"]
    # Three whole cells starting at a grid point, so the sweep crosses two cell
    # boundaries -- where #571's discontinuity lived.
    lo = min_soe + 322 * SOE_STEP_KWH
    span = 3 * SOE_STEP_KWH
    refinement = 4
    fine_n = 24

    fine = [
        _shadow_price_at_start_soe(lo + span * k / fine_n) for k in range(fine_n + 1)
    ]
    fine_step = max(abs(fine[i + 1] - fine[i]) for i in range(fine_n))
    coarse_step = max(
        abs(fine[i + refinement] - fine[i]) for i in range(0, fine_n, refinement)
    )

    # Vacuity guard: a degenerate estimator reporting one value everywhere would
    # give 0/0 and satisfy any ratio.
    assert fine_step > 0.0, "shadow price does not vary across three grid cells"

    assert coarse_step / fine_step == pytest.approx(refinement, rel=0.05), (
        f"shadow price is not continuous in SoE: sampling {refinement}x finer "
        f"shrank the largest step only {coarse_step / fine_step:.2f}x "
        f"(coarse {coarse_step:.6f}, fine {fine_step:.6f}). A ratio near 1.0 "
        "means a jump, which is #571."
    )


def test_shadow_price_still_varies_between_grid_cells():
    """Guard on the test above: equality within a cell must not come from a
    degenerate estimator that reports one value everywhere."""
    min_soe = json.loads(ISSUE_571_FIXTURE.read_text())["battery"]["min_soe_kwh"]
    in_cell_323, in_cell_324 = 9.8800, 9.9200
    assert int((in_cell_323 - min_soe) / SOE_STEP_KWH) == 323
    assert int((in_cell_324 - min_soe) / SOE_STEP_KWH) == 324

    assert _shadow_price_at_start_soe(in_cell_323) != pytest.approx(
        _shadow_price_at_start_soe(in_cell_324)
    )


def _make_bsm(
    buy_prices: list[float],
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource(buy_prices),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)


def _store_authorization(bsm: BatterySystemManager, period: int, allowed: bool) -> None:
    """Populate the schedule store with a SOLAR_EXPORT period carrying the DP's
    sub-period discharge authorization (#526 -- the BSM reads the decision, not
    the shadow price it was derived from)."""
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    decision = DecisionData(
        strategic_intent="SOLAR_EXPORT", intra_period_discharge_allowed=allowed
    )
    period_data = PeriodData(
        period=period,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(period),
        economic=EconomicData(),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestSolarExportDischargeGate:
    """BSM-integration coverage: proves the gate actually fires in the real
    hardware-write path (_apply_period_schedule), not just the standalone
    gate function. Mirrors TestSolarStorageDischargeGate."""

    def test_dip_covered_when_battery_worth_less_than_grid(self):
        """DP authorized (stored energy worth less than buying now) -> gate
        opens, dip covered from battery."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")
        _store_authorization(bsm, PERIOD, allowed=True)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_reserve_protected_when_dp_withholds_authorization(self):
        """DP withheld authorization (reserve worth more than the dip) ->
        gate stays closed, reserve protected."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")
        _store_authorization(bsm, PERIOD, allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_no_stored_schedule_holds_discharge(self):
        """No schedule stored yet -> gate cannot evaluate, discharge stays 0 (safe default)."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0


def _solar_export_periods(result):
    return [
        t
        for t, pd in enumerate(result.period_data)
        if pd.decision.strategic_intent == "SOLAR_EXPORT"
    ]


@pytest.mark.slow
def test_solar_export_covers_dip_when_buy_exceeds_export():
    """Normal prices (buy comfortably above shadow). During the solar-surplus
    window the battery is at/near capacity and exporting surplus, so the
    marginal *stored* kWh is worth only the export price. Since #683 the
    recorded shadow price is denominated per kWh **delivered**, so it converges
    to `sell_price / efficiency_discharge` in steady state -- the same economic
    law in a different unit, per the documented law
    (see docs/agents/bess-knowledge.md and
    docs/superpowers/specs/2026-06-27-solar-export-discharge-rate-design.md).

    Checked across the whole solar-surplus window (periods 0-7) rather than
    filtering to periods labeled SOLAR_EXPORT specifically: at fine DP
    discretization (docs/superpowers/specs/2026-07-12-dp-continuous-path-reconstruction-fix-design.md,
    Option B) some of these periods land on a tiny genuine micro-arbitrage
    discharge the old coarser grid couldn't represent, and get classified
    BATTERY_EXPORT instead -- a real, small optimization improvement, not a
    change to the underlying economic law this test checks. The shadow price
    still converges to sell_price on those periods either way.

    The first period is a finite-horizon transient (a normal DP boundary
    effect near the horizon's terminal transition, not an economic constant)
    and is only checked for the gate property, not the exact value. The gate
    still ALLOWS discharge (100) here because buy*eff_d clears the shadow
    price either way.
    """
    bs = make_battery_settings(efficiency_discharge=0.95)
    eff_d = bs.efficiency_discharge

    buy = [1.0] * 8 + [5.0] * 8
    sell = [0.3] * 16
    solar = [4.0] * 8 + [0.0] * 8
    consumption = [0.5] * 8 + [2.0] * 8

    result = optimize_battery_schedule(
        buy_price=buy,
        sell_price=sell,
        home_consumption=consumption,
        battery_settings=bs,
        solar_production=solar,
        initial_soe=bs.max_soe_kwh,  # full battery -> daytime surplus is solar-export-driven
    )

    for t in range(8):
        shadow = result.period_data[t].decision.shadow_price
        if t == 0:
            # First period is a finite-horizon transient near the horizon's
            # terminal transition, not a fixed economic constant -- at fine
            # DP discretization (docs/superpowers/specs/2026-07-12-dp-
            # continuous-path-reconstruction-fix-design.md, Option B) the
            # backward-difference V[0,i]-V[0,i-1] can legitimately land on
            # exactly 0.0 right at max capacity here. Only check the gate
            # decision itself is still consistent (a zero shadow price still
            # correctly implies "discharge is fine," so the gate call below
            # must still be 100).
            assert shadow >= 0.0, f"period {t}: shadow_price not populated"
        else:
            # Steady state: shadow price converges to sell_price, per
            # docs/agents/bess-knowledge.md's documented law for the
            # solar-surplus window (battery at/near capacity, solar refills
            # it for free -- marginal kWh is worth only the export price).
            assert shadow > 0.0, f"period {t}: shadow_price not populated"
            # #683: shadow_price is per kWh delivered, so the steady-state value
            # of a stored kWh (the sell price) appears divided by eff_d.
            assert shadow == pytest.approx(sell[t] / eff_d, abs=0.01), (
                f"period {t}: shadow {shadow:.4f} should equal sell_price "
                f"{sell[t]} / eff_d {eff_d} = {sell[t] / eff_d:.4f}"
            )
        # #683: both sides per kWh delivered, so no efficiency factor. This is
        # the same condition as the old `shadow < buy * eff_d` on a per-SoE
        # shadow price -- `buy >= sell/eta` and `buy * eta >= sell` agree.
        assert shadow < buy[t]
        assert result.period_data[t].decision.intra_period_discharge_allowed is True


@pytest.mark.slow
def test_solar_export_holds_when_export_more_valuable():
    """Temporary export premium during solar hours, followed by an expensive
    buy window right after. The stored energy is worth more EXPORTED now (or
    preserved for the expensive window ahead) than the cheap grid import it
    would displace, so the gate HOLDS (0): export the surplus and buy the dip
    from grid instead of discharging the battery. Proves the gate is not a
    no-op. (A sustained export premium with no future recharge cost instead
    makes full-day arbitrage strictly better than holding, eliminating
    SOLAR_EXPORT entirely -- hence the expensive window after solar hours,
    which is what makes preserving stored energy the better choice here.)

    Future consumption (periods 8-15) is set to exceed the battery's usable
    capacity (bs.max_soe_kwh - bs.min_soe_kwh), not just approach it: with
    usable capacity > future need, the DP's own exact backward-induction
    optimum genuinely prefers selling a small "free" slack now (it doesn't
    reduce what's available to cover the future need either way) even though
    the coarse discretization grid used to be too coarse to discover that
    optimum, producing an accidental hold that only looked like the documented
    law. Verified (docs/superpowers/specs/2026-07-12-dp-continuous-path-reconstruction-fix-design.md,
    Option B investigation): with genuine future scarcity (no slack), holding
    is the DP's true optimum at any grid resolution, not just an artifact.
    """
    bs = make_battery_settings(efficiency_discharge=0.95)
    eff_d = bs.efficiency_discharge

    buy = [0.2] * 8 + [8.0] * 8  # export premium during solar hours, then a
    # much more expensive window right after -- preserving stored energy for
    # that window beats liquidating it now (verified: this is what makes the
    # DP genuinely hold rather than actively discharge -- with a sustained
    # premium and no future cost of recharging, full-day arbitrage dominates
    # instead, per this scenario's original inputs).
    sell = [1.0] * 8 + [0.5] * 8
    solar = [4.0] * 8 + [0.0] * 8
    # 8 * 2.3 = 18.4 kWh future need > 17.8 kWh usable capacity (bs defaults):
    # genuine scarcity, no free slack to sell now regardless of discretization.
    consumption = [0.5] * 8 + [2.3] * 8

    result = optimize_battery_schedule(
        buy_price=buy,
        sell_price=sell,
        home_consumption=consumption,
        battery_settings=bs,
        solar_production=solar,
        initial_soe=bs.max_soe_kwh,
    )

    periods = _solar_export_periods(result)
    assert periods, "scenario did not produce any SOLAR_EXPORT period"
    for t in periods:
        shadow = result.period_data[t].decision.shadow_price
        assert shadow > buy[t] * eff_d, (
            f"period {t}: shadow {shadow:.3f} should exceed buy*eff_d "
            f"{buy[t] * eff_d:.3f} (export worth more than grid import)"
        )
        assert result.period_data[t].decision.intra_period_discharge_allowed is False
