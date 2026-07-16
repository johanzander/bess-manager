"""SOLAR_EXPORT intra-period discharge gate (shadow-price).

The optimizer plans power=0 (hold) for SOLAR_EXPORT periods, mapping to
load_first + discharge_rate=0. But discharge_rate=0 is a hardware register that
blocks the battery from covering an intra-period solar dip. Whether it SHOULD
cover the dip is an economic question: cover from battery only when the stored
energy is worth less than buying from grid right now, i.e.

    buy_price * efficiency_discharge >= shadow_price

where shadow_price is the DP value-function gradient dV/dSoE (marginal
opportunity value of stored energy), persisted per period on DecisionData.

See docs/superpowers/specs/2026-06-27-solar-export-discharge-rate-design.md.
"""

from types import SimpleNamespace

import pytest

from core.bess.battery_system_manager import (
    BatterySystemManager,
    intra_period_discharge_gate,
)
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import make_battery_settings

PERIOD = 20  # Arbitrary test period (quarter-hour slot)


def test_intra_period_discharge_gate_gate_boundary():
    """Gate is 100 iff buy*eff_d >= shadow; equality discharges (>=)."""
    eff_d = 0.95
    # stored energy worth less than buying now -> cover from battery
    assert (
        intra_period_discharge_gate(buy_price=2.0, shadow_price=1.0, eff_d=eff_d) == 100
    )
    # stored energy worth more (reserved for a peak) -> hold, buy from grid
    assert (
        intra_period_discharge_gate(buy_price=0.5, shadow_price=4.0, eff_d=eff_d) == 0
    )
    # exact equality -> discharge (>=)
    assert (
        intra_period_discharge_gate(buy_price=1.0, shadow_price=0.95, eff_d=0.95) == 100
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


def _store_shadow_price(
    bsm: BatterySystemManager, period: int, shadow_price: float
) -> None:
    """Populate the schedule store with a SOLAR_EXPORT period at the given shadow price."""
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
    decision = DecisionData(strategic_intent="SOLAR_EXPORT", shadow_price=shadow_price)
    period_data = PeriodData(
        period=period,
        energy=energy,
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
        """High buy price, low shadow price -> gate opens, dip covered from battery."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")
        _store_shadow_price(bsm, PERIOD, shadow_price=0.5)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_reserve_protected_when_shadow_price_high(self):
        """Low buy price, high shadow price -> gate stays closed, reserve protected."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_EXPORT")
        _store_shadow_price(bsm, PERIOD, shadow_price=4.0)

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
    marginal stored kWh is worth only the export price: shadow price
    converges to sell_price in steady state, per the documented economic law
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
            assert shadow == pytest.approx(
                sell[t], abs=0.01
            ), f"period {t}: shadow {shadow:.4f} should equal sell_price {sell[t]}"
        assert shadow < buy[t] * eff_d
        assert intra_period_discharge_gate(buy[t], shadow, eff_d) == 100


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
        assert intra_period_discharge_gate(buy[t], shadow, eff_d) == 0
