"""Generate a mock_ha scenario JSON from a BESS debug log file.

The generated scenario seeds the mock HA server with:
- Battery SOC from the debug log's last optimization initial_soe
- Nordpool prices (today + tomorrow) from input_data.buy_price
- Synthetic solar forecast shaped from input_data.full_solar_production
- Synthetic lifetime sensor values (large stable numbers)
- A flat consumption reading from input_data.full_home_consumption

Usage:
    python scripts/mock_ha/scenarios/from_debug_log.py docs/bess-debug-2026-03-24-225535.md
    # Writes: scripts/mock_ha/scenarios/2026-03-24-225535.json
    # Then:   ./mock-run.sh 2026-03-24-225535

The scenario name is derived from the debug log filename timestamp.
All replay scenarios use bess_config/min.json (no separate config needed).
"""

import json
import re
import sys
from pathlib import Path

# Allow importing from repo root when run as a script
repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(repo_root))

from core.bess.tests.debug_log_parser import parse_debug_log  # noqa: E402


def _quarterly_to_hourly_detail(quarterly: list[float], date_str: str) -> list[dict]:
    """Convert 96 quarterly values to 24 hourly detailedHourly entries (Solcast format)."""
    hourly = []
    for h in range(24):
        # Sum the 4 quarterly periods → hourly kWh
        q_start = h * 4
        total = sum(quarterly[q_start : q_start + 4])
        hourly.append(
            {
                "period_start": f"{date_str}T{h:02d}:00:00+01:00",
                "pv_estimate": round(total, 3),
            }
        )
    return hourly


