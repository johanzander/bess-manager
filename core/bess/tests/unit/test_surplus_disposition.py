"""Characterization + target behaviour for binary solar-surplus disposition.
Issue #145. Tests in the CURRENT section document today's behaviour and will be
updated to the target behaviour in Task 2/3 (the change is intentional)."""

from core.bess.dp_battery_algorithm import _state_transition
from core.bess.tests.helpers import make_battery_settings

DT = 0.25
PRICES_BUY = [1.0]
PRICES_SELL = [0.8]


def test_current_idle_passively_stores_surplus():
    """CURRENT: idle (power=0) stores surplus solar (to be changed in Task 2)."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    # surplus = 1.5 - 0.1 = 1.4 kWh; idle currently stores it
    next_soe = _state_transition(
        5.0, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    assert next_soe > 5.0  # battery charged passively (current behaviour)
