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
D_REF_KW = 2.0  # D3's proposed reference load excursion
REPRO = ("regression_2026_08_12_202906", 99)  # the #352 reproduction period


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
                    "benefit": sell[i] * e.battery_to_grid,
                    "buy": buy[i],
                    "sell": sell[i],
                }
            )
    return rows


def admits(row: dict, d_ref_kw: float) -> bool:
    """D3: the export revenue must cover the import the commitment exposes the
    house to at a reference load excursion of `d_ref_kw`.

    `headroom == 0` (a full-rate export) gives harm 0 and is always admitted --
    there is no load-following behaviour left to protect, so demoting it would
    forgo revenue for nothing. That is #354's live-E2E finding, arriving as
    arithmetic rather than as a special case.
    """
    harm = row["buy"] * min(d_ref_kw * row["dt"], row["headroom"])
    return row["benefit"] >= harm


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

    print(f"\n=== section 5: D3 predicate sweep (proposed D_ref = {D_REF_KW} kW) ===")
    total_rev = sum(r["benefit"] for r in rows)
    print(
        f"{'D_ref':<26} {'rejected':>9} {'revenue given up':>18} {'headroom kept':>15}"
    )
    for d_ref in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 25 * 230 * 3 / 1000):
        rejected = [r for r in rows if not admits(r, d_ref)]
        given_up = sum(r["benefit"] for r in rejected)
        label = f"{d_ref:.1f} kW" + (" (house fuse)" if d_ref > 10 else "")
        print(
            f"{label:<26} {len(rejected):>4} /{n:<4} "
            f"{given_up:>10.2f} SEK ({given_up / total_rev:>4.1%}) "
            f"{sum(r['headroom'] for r in rejected):>12.1f} kWh"
        )

    # #354's rule, for the subsumption claim
    rejects_354 = {
        (r["fixture"], r["period"])
        for r in rows
        if not (
            r["export"] > 0.1
            and (r["export"] > r["battery_to_home"] or r["export"] > r["headroom"])
        )
    }
    rejects_d3 = {(r["fixture"], r["period"]) for r in rows if not admits(r, D_REF_KW)}
    print(
        f"\n#354 two-sided rejects {len(rejects_354)}; D3 rejects {len(rejects_d3)}; "
        f"#354-only {len(rejects_354 - rejects_d3)} "
        f"(0 means D3 strictly subsumes it)"
    )

    repro = [r for r in rows if (r["fixture"], r["period"]) == REPRO]
    if not repro:
        raise SystemExit(
            f"#352 reproduction period {REPRO} is no longer a BATTERY_EXPORT "
            "period -- the acceptance criterion it anchors needs re-deriving"
        )
    r = repro[0]
    harm = r["buy"] * min(D_REF_KW * r["dt"], r["headroom"])
    print(f"\n=== #352 reproduction: {REPRO[0]} p{REPRO[1]} ===")
    print(
        f"  export {r['export']:.3f} kWh, home take {r['battery_to_home']:.3f} kWh, "
        f"headroom {r['headroom']:.3f} kWh"
    )
    print(
        f"  benefit {r['benefit']:.3f} SEK vs harm {harm:.3f} SEK -> "
        f"{'ADMIT' if admits(r, D_REF_KW) else 'REJECT'}"
    )


if __name__ == "__main__":
    main()
