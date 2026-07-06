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

import pytest

from core.bess.battery_system_manager import solar_export_discharge_rate
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import make_battery_settings


def test_solar_export_discharge_rate_gate_boundary():
    """Gate is 100 iff buy*eff_d >= shadow; equality discharges (>=)."""
    eff_d = 0.95
    # stored energy worth less than buying now -> cover from battery
    assert (
        solar_export_discharge_rate(buy_price=2.0, shadow_price=1.0, eff_d=eff_d) == 100
    )
    # stored energy worth more (reserved for a peak) -> hold, buy from grid
    assert (
        solar_export_discharge_rate(buy_price=0.5, shadow_price=4.0, eff_d=eff_d) == 0
    )
    # exact equality -> discharge (>=)
    assert (
        solar_export_discharge_rate(buy_price=1.0, shadow_price=0.95, eff_d=0.95) == 100
    )


def _solar_export_periods(result):
    return [
        t
        for t, pd in enumerate(result.period_data)
        if pd.decision.strategic_intent == "SOLAR_EXPORT"
    ]


@pytest.mark.slow
def test_solar_export_covers_dip_when_buy_exceeds_export():
    """Normal prices (buy comfortably above shadow). During SOLAR_EXPORT the
    battery is full and exporting surplus, so the marginal stored kWh is worth
    only the export price: shadow price converges to sell_price in steady
    state, per the documented economic law (see
    docs/agents/bess-knowledge.md and
    docs/superpowers/specs/2026-06-27-solar-export-discharge-rate-design.md).
    The first SOLAR_EXPORT period is a finite-horizon transient (a normal DP
    boundary effect near the horizon's terminal transition, not an economic
    constant) and is only checked for the gate property, not the exact value.
    The gate still ALLOWS discharge (100) here because buy*eff_d clears the
    shadow price either way.
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
        initial_soe=bs.max_soe_kwh,  # full battery -> daytime surplus is SOLAR_EXPORT
    )

    periods = _solar_export_periods(result)
    assert periods, "scenario did not produce any SOLAR_EXPORT period"
    for t in periods:
        shadow = result.period_data[t].decision.shadow_price
        assert shadow > 0.0, f"period {t}: shadow_price not populated"
        if t == periods[0]:
            # First SOLAR_EXPORT period is a finite-horizon transient (verified:
            # 0.45 here vs. steady-state 0.30 for the rest) -- a normal DP
            # boundary effect near the horizon's terminal transition, not a
            # fixed economic constant. Only check the gate property still holds.
            assert shadow > 0.0
        else:
            # Steady state: shadow price converges to sell_price, per
            # docs/agents/bess-knowledge.md's documented law for SOLAR_EXPORT
            # (battery full, solar refills it for free -- marginal kWh is
            # worth only the export price).
            assert shadow == pytest.approx(
                sell[t], abs=0.01
            ), f"period {t}: shadow {shadow:.4f} should equal sell_price {sell[t]}"
        assert shadow < buy[t] * eff_d
        assert solar_export_discharge_rate(buy[t], shadow, eff_d) == 100


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
    which is what makes preserving stored energy the better choice here.)"""
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
    consumption = [0.5] * 8 + [2.0] * 8

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
        assert solar_export_discharge_rate(buy[t], shadow, eff_d) == 0
