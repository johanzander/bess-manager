#!/usr/bin/env python3
"""Score the DP's terminal knee against what a house actually drew overnight.

#687 made the terminal value concave: `head_rate` up to `knee_kwh`, `tail_rate`
above. Because the head rate sits well above the tail, the planned midnight SOE
comes out at `min_soe + knee` -- so the knee *is* the carry, and any error in it
passes through one-for-one. Nothing else measures whether that quantity is right.

This reads a debug bundle, rebuilds the forecast production actually held from
the same captured inputs (`ha_statistics` long-term statistics and the Solcast
`detailedHourly` attribute), computes the knee production would have derived,
and scores it against the night the bundle metered.

Method, stated plainly because it is easy to get wrong: this is an out-of-sample
backtest, not a replay. The statistics window ends at the bundle's own midnight
(`_fetch_ha_statistics_raw` queries `[today-7, today)`), so it never contains the
night being scored -- but it is one day fresher than the window the real plan for
that night used, which makes the test mildly *generous* to the forecast. The
first version of this analysis fed measured actuals in as the forecast and
"validated" the knee against the same data it was built from; the resulting
figure was wrong by ten points of SOC. Building the forecast side from anything
other than production's own inputs measures nothing.

Usage:
    scripts/knee_oracle.py BUNDLE.md --capacity 15 --min-soe 1.8
    scripts/knee_oracle.py BUNDLE.md --capacity 15 --min-soe 1.8 --profile p75
"""

import argparse
import json
import re
import statistics
import sys
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.bess.battery_system_manager import (
    ha_statistics_quarterly_profile,
)
from core.bess.ha_api_controller import (
    solcast_detailed_hourly_to_quarterly,
)
from core.bess.terminal_value import pv_covers_load
from core.bess.time_utils import TIMEZONE

# `pv_covers_load` rejects the `0.0 >= 0.0` reading of a no-load period (#715),
# which is enough for a forecast. Metered data needs one thing more: a
# quantization tie (0.1 vs 0.1, with solar back to 0.0 the next quarter) is a
# real load meeting real PV and passes the predicate, yet reads sunrise ~30
# minutes early. Requiring coverage sustained across two consecutive periods is
# what "the sun took over" means on a meter. Scoped to the oracle on purpose:
# production forecasts are smooth and have no such ties, so this is about
# scoring honestly, not a shape the production scan should copy.
_SUSTAINED_PERIODS = 2


def _embedded_json(text: str, header: str, stop: str) -> Any:
    """First ```json block between two section headers of a debug bundle."""
    start = text.index(header)
    end = text.index(stop, start)
    match = re.search(r"```json\n(.*?)\n```", text[start:end], re.S)
    if match is None:
        raise SystemExit(f"no JSON block found under {header!r}")
    return json.loads(match.group(1))


def p75_quarterly_profile(stats: list[dict], tz: tzinfo) -> tuple[list[float], int]:
    """P75-per-hour variant, for comparing a reserve margin against the mean.

    Not a better predictor -- measured across the nights in a bundle it tends
    to *over*-forecast. It is a deliberate margin, justified by the asymmetry
    between the head and tail rates rather than by accuracy (#381).
    """
    buckets: dict[int, list[float]] = {h: [] for h in range(24)}
    for entry in stats:
        change, start = entry.get("change"), entry.get("start")
        if change is None or start is None:
            continue
        ts = start / 1000 if start > 1e12 else start
        hour = datetime.fromtimestamp(ts, tz=UTC).astimezone(tz).hour
        buckets[hour].append(float(change))

    hourly = [0.0] * 24
    hours_with_data = 0
    for hour in range(24):
        values = sorted(buckets[hour])
        if values:
            hourly[hour] = (
                statistics.quantiles(values, n=4, method="inclusive")[2]
                if len(values) > 1
                else values[0]
            )
            hours_with_data += 1
    return [v / 4.0 for v in hourly for _ in range(4)], hours_with_data


def knee_from_forecast(
    consumption: list[float], solar: list[float], efficiency_discharge: float
) -> tuple[float, int | None]:
    """`knee_kwh_from_forecast`'s scan, reporting where it stopped.

    The production function returns only the quantity; the crossover index is
    what makes a miss legible as timing rather than level, so the scan is
    repeated here. The *decision* is not repeated -- `pv_covers_load` is
    imported, so a change to what counts as a crossover reaches the oracle
    without anyone remembering to update it. A local copy of that predicate is
    how a harness comes to grade a scan production no longer runs.
    """
    net = 0.0
    for index, (consumed, produced) in enumerate(zip(consumption, solar, strict=False)):
        if consumed <= 0:
            continue  # no forecast load: a data gap, not a period (#715)
        if pv_covers_load(consumed, produced):
            return net / efficiency_discharge, index
        net += consumed - produced
    return net / efficiency_discharge, None