def generate_scenario(log_path: str) -> None:
    """Parse a debug log and write a scenario JSON file named after its timestamp."""
    log = parse_debug_log(log_path)
    d = log.input_data

    if not d:
        print(f"Error: No input_data found in {log_path}")
        sys.exit(1)

    # Derive output name and mock_time from filename: bess-debug-YYYY-MM-DD-HHMMSS.md
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})(\d{2})", Path(log_path).name)
    if m:
        output_name = f"{m.group(1)}-{m.group(2)}{m.group(3)}{m.group(4)}"
        mock_time = f"@{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
    else:
        output_name = Path(log_path).stem
        mock_time = ""

    buy_prices = d.get("buy_price", [])
    consumption = d.get("full_home_consumption", [])
    solar = d.get("full_solar_production", [0.0] * 192)
    horizon = d.get("horizon", len(buy_prices))
    initial_soe = d.get("initial_soe", 13.5)
    total_capacity = log.battery_settings.get("total_capacity", 30.0)
    initial_soc_pct = round(initial_soe / total_capacity * 100, 1)

    # Use the inverter TOU segments captured from hardware memory (active_tou_intervals).
    # Only enabled segments are exported — disabled slots are not captured because their
    # start/end times depend on what was previously programmed and are not known.
    # The mock will return only these active segments; BESS handles the missing disabled
    # slots gracefully (treats absent slots as cleared during differential update).
    # Old logs without ## Inverter TOU Segments fall back to empty (no segments known).
    time_segments = log.inverter_tou_segments

    opt_period = log.optimization_period
    remaining_today = 96 - opt_period  # how many periods of today remain

    if log.price_data and log.price_data.get("today"):
        # New-style debug log: full raw prices for both days are stored directly.
        today_prices = list(log.price_data["today"])
        tomorrow_prices = list(log.price_data.get("tomorrow", []))
        # Pad to 96 in case of DST-short days
        while len(today_prices) < 96:
            today_prices.append(today_prices[-1] if today_prices else 0.1)
        while len(tomorrow_prices) < 96:
            tomorrow_prices.append(tomorrow_prices[-1] if tomorrow_prices else 0.1)
    else:
        # Old-style debug log: reverse the PriceManager transformation to recover
        # raw Nordpool spot prices from the optimizer's buy_price array.
        # buy_price = (raw + markup_rate) * vat_multiplier + additional_costs
        # → raw = (buy_price - additional_costs) / vat_multiplier - markup_rate
        ps = log.price_settings
        markup_rate = ps.get("markup_rate", 0.08)
        vat_multiplier = ps.get("vat_multiplier", 1.25)
        additional_costs = ps.get("additional_costs", 1.03)

        def _to_raw(buy: float) -> float:
            return (buy - additional_costs) / vat_multiplier - markup_rate

        raw_prices = [_to_raw(p) for p in buy_prices]

        # raw_prices starts at opt_period, not midnight.
        # e.g. opt_period=91 → raw_prices[0..4] are last 5 periods of today (22:45-23:59)
        #                        raw_prices[5..100] are all 96 periods of tomorrow (00:00-23:59)
        today_fill = raw_prices[0] if raw_prices else 0.1
        today_prices = [today_fill] * opt_period + list(raw_prices[:remaining_today])
        tomorrow_prices = list(raw_prices[remaining_today : remaining_today + 96])
        while len(tomorrow_prices) < 96:
            tomorrow_prices.append(tomorrow_prices[-1] if tomorrow_prices else 0.1)

    # Average quarterly consumption → W (for 48h avg sensor)
    avg_quarterly_kwh = (
        sum(consumption[:96]) / len(consumption[:96]) if consumption else 0.8
    )
    avg_consumption_w = round(avg_quarterly_kwh * 4 * 1000, 1)  # kWh/qtr → W

    # Solar: same offset logic as prices — solar[0] is period opt_period, not midnight
    solar_today = [0.0] * opt_period + list(solar[:remaining_today])
    solar_today += [0.0] * (96 - len(solar_today))
    solar_tomorrow = list(solar[remaining_today : remaining_today + 96])
    solar_tomorrow += [0.0] * (96 - len(solar_tomorrow))

    nordpool_entity = "sensor.nordpool_kwh_se4_sek_2_10_025"

    sensors: dict = {
        "sensor.rkm0d7n04x_statement_of_charge_soc": str(initial_soc_pct),
        "number.rkm0d7n04x_battery_charge_soc_limit": "95",
        "number.rkm0d7n04x_battery_discharge_soc_limit": "15",
        "number.rkm0d7n04x_battery_charge_power_limit": "100",
        "number.rkm0d7n04x_battery_discharge_power_limit": "100",
        "switch.rkm0d7n04x_ac_charge": "off",
        "sensor.rkm0d7n04x_internal_wattage": "0",
        "sensor.rkm0d7n04x_local_load_power": str(avg_consumption_w),
        "sensor.rkm0d7n04x_import_power": str(avg_consumption_w),
        "sensor.rkm0d7n04x_export_power": "0",
        "sensor.rkm0d7n04x_battery_1_charging_w": "0",
        "sensor.rkm0d7n04x_battery_1_discharging_w": "0",
        "sensor.rkm0d7n04x_output_power": str(avg_consumption_w),
        "sensor.rkm0d7n04x_self_power": "0",
        "sensor.rkm0d7n04x_system_power": "0",
        "sensor.current_l1_gustavsgatan_32a": "1.2",
        "sensor.current_l2_gustavsgatan_32a": "1.2",
        "sensor.current_l3_gustavsgatan_32a": "1.2",
        "sensor.rkm0d7n04x_lifetime_total_solar_energy": "10000.0",
        "sensor.rkm0d7n04x_lifetime_total_load_consumption": "20000.0",
        "sensor.rkm0d7n04x_lifetime_self_consumption": "8000.0",
        "sensor.rkm0d7n04x_lifetime_import_from_grid": "15000.0",
        "sensor.rkm0d7n04x_lifetime_total_export_to_grid": "3000.0",
        "sensor.rkm0d7n04x_lifetime_total_all_batteries_charged": "5000.0",
        "sensor.rkm0d7n04x_lifetime_total_all_batteries_discharged": "4500.0",
        "sensor.rkm0d7n04x_lifetime_system_production": "10000.0",
        "sensor.zap263668_energy_meter": "500.0",
        "sensor.48h_average_grid_import_power": str(avg_consumption_w),
        nordpool_entity: {
            "state": str(round(today_prices[0], 2)),
            "attributes": {
                "today": [round(p, 4) for p in today_prices],
                "tomorrow": [round(p, 4) for p in tomorrow_prices],
            },
        },
        "sensor.solcast_pv_forecast_forecast_today": {
            "state": str(round(sum(solar_today), 1)),
            "attributes": {
                "detailedHourly": _quarterly_to_hourly_detail(solar_today, "2026-03-24")
            },
        },
        "sensor.solcast_pv_forecast_forecast_tomorrow": {
            "state": str(round(sum(solar_tomorrow), 1)),
            "attributes": {
                "detailedHourly": _quarterly_to_hourly_detail(
                    solar_tomorrow, "2026-03-25"
                )
            },
        },
    }

    # Derive inverter type from schedule structure:
    # MIN produces time_segments; SPH produces ac_charge_times/ac_discharge_times.
    opt_result = log.last_schedule.get("optimization_result", {})
    inverter_type = "sph" if "ac_charge_times" in opt_result else "min"

    scenario = {
        "name": output_name,
        "description": (
            f"Replay scenario generated from {Path(log_path).name}. "
            f"Period {log.optimization_period}, initial_soe={initial_soe:.1f} kWh, "
            f"horizon={horizon}."
        ),
        "inverter_type": inverter_type,
        "bess_config": log.addon_options if log.addon_options else None,
        "sensors": sensors,
        "mock_time": mock_time,
        "time_segments": time_segments if inverter_type == "min" else None,
        "ac_charge_times": [] if inverter_type == "sph" else None,
        "ac_discharge_times": [] if inverter_type == "sph" else None,
    }
    # Remove keys that don't apply to this inverter type or are absent
    scenario = {k: v for k, v in scenario.items() if v is not None}

    if not log.addon_options:
        print(
            "Note: No ## BESS Configuration in log — bess_config will not be embedded. "
            "BESS config must be present in the container from a previous run."
        )

    # Write scenario (named after the debug log timestamp)
    scenarios_dir = Path(__file__).parent
    scenario_path = scenarios_dir / f"{output_name}.json"
    with open(scenario_path, "w") as f:
        json.dump(scenario, f, indent=2)
    print(f"Wrote scenario: {scenario_path}")

    print(f"\nRun:  ./mock-run.sh {output_name}")
    print(f"      initial_soe={initial_soe:.1f} kWh ({initial_soc_pct}% SOC)")
    source = "price_data" if log.price_data else "reversed buy_price (old log)"
    print(
        f"      horizon={horizon} periods, avg_buy={sum(buy_prices[:96])/96:.2f} SEK"
        f", today raw prices: {len(today_prices)} periods (source: {source})"
    )
    if mock_time:
        print(f"      mock_time={mock_time}  (BESS will run as if it is this time)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <debug_log.md>")
        sys.exit(1)

    generate_scenario(sys.argv[1])
