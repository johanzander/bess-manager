#!/usr/bin/env python3
"""Reproduce and diagnose #275's "Worse" scenario directly via
optimize_battery_schedule -- no mock-HA/podman stack needed.

Background: #275 reported that the DP holds battery charge past midnight and
sells it the next day at a known-worse price once a real 2-day price horizon
is in view. #276/#282 assumed this was a fixed-grid discretization/
interpolation artifact in the DP's value function. Direct investigation
(see docs/superpowers/specs/2026-07-12-issue-275-root-cause-investigation.md)
found that assumption doesn't hold up:

1. Sweeping SOE_STEP_KWH 20x finer (0.05 -> 0.0025) doesn't change the
   held-charge behavior -- ruling out discretization/interpolation error.
2. The 2-day joint optimization beats naive myopic day-by-day optimization
   by a wide margin -- the DP is doing something economically sound, not
   something buggy.
3. Tracing the SOE trajectory directly shows the overnight reserve drains to
   within ~0.003 kWh of the floor before the next day's solar arrives -- the
   later "export at a worse price" is fresh next-day solar with no earlier
   selling opportunity, not the carried-over charge.

Usage:
    .venv/bin/python scripts/repro_issue_275_worse_scenario.py
    .venv/bin/python scripts/repro_issue_275_worse_scenario.py --sweep-soe-step
    .venv/bin/python scripts/repro_issue_275_worse_scenario.py --isolate-solar
    .venv/bin/python scripts/repro_issue_275_worse_scenario.py --myopic-vs-joint
    .venv/bin/python scripts/repro_issue_275_worse_scenario.py --verify-mechanism
"""

from __future__ import annotations

import argparse

import core.bess.dp_battery_algorithm as dpalg
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings

# Real data from Frank's debug bundle (#126, exported 2026-07-12 06:07),
# battery/prices matching the design doc's original "Worse" reproduction.
TODAY_SPOT = [
    0.13744,
    0.13188,
    0.12557,
    0.1251,
    0.12288,
    0.12079,
    0.11161,
    0.09978,
    0.06194,
    0.00538,
    -4e-05,
    -0.00024,
    0.0007,
    0.00142,
    0.00124,
    0.00022,
    -0.00144,
    0.00658,
    0.09055,
    0.13151,
    0.14091,
    0.14449,
    0.14493,
    0.13932,
]
DULL_RATIO = 0.114 / 0.14493  # "Worse" scenario: tomorrow's peak dulled ~21%
TOMORROW_SPOT = [p * DULL_RATIO for p in TODAY_SPOT]

TODAY_SOLAR_HOURLY = [
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.005,
    0.269,
    0.912,
    1.671,
    2.416,
    3.042,
    3.512,
    3.804,
    3.901,
    3.815,
    3.534,
    3.143,
    2.632,
    1.983,
    1.272,
    0.62,
    0.112,
    0.0,
    0.0,
]
TOMORROW_SOLAR_HOURLY = [
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.004,
    0.314,
    0.939,
    1.704,
    2.463,
    3.088,
    3.592,
    3.916,
    4.023,
    3.935,
    3.672,
    3.175,
    2.545,
    1.866,
    1.147,
    0.475,
    0.054,
    0.0,
    0.0,
]

HOME_CONSUMPTION_HOURLY_AVG = 0.5167  # Frank's real historical average (kWh/h)


def buy(spot: float) -> float:
    """Luminus Dynamic contract formula (Frank's real tariff, from #126)."""
    return (spot * 1.0175 + 0.1984) * 1.06


def sell(spot: float) -> float:
    return spot * 1.018 - 0.012685


def expand_quarterly(hourly: list[float]) -> list[float]:
    """Matches entsoe_source._expand_to_quarterly: repeat each hourly value 4x."""
    out: list[float] = []
    for p in hourly:
        out.extend([p] * 4)
    return out


def make_battery_settings(cycle_cost: float = 0.035) -> BatterySettings:
    return BatterySettings(
        total_capacity=15.0,
        min_soc=47.0,
        max_soc=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=0.97,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=cycle_cost,
    )


def make_prices() -> tuple[list[float], list[float]]:
    all_spot = expand_quarterly(TODAY_SPOT) + expand_quarterly(TOMORROW_SPOT)
    return [buy(s) for s in all_spot], [sell(s) for s in all_spot]


