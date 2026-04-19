"""
Reproduction test for GitHub issue #73.

The DP optimizer should prefer SOLAR_STORAGE over IDLE during high-solar
periods when evening buy prices are significantly higher than the sell price.
Storing free solar for later use is economically superior to exporting at
the lower sell price.

This test uses data from a real user's debug log (Octopus Agile, UK, MIN inverter,
10 kWh battery) where the optimizer incorrectly chose IDLE for all solar periods
and then scheduled GRID_CHARGING later.
"""

import logging

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings

logger = logging.getLogger(__name__)


def test_solar_storage_preferred_over_idle_when_profitable():
    """The optimizer should store free solar rather than export it when future
    buy prices make storage more valuable than immediate export revenue.

    User scenario: Octopus Agile UK tariff with sell=0.12, midday buy~0.08,
    evening buy~0.33. With 44 kWh solar forecast and low consumption, the
    optimizer should charge the battery from solar during the day for evening
    discharge — not leave it idle and then grid-charge later.
    """
    # From user's debug log (period 35 optimization, 57-period horizon)
    # These are the remaining periods from 08:45 to end of day (15-min resolution)
    buy_price = [
        0.12873,  # 08:45
        0.10164,
        0.10164,  # 09:00-09:15
        0.09492,
        0.09492,  # 09:30-09:45
        0.09303,
        0.09303,  # 10:00-10:15
        0.09261,
        0.09261,  # 10:30-10:45
        0.08253,
        0.08253,  # 11:00-11:15
        0.07896,
        0.07896,  # 11:30-11:45
        0.08043,
        0.08043,  # 12:00-12:15
        0.080745,
        0.080745,  # 12:30-12:45
        0.08463,
        0.08463,  # 13:00-13:15
        0.08316,
        0.08316,  # 13:30-13:45
        0.08463,
        0.08463,  # 14:00-14:15
        0.09513,
        0.09513,  # 14:30-14:45
        0.11613,
        0.11613,  # 15:00-15:15
        0.12936,
        0.12936,  # 15:30-15:45
        0.298305,
        0.298305,  # 16:00-16:15
        0.32004,
        0.32004,  # 16:30-16:45
        0.323505,
        0.323505,  # 17:00-17:15
        0.32823,
        0.32823,  # 17:30-17:45
        0.33705,
        0.33705,  # 18:00-18:15
        0.34713,
        0.34713,  # 18:30-18:45
        0.20286,
        0.20286,  # 19:00-19:15
        0.21063,
        0.21063,  # 19:30-19:45
        0.2163,
        0.2163,  # 20:00-20:15
        0.21378,
        0.21378,  # 20:30-20:45
        0.218295,
        0.218295,  # 21:00-21:15
        0.20349,
        0.20349,  # 21:30-21:45
        0.20643,
        0.20643,  # 22:00-22:15
        0.178185,
        0.178185,  # 22:30-22:45
    ]

    sell_price = [0.12] * len(buy_price)

    # Solar forecast from Solcast (quarterly, kWh per 15-min period)
    solar_production = [
        0.698375,  # 08:45
        1.0926,
        1.0926,  # 09:00-09:15
        1.0926,
        1.0926,  # 09:30-09:45
        1.379275,
        1.379275,  # 10:00-10:15
        1.379275,
        1.379275,  # 10:30-10:45
        1.5195,
        1.5195,  # 11:00-11:15
        1.5195,
        1.5195,  # 11:30-11:45
        1.469275,
        1.469275,  # 12:00-12:15
        1.469275,
        1.469275,  # 12:30-12:45
        1.32075,
        1.32075,  # 13:00-13:15
        1.32075,
        1.32075,  # 13:30-13:45
        1.15855,
        1.15855,  # 14:00-14:15
        1.15855,
        1.15855,  # 14:30-14:45
        0.90805,
        0.90805,  # 15:00-15:15
        0.90805,
        0.90805,  # 15:30-15:45
        0.62475,
        0.62475,  # 16:00-16:15
        0.62475,
        0.62475,  # 16:30-16:45
        0.3919,
        0.3919,  # 17:00-17:15
        0.3919,
        0.3919,  # 17:30-17:45
        0.1776,
        0.1776,  # 18:00-18:15
        0.1776,
        0.1776,  # 18:30-18:45
        0.033225,
        0.033225,  # 19:00-19:15
        0.033225,
        0.033225,  # 19:30-19:45
        0.0,
        0.0,  # 20:00-20:15
        0.0,
        0.0,  # 20:30-20:45
        0.0,
        0.0,  # 21:00-21:15
        0.0,
        0.0,  # 21:30-21:45
        0.0,
        0.0,  # 22:00-22:15
        0.0,
        0.0,  # 22:30-22:45
    ]

    # Home consumption from InfluxDB 7-day average (kWh per 15-min period)
    home_consumption = [
        0.31871,  # 08:45
        0.26493,
        0.27447,  # 09:00-09:15
        0.23888,
        0.21702,  # 09:30-09:45
        0.23066,
        0.21604,  # 10:00-10:15
        0.25731,
        0.21763,  # 10:30-10:45
        0.27646,
        0.26145,  # 11:00-11:15
        0.22344,
        0.32047,  # 11:30-11:45
        0.22240,
        0.21479,  # 12:00-12:15
        0.27067,
        0.31200,  # 12:30-12:45
        0.33609,
        0.16526,  # 13:00-13:15
        0.24122,
        0.22048,  # 13:30-13:45
        0.22361,
        0.21192,  # 14:00-14:15
        0.36199,
        0.31134,  # 14:30-14:45
        0.24229,
        0.30431,  # 15:00-15:15
        0.18593,
        0.17477,  # 15:30-15:45
        0.14856,
        0.15732,  # 16:00-16:15
        0.14972,
        0.14982,  # 16:30-16:45
        0.12936,
        0.11860,  # 17:00-17:15
        0.11519,
        0.17847,  # 17:30-17:45
        0.32470,
        0.25986,  # 18:00-18:15
        0.34569,
        0.20779,  # 18:30-18:45
        0.32485,
        0.26015,  # 19:00-19:15
        0.18954,
        0.22907,  # 19:30-19:45
        0.17239,
        0.22497,  # 20:00-20:15
        0.15774,
        0.17475,  # 20:30-20:45
        0.18514,
        0.18529,  # 21:00-21:15
        0.18036,
        0.19174,  # 21:30-21:45
        0.14576,
        0.11838,  # 22:00-22:15
        0.11020,
        0.09923,  # 22:30-22:45
    ]

    battery_settings = BatterySettings(
        total_capacity=10.0,
        min_soc=10,
        max_soc=100,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=0.97,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.02,
    )

    initial_soe = 2.9  # From debug log at period 35

    result = optimize_battery_schedule(
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        period_duration_hours=0.25,
        currency="GBP",
    )

    # Analyze what the optimizer chose
    solar_periods_with_excess = []
    for i, pd in enumerate(result.period_data):
        excess = solar_production[i] - home_consumption[i]
        if excess > 0.3:  # Significant excess solar
            solar_periods_with_excess.append(
                (i, pd.decision.strategic_intent, excess, buy_price[i])
            )
            logger.info(
                f"Period {i}: intent={pd.decision.strategic_intent}, "
                f"excess_solar={excess:.2f} kWh, buy={buy_price[i]:.4f}, "
                f"SOE={pd.energy.battery_soe_start:.1f}→{pd.energy.battery_soe_end:.1f}"
            )

    # Count how many high-solar periods chose SOLAR_STORAGE vs IDLE
    solar_storage_count = sum(
        1 for _, intent, _, _ in solar_periods_with_excess if intent == "SOLAR_STORAGE"
    )
    idle_count = sum(
        1 for _, intent, _, _ in solar_periods_with_excess if intent == "IDLE"
    )
    grid_charging_count = sum(
        1
        for pd in result.period_data
        if pd.decision.strategic_intent == "GRID_CHARGING"
    )

    logger.info(
        f"High-solar periods: {len(solar_periods_with_excess)} total, "
        f"{solar_storage_count} SOLAR_STORAGE, {idle_count} IDLE"
    )
    logger.info(f"GRID_CHARGING periods: {grid_charging_count}")

    # The optimizer should choose SOLAR_STORAGE for at least some high-solar
    # periods rather than leaving the battery idle and grid-charging later.
    # With sell=0.12 and evening buy=0.20-0.35, storing free solar is clearly
    # more valuable than exporting it.
    assert solar_storage_count > 0, (
        f"Optimizer chose IDLE for all {len(solar_periods_with_excess)} high-solar "
        f"periods and scheduled {grid_charging_count} GRID_CHARGING periods. "
        f"Free solar storage should be preferred over grid export at 0.12 GBP "
        f"when evening prices reach 0.20-0.35 GBP."
    )

    # If the optimizer correctly stores solar, it should NOT need grid charging
    # (or need very little) since solar can fill the battery for free.
    assert grid_charging_count == 0, (
        f"Optimizer scheduled {grid_charging_count} GRID_CHARGING periods despite "
        f"abundant free solar available for storage. Grid charging should be "
        f"unnecessary with this solar forecast."
    )
