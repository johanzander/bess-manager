#!/usr/bin/env python3
"""Measure what every `grid_first` export period commits the inverter to (#352).

Re-derives the two tables in
`docs/superpowers/specs/2026-08-11-phase4-executable-candidates-design.md`:
section 2 (which criterion produces the 22/16 figure, and why the "0" was
vacuous) and section 5 (D3's predicate sweep). Kept under `scripts/` rather
than thrown away because both numbers are cited as justification for Phase 4b
and have already been mis-measured once.

What it measures, and what it cannot
------------------------------------
A BATTERY_EXPORT period is written to load-following hardware as `grid_first`
at a rate scaled from the planned action. `grid_first` does not load-follow, so
that rate is a commitment for the whole period: any in-period load above it is
imported at the buy price.

The corpus cannot show that import. Its fixtures are 15-minute *point*
forecasts, so load never exceeds the period average by construction, and
planned import inside an export period is identically zero. What is measurable
is the **commitment**: the load-following headroom the plan gives up, and the
export revenue it gives it up for.

Usage: PYTHONPATH=. .venv/bin/python scripts/measure_export_commitment.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.bess.dp_battery_algorithm import optimize_battery_schedule  # noqa: E402
from core.bess.tests.helpers import _scenario_inputs  # noqa: E402
from core.bess.tests.unit.golden_capture import DATA_DIR, fixture_names  # noqa: E402

BAND = (0.1, 0.5)  # the export band #511's executability filter does not reach
REPRO = ("regression_2026_08_12_202906", 99)  # the #352 reproduction period
LATTICE_STEP_FRACTION = 0.01  # one percent-lattice gear -- "already flat out"


def collect() -> list[dict]:
    """One row per BATTERY_EXPORT period across the whole fixture corpus."""
    rows = []
    for name in fixture_names():
        scenario = json.loads((DATA_DIR / f"{name}.json").read_text())
        inputs = _scenario_inputs(scenario)
        result = optimize_battery_schedule(**inputs)
        dt = inputs["period_duration_hours"]
        max_discharge_kwh = inputs["battery_settings"].max_discharge_power_kw * dt
        buy, sell = inputs["buy_price"], inputs["sell_price"]

        for i, period in enumerate(result.period_data):
            if period.decision.strategic_intent != "BATTERY_EXPORT":
                continue
            e = period.energy
            rows.append(
                {
                    "fixture": name,
                    "period": i,
                    "dt": dt,
                    "discharged": e.battery_discharged,
                    "export": e.battery_to_grid,
                    "battery_to_home": e.battery_to_home,
                    "home": e.home_consumption,
                    "deficit": max(0.0, e.home_consumption - e.solar_production),
                    "headroom": max(0.0, max_discharge_kwh - e.battery_discharged),
                    "max_discharge": max_discharge_kwh,
                    "benefit": sell[i] * e.battery_to_grid,
                    "buy": buy[i],
                    "sell": sell[i],
                }
            )
    return rows


def admits(row: dict) -> bool:
    """D3 as decided 2026-08-14: is the period MOSTLY ABOUT EXPORTING?

    An export command commits the inverter for the whole period, so it is
    admissible only when the export is the point of the period rather than a
    by-product of covering the house -- or when the battery is already flat
    out, where there is no load-following capacity left to protect and
    demoting would forgo revenue for nothing (#354's live-E2E lesson).

    No invented constants: "mostly" is the 50/50 split, and "flat out" is the
    top of the platform's own percent lattice.
    """
    flat_out = row["headroom"] <= LATTICE_STEP_FRACTION * row["max_discharge"]
    return row["export"] > row["battery_to_home"] or flat_out


def main() -> None:
    rows = collect()
    n = len(rows)
    in_band = lambda r: BAND[0] <= r["export"] <= BAND[1]  # noqa: E731

    print(f"corpus: {len(fixture_names())} fixtures, {n} BATTERY_EXPORT periods")
    print(
        f"planned export {sum(r['export'] for r in rows):.1f} kWh | "
        f"revenue {sum(r['benefit'] for r in rows):.1f} SEK | "
        f"headroom forfeited {sum(r['headroom'] for r in rows):.1f} kWh | "
        f"full-rate periods {sum(1 for r in rows if r['headroom'] <= 1e-9)}"
    )

    print("\n=== section 2: which criterion is being counted ===")
    criteria = {
        "discharge < home (the 22/16 figure)": lambda r: r["discharged"] < r["home"],
        "export < deficit (home-dominant)": lambda r: r["export"] < r["deficit"],
        "headroom > export": lambda r: r["headroom"] > r["export"],
        "#354 two-sided (both readings)": lambda r: (
            r["battery_to_home"] > r["export"] and r["headroom"] > r["export"]
        ),
        "discharge < deficit (VACUOUS)": lambda r: r["discharged"] < r["deficit"],
    }
    print(f"{'criterion':<38} {'count':>6} {'in band':>9}")
    for label, hit in criteria.items():
        sel = [r for r in rows if hit(r)]
        print(f"{label:<38} {len(sel):>6} {sum(1 for r in sel if in_band(r)):>9}")
    print("\n  The last row is 0 by construction, not by evidence:")
    print("  EnergyData._calculate_detailed_flows sets battery_to_home =")
    print("  min(discharged, home - solar), so any export requires discharge")
    print("  above the deficit. A zero there measures an identity.")

    print("\n=== section 5: D3, the decided rule ===")
    rejected = [r for r in rows if not admits(r)]
    total_rev = sum(r["benefit"] for r in rows)
    total_headroom = sum(r["headroom"] for r in rows)
    print(f"  refused {len(rejected)} of {n} grid_first commands")
    print(
        f"  export revenue refused : {sum(r['benefit'] for r in rejected):7.2f} SEK "
        f"of {total_rev:.2f} ({sum(r['benefit'] for r in rejected) / total_rev:.1%})"
    )
    print(
        f"  headroom no longer committed: "
        f"{sum(r['headroom'] for r in rejected):7.1f} kWh of {total_headroom:.1f}"
    )
    print("\n  NOTE: revenue refused is an UPPER BOUND counted on today's plan.")
    print("  Under 4b the DP re-optimises and recovers most of it -- measured")
    print("  +3.67 SEK corpus-wide (0.14% of savings) in the spike behind D3,")
    print("  which is the figure the design doc records. Re-measure that")
    print("  properly once the filter exists in the selector.")

    # The exemption is load-bearing: quantify what bare dominance would cost.
    bare = [r for r in rows if not (r["export"] > r["battery_to_home"])]
    full_rate = [
        r for r in bare if r["headroom"] <= LATTICE_STEP_FRACTION * r["max_discharge"]
    ]
    print(
        f"\n  without the flat-out exemption it would also refuse "
        f"{len(full_rate)} full-rate periods"
    )
    print(
        f"  carrying {sum(r['benefit'] for r in full_rate):.1f} SEK -- pure loss, "
        f"since a full-rate command has no headroom to protect"
    )

    repro = [r for r in rows if (r["fixture"], r["period"]) == REPRO]
    if not repro:
        raise SystemExit(
            f"#352 reproduction period {REPRO} is no longer a BATTERY_EXPORT "
            "period -- the acceptance criterion it anchors needs re-deriving"
        )
    r = repro[0]
    share = r["export"] / (r["export"] + r["battery_to_home"])
    print(f"\n=== #352 reproduction: {REPRO[0]} p{REPRO[1]} ===")
    print(
        f"  {r['export']:.3f} kWh to the grid vs {r['battery_to_home']:.3f} kWh to "
        f"the house -- export share {share:.0%}, headroom {r['headroom']:.3f} kWh"
    )
    print(f"  -> {'ADMIT' if admits(r) else 'REJECT'} (must be REJECT)")


if __name__ == "__main__":
    main()