def make_solar(today_on: bool, tomorrow_on: bool) -> list[float]:
    today = (
        expand_quarterly([s / 4.0 for s in TODAY_SOLAR_HOURLY])
        if today_on
        else [0.0] * 96
    )
    tomorrow = (
        expand_quarterly([s / 4.0 for s in TOMORROW_SOLAR_HOURLY])
        if tomorrow_on
        else [0.0] * 96
    )
    return today + tomorrow


def run_baseline():
    buy_prices, sell_prices = make_prices()
    solar_production = make_solar(True, True)
    home_consumption = [HOME_CONSUMPTION_HOURLY_AVG / 4.0] * 192
    battery_settings = make_battery_settings()

    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        solar_production=solar_production,
        period_duration_hours=0.25,
        terminal_value_per_kwh=0.0,
    )
    print(
        f"{'p':>3} {'day':>8} {'hh:mm':>6} {'sell':>7} {'action':>8} {'intent':>15} {'soe_end':>8} {'export':>7}"
    )
    for pd in result.period_data:
        p = pd.period
        day = "today" if p < 96 else "tomorrow"
        within = p % 96
        hh, mm = within // 4, (within % 4) * 15
        action = pd.decision.battery_action or 0.0
        if abs(action) > 1e-6 or pd.decision.strategic_intent not in (
            "IDLE",
            "SOLAR_EXPORT",
        ):
            print(
                f"{p:3d} {day:>8} {hh:02d}:{mm:02d} {sell_prices[p]:7.4f} {action:8.3f} "
                f"{pd.decision.strategic_intent:>15} {pd.energy.battery_soe_end:8.3f} {pd.energy.grid_exported:7.3f}"
            )
    print()
    print("Total cost:", result.economic_summary.battery_solar_cost)
    print("SOE at 23:45 tonight (p=95):", result.period_data[95].energy.battery_soe_end)
    print("Floor (min_soe_kwh):", battery_settings.min_soe_kwh)


def sweep_soe_step():
    buy_prices, sell_prices = make_prices()
    solar_production = make_solar(True, True)
    home_consumption = [HOME_CONSUMPTION_HOURLY_AVG / 4.0] * 192
    battery_settings = make_battery_settings()

    for soe_step in [0.05, 0.025, 0.01, 0.005, 0.0025]:
        dpalg.SOE_STEP_KWH = soe_step
        result = optimize_battery_schedule(
            buy_price=buy_prices,
            sell_price=sell_prices,
            home_consumption=home_consumption,
            battery_settings=battery_settings,
            solar_production=solar_production,
            period_duration_hours=0.25,
            terminal_value_per_kwh=0.0,
        )
        soe = result.period_data[95].energy.battery_soe_end
        cost = result.economic_summary.battery_solar_cost
        print(
            f"SOE_STEP_KWH={soe_step:.4f}  SOE@23:45={soe:.4f} kWh  "
            f"held={soe - battery_settings.min_soe_kwh:.4f}  total_cost={cost:.6f}"
        )


def isolate_solar():
    buy_prices, sell_prices = make_prices()
    home_consumption = [HOME_CONSUMPTION_HOURLY_AVG / 4.0] * 192

    def run(name, today_on, tomorrow_on, cycle_cost):
        battery_settings = make_battery_settings(cycle_cost)
        solar_production = make_solar(today_on, tomorrow_on)
        result = optimize_battery_schedule(
            buy_price=buy_prices,
            sell_price=sell_prices,
            home_consumption=home_consumption,
            battery_settings=battery_settings,
            solar_production=solar_production,
            period_duration_hours=0.25,
            terminal_value_per_kwh=0.0,
        )
        soe = result.period_data[95].energy.battery_soe_end
        tonight_disch = sum(
            pd.energy.battery_discharged for pd in result.period_data[80:96]
        )
        tonight_exp = sum(pd.energy.grid_exported for pd in result.period_data[80:96])
        tmrw_disch = sum(
            pd.energy.battery_discharged for pd in result.period_data[180:192]
        )
        tmrw_exp = sum(pd.energy.grid_exported for pd in result.period_data[180:192])
        print(
            f"{name:35s} SOE@23:45={soe:7.3f} held={soe - battery_settings.min_soe_kwh:6.3f}  "
            f"tonight[disch/exp]={tonight_disch:5.2f}/{tonight_exp:5.2f}  "
            f"tmrwEve[disch/exp]={tmrw_disch:5.2f}/{tmrw_exp:5.2f}  "
            f"cost={result.economic_summary.battery_solar_cost:8.4f}"
        )

    run("baseline (solar both days)", True, True, 0.035)
    run("no solar at all", False, False, 0.035)
    run("solar TODAY only", True, False, 0.035)
    run("solar TOMORROW only", False, True, 0.035)
    run("solar both days, cycle_cost=0", True, True, 0.0)