def oracle_knee(
    consumption: list[float], solar: list[float], efficiency_discharge: float
) -> tuple[float, int | None]:
    """What the house really needed from storage before the sun took over."""
    net = 0.0
    for index, (consumed, produced) in enumerate(zip(consumption, solar, strict=False)):
        covered = [
            pv_covers_load(consumed_n, produced_n)
            for consumed_n, produced_n in zip(
                consumption[index : index + _SUSTAINED_PERIODS],
                solar[index : index + _SUSTAINED_PERIODS],
                strict=False,
            )
        ]
        if len(covered) == _SUSTAINED_PERIODS and all(covered):
            return net / efficiency_discharge, index
        if consumed <= 0:
            continue  # metered no-load quarter: a gap, same as the forecast side
        net += consumed - produced
    return net / efficiency_discharge, None


def _hhmm(index: int | None) -> str:
    return "never" if index is None else f"{index // 4:02d}:{(index % 4) * 15:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="debug export (.md)")
    parser.add_argument("--capacity", type=float, required=True, help="pack kWh")
    parser.add_argument("--min-soe", type=float, required=True, help="floor kWh")
    parser.add_argument("--efficiency-discharge", type=float, default=0.95)
    parser.add_argument(
        "--profile",
        choices=("trimmed", "p75"),
        default="trimmed",
        help="trimmed = what ships; p75 = the reserve-margin variant",
    )
    args = parser.parse_args()

    text = args.bundle.read_text()
    stats = _embedded_json(text, "## HA Statistics", "## Inverter TOU")["stats"]
    entities = _embedded_json(text, "## Entity Snapshot", "## HA Statistics")

    # Solcast "today", not "tomorrow": the bundle carries today's meter, so
    # today's forecast is the one that can be scored against an outcome. The
    # consumption profile is a time-of-day shape with no notion of which day it
    # describes, so it needs no such choice.
    try:
        solar_key = next(
            key
            for key in entities
            if "solcast" in key and ("vandaag" in key or "today" in key)
        )
    except StopIteration:
        raise SystemExit("no Solcast today-forecast entity in this bundle") from None

    builder = (
        p75_quarterly_profile
        if args.profile == "p75"
        else ha_statistics_quarterly_profile
    )
    consumption_forecast, hours_with_data = builder(stats, TIMEZONE)
    if hours_with_data < 12:
        raise SystemExit(
            f"only {hours_with_data}/24 hours have statistics -- production would "
            "have fallen back to the fixed profile here, so there is no knee to score"
        )
    solar_forecast = solcast_detailed_hourly_to_quarterly(
        entities[solar_key]["attributes"]["detailedHourly"]
    )

    history = [
        period
        for period in _embedded_json(
            text, "## Historical Sensor Data", "## Previous Days"
        )
        if period and period.get("energy")
    ]
    consumption_actual = [p["energy"]["home_consumption"] for p in history]
    solar_actual = [p["energy"]["solar_production"] for p in history]

    forecast_knee, forecast_crossover = knee_from_forecast(
        consumption_forecast, solar_forecast, args.efficiency_discharge
    )
    measured_knee, measured_crossover = oracle_knee(
        consumption_actual, solar_actual, args.efficiency_discharge
    )

    if measured_crossover is None:
        raise SystemExit(
            f"this bundle has {len(history)} periods of actuals and no PV crossover "
            "in them -- it was exported before the sun took over, so the overnight "
            "sum is censored and cannot be scored. Capture one after sunrise."
        )

    capacity: float = args.capacity

    def as_soc(kwh: float) -> float:
        return 100.0 * kwh / capacity

    planned = args.min_soe + forecast_knee
    ideal = args.min_soe + measured_knee
    print(f"{args.bundle.name}  ({args.profile} profile)")
    print(
        f"  forecast knee  {forecast_knee:6.2f} kWh   PV crossover {_hhmm(forecast_crossover)}"
    )
    print(
        f"  measured knee  {measured_knee:6.2f} kWh   PV crossover {_hhmm(measured_crossover)}"
    )
    print(
        f"  error          {forecast_knee - measured_knee:+6.2f} kWh "
        f"({100 * (forecast_knee - measured_knee) / measured_knee:+.0f}%)"
    )
    print(
        f"  midnight SOE   planned {planned:.2f} kWh ({as_soc(planned):.1f}%)   "
        f"needed {ideal:.2f} kWh ({as_soc(ideal):.1f}%)"
    )

    window = measured_crossover
    forecast_over_window = (
        sum(consumption_forecast[:window]) - sum(solar_forecast[:window])
    ) / args.efficiency_discharge
    print(f"\n  decomposition over 00:00-{_hhmm(window)}:")
    print(f"    forecast net load {forecast_over_window:6.2f} kWh")
    print(f"    measured net load {measured_knee:6.2f} kWh")
    print(f"    level error       {forecast_over_window - measured_knee:+6.2f} kWh")
    print(
        f"    timing error      {forecast_knee - forecast_over_window:+6.2f} kWh "
        f"(forecast sunrise {_hhmm(forecast_crossover)} vs actual {_hhmm(measured_crossover)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
