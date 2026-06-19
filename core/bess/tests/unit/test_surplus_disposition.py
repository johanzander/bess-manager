"""Characterization + target behaviour for binary solar-surplus disposition.
Issue #145. Tests in the CURRENT section document today's behaviour and will be
updated to the target behaviour in Task 2/3 (the change is intentional)."""

from core.bess.dp_battery_algorithm import _compute_reward, _state_transition
from core.bess.tests.helpers import make_battery_settings

DT = 0.25
PRICES_BUY = [1.0]
PRICES_SELL = [0.8]


def test_idle_exports_surplus_and_holds_battery():
    """TARGET: idle (power=0) is the EXPORT disposition — surplus is exported,
    battery holds (does NOT passively store)."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    next_soe = _state_transition(
        5.0, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    assert next_soe == 5.0  # battery holds; surplus exported, not stored

    reward, _ = _compute_reward(
        power=0.0,
        soe=5.0,
        next_soe=5.0,
        period=0,
        home_consumption=0.1,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.5,
        cost_basis=bs.cycle_cost_per_kwh,
    )
    # surplus 1.4 kWh exported @ 0.8 → reward = +1.4*0.8 = 1.12 (cost = -1.12)
    assert round(reward, 4) == round(1.4 * 0.8, 4)