def myopic_vs_joint():
    buy_prices, sell_prices = make_prices()
    solar_production = make_solar(True, True)
    home_consumption = [HOME_CONSUMPTION_HOURLY_AVG / 4.0] * 192
    battery_settings = make_battery_settings()

    joint = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        solar_production=solar_production,
        period_duration_hours=0.25,
        terminal_value_per_kwh=0.0,
    )
    today_only = optimize_battery_schedule(
        buy_price=buy_prices[:96],
        sell_price=sell_prices[:96],
        home_consumption=home_consumption[:96],
        battery_settings=battery_settings,
        solar_production=solar_production[:96],
        period_duration_hours=0.25,
        terminal_value_per_kwh=0.0,
    )
    tomorrow_only = optimize_battery_schedule(
        buy_price=buy_prices[96:],
        sell_price=sell_prices[96:],
        home_consumption=home_consumption[96:],
        battery_settings=battery_settings,
        solar_production=solar_production[96:],
        period_duration_hours=0.25,
        terminal_value_per_kwh=0.0,
        initial_soe=today_only.period_data[95].energy.battery_soe_end,
    )
    joint_cost = joint.economic_summary.battery_solar_cost
    myopic_total = (
        today_only.economic_summary.battery_solar_cost
        + tomorrow_only.economic_summary.battery_solar_cost
    )

    print(f"Joint 2-day optimization total cost: {joint_cost:.6f}")
    print(f"Myopic today-alone + tomorrow-alone:  {myopic_total:.6f}")
    print(
        f"Joint - Myopic = {joint_cost - myopic_total:.6f}  "
        f"({'JOINT IS WORSE -- BUG' if joint_cost > myopic_total + 1e-6 else 'joint at least as good (no bug via this test)'})"
    )


def verify_mechanism():
    buy_prices, sell_prices = make_prices()
    solar_production = make_solar(True, True)
    home_consumption = [HOME_CONSUMPTION_HOURLY_AVG / 4.0] * 192
    battery_settings = make_battery_settings()

    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        solar_production=solar_production,
        period_duration_hours=0.25,
        terminal_value_per_kwh=0.0,
    )
    window = result.period_data[96:136]
    min_soe = min(pd.energy.battery_soe_end for pd in window)
    min_p = next(pd.period for pd in window if pd.energy.battery_soe_end == min_soe)
    print(
        f"Min SOE between midnight and solar arrival: {min_soe:.4f} kWh at period {min_p} "
        f"(floor={battery_settings.min_soe_kwh}, gap={min_soe - battery_settings.min_soe_kwh:.4f})"
    )
    print()
    print("SOE trajectory 00:00 -> solar arrival (hourly):")
    for pd in result.period_data[96:128]:
        if pd.period % 4 == 0:
            hh = (pd.period % 96) // 4
            print(
                f"  p={pd.period:3d} ({hh:02d}:00)  soe_end={pd.energy.battery_soe_end:7.3f}  "
                f"intent={pd.decision.strategic_intent}"
            )
    print()
    print(
        "Total export tomorrow evening (180-191):",
        sum(pd.energy.grid_exported for pd in result.period_data[180:192]),
    )
    print(
        "Total solar captured midday tomorrow (136-146):",
        sum(pd.energy.battery_charged for pd in result.period_data[136:147]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-soe-step", action="store_true")
    parser.add_argument("--isolate-solar", action="store_true")
    parser.add_argument("--myopic-vs-joint", action="store_true")
    parser.add_argument("--verify-mechanism", action="store_true")
    args = parser.parse_args()

    if args.sweep_soe_step:
        sweep_soe_step()
    elif args.isolate_solar:
        isolate_solar()
    elif args.myopic_vs_joint:
        myopic_vs_joint()
    elif args.verify_mechanism:
        verify_mechanism()
    else:
        run_baseline()


if __name__ == "__main__":
    main()
