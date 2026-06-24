"""Regression test for GitHub issue #161.

When the battery starts below its configured minimum SOE, IDLE periods must
not be classified as SOLAR_STORAGE. The bug was that _idle_battery_flows
returned a phantom battery_charged value equal to the min-SOE floor clamp
delta, which misled classify_strategic_intent into reporting SOLAR_STORAGE
even at 2 am with no solar production.
"""

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import make_battery_settings

pytestmark = pytest.mark.slow


def test_no_solar_storage_intent_when_initial_soe_below_minimum():
    """IDLE periods must not be SOLAR_STORAGE when there is no solar.

    Scenario: battery starts below min_soe_kwh (2.7 < 3.0 kWh) with flat
    prices and zero solar production all day. Every period the optimizer
    chooses IDLE. Before the fix, the floor clamp (soe 2.7 → 3.0 kWh) was
    counted as battery_charged, triggering SOLAR_STORAGE for each period.
    """
    # min_soe_kwh = 15% of 20 kWh = 3.0 kWh; initial SOE is below that
    bs = make_battery_settings(total_capacity=20.0, min_soc=15.0)
    initial_soe = 2.7  # below min_soe_kwh = 3.0

    solar = [0.0] * 24
    consumption = [0.5] * 24
    buy_price = [0.3] * 24
    sell_price = [0.2] * 24

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=consumption,
        solar_production=solar,
        initial_soe=initial_soe,
        battery_settings=bs,
        period_duration_hours=1.0,
    )

    for pd in result.period_data:
        assert pd.energy.battery_charged == pytest.approx(0.0), (
            f"Period {pd.period}: soe_start={pd.energy.battery_soe_start:.2f} kWh "
            f"with zero solar must not register phantom battery charging"
        )
