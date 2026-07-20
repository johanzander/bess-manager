#!/usr/bin/env python3
"""Build the interactive debug-log chart (HTML) from a BESS Manager debug bundle.

Recomputes every actual/historical period's detailed flows and observed
intent using the REAL production code (core.bess.models.EnergyData,
infer_intent_from_flows) imported from the repo at the path this script is
run from -- so the chart always reflects whatever's on the current branch,
never a stale pre-fix snapshot baked into the bundle at export time.

Usage:
    python3 build_chart.py <bundle.md> -o out.html [--title "..."]

The bundle path can be a local file (downloaded debug export attachment) or
piped in via stdin with `-`.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[
    3
]  # .claude/skills/visualize-debug-log/scripts -> repo root
sys.path.insert(0, str(REPO_ROOT))

from core.bess.dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW  # noqa: E402
from core.bess.models import EnergyData, infer_intent_from_flows  # noqa: E402


def _extract_json_block(text: str, anchor: str) -> str:
    """Return the raw JSON text of the first ```json fenced block after `anchor`."""
    start = text.index(anchor)
    fence_start = text.index("```json\n", start) + len("```json\n")
    fence_end = text.index("\n```", fence_start)
    return text[fence_start:fence_end]


def _fmt_time(period: int) -> str:
    total_min = (period % 96) * 15
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def parse_bundle(text: str) -> dict:
    battery_settings = json.loads(_extract_json_block(text, "### Battery Settings"))
    hist_raw = json.loads(_extract_json_block(text, "Full Historical Data JSON"))
    hist = [r for r in hist_raw if r is not None]

    schedule_start = text.index("## Raw Schedule JSON")
    schedule_all = json.loads(_extract_json_block(text[schedule_start:], "```json"))
    latest_run = schedule_all[-1]  # most recent optimization run, full horizon
    period_data_list = latest_run["optimization_result"]["period_data"]

    return {
        "battery_settings": battery_settings,
        "historical": hist,
        "forecast": period_data_list,
    }


def _clean_flow(v: float) -> float:
    """Zero out sub-threshold energy flows.

    Below core's own POWER_CLASSIFICATION_THRESHOLD_KW, a flow value is
    floating-point/cross-sensor noise, not a real physical transfer (same
    threshold core.bess.decision_intelligence uses to classify flows) --
    reused here so the chart never displays a phantom "0.00 grid" a raw
    float epsilon would otherwise trigger.
    """
    return v if abs(v) > POWER_CLASSIFICATION_THRESHOLD_KW else 0.0


def compute_decision_view(r: dict, cycle_cost: float) -> dict:
    """All decision/outcome math the tooltip needs, computed once here.

    This is the single implementation: the chart's JS only formats these
    numbers, it never re-derives a threshold, comparison, or formula from
    raw fields. A fix or behavior change in the real economics (reward,
    thresholds, formulas) only has to happen here to reach the chart.
    """
    solar_to_batt = r["solar_to_batt"]
    grid_to_batt = r["grid_to_batt"]
    batt_to_home = r["batt_to_home"]
    batt_to_grid = r["batt_to_grid"]

    charge_parts = []
    if solar_to_batt > 0:
        charge_parts.append({"source": "solar", "kwh": solar_to_batt})
    if grid_to_batt > 0:
        charge_parts.append({"source": "grid", "kwh": grid_to_batt})
    discharge_parts = []
    if batt_to_home > 0:
        discharge_parts.append({"source": "home", "kwh": batt_to_home})
    if batt_to_grid > 0:
        discharge_parts.append({"source": "grid", "kwh": batt_to_grid})

    # Which price the shadow price is actually being weighed against, and
    # whether it clears -- mirrors the DP's own reward/wear-cost policy
    # (discharge never incurs wear cost; charging always does).
    compare = None
    shadow = r["shadow_price"]
    if shadow > 0:
        if batt_to_grid > 0:
            compare = {
                "case": "export",
                "label": "sell price",
                "price": r["sell"],
                "clears": r["sell"] >= shadow,
            }
        elif batt_to_home > 0:
            compare = {
                "case": "home",
                "label": "buy price avoided",
                "price": r["buy"],
                "clears": r["buy"] >= shadow,
            }
        elif grid_to_batt > 0:
            cost = r["buy"] + cycle_cost
            compare = {
                "case": "grid_charge",
                "label": "buy price + cycle cost",
                "price": cost,
                "clears": shadow >= cost,
                "buy": r["buy"],
                "cycle_cost": cycle_cost,
            }
        elif solar_to_batt > 0:
            cost = r["sell"] + cycle_cost
            compare = {
                "case": "solar_store",
                "label": "sell price + cycle cost",
                "price": cost,
                "clears": shadow >= cost,
                "sell": r["sell"],
                "cycle_cost": cycle_cost,
            }

    breakeven = r["cost_basis"] + cycle_cost if r["cost_basis"] > 0 else None
    home_profit = (
        batt_to_home * (r["buy"] - breakeven)
        if breakeven is not None and batt_to_home > 0
        else None
    )
    export_profit = (
        batt_to_grid * (r["sell"] - breakeven)
        if breakeven is not None and batt_to_grid > 0
        else None
    )
    reward = r["export_revenue"] - r["import_cost"] - r["battery_wear_cost"]

    return {
        "charge_parts": charge_parts,
        "discharge_parts": discharge_parts,
        "charge_total": solar_to_batt + grid_to_batt,
        "discharge_total": batt_to_home + batt_to_grid,
        "export_total": r["solar_to_grid"] + batt_to_grid,
        "import_total": r["grid_to_home"] + grid_to_batt,
        "compare": compare,
        "breakeven": breakeven,
        "home_profit": home_profit,
        "export_profit": export_profit,
        "reward": reward,
        "total_value": reward + r["future_value"],
        "net_savings": r["grid_only_cost"] - r["grid_cost"],
    }


def build_rows(parsed: dict) -> list[dict]:
    rows_by_period: dict[int, dict] = {}

    for h in parsed["historical"]:
        e = h["energy"]
        econ = h["economic"]
        dec = h["decision"]
        # Recompute using the REAL current production code, not the bundle's
        # own (possibly pre-fix) stored detailed-flow values.
        energy = EnergyData(
            solar_production=e["solar_production"],
            home_consumption=e["home_consumption"],
            battery_charged=e["battery_charged"],
            battery_discharged=e["battery_discharged"],
            grid_imported=e["grid_imported"],
            grid_exported=e["grid_exported"],
            battery_soe_start=e["battery_soe_start"],
            battery_soe_end=e["battery_soe_end"],
        )
        power = energy.battery_charged - energy.battery_discharged
        intent = infer_intent_from_flows(power, energy)
        rows_by_period[h["period"]] = {
            "period": h["period"],
            "time": _fmt_time(h["period"]),
            "buy": econ.get("buy_price", 0.0),
            "sell": econ.get("sell_price", 0.0),
            "intent": intent,
            "soe_start": energy.battery_soe_start,
            "soe_end": energy.battery_soe_end,
            "solar": energy.solar_production,
            "load": energy.home_consumption,
            "grid_import": energy.grid_imported,
            "grid_export": energy.grid_exported,
            "batt_charged": energy.battery_charged,
            "batt_discharged": energy.battery_discharged,
            "solar_to_batt": _clean_flow(energy.solar_to_battery),
            "grid_to_batt": _clean_flow(energy.grid_to_battery),
            "batt_to_home": _clean_flow(energy.battery_to_home),
            "batt_to_grid": _clean_flow(energy.battery_to_grid),
            "solar_to_home": _clean_flow(energy.solar_to_home),
            "solar_to_grid": _clean_flow(energy.solar_to_grid),
            "grid_to_home": _clean_flow(energy.grid_to_home),
            "source": "actual",
            "shadow_price": dec.get("shadow_price", 0.0),
            "cost_basis": dec.get("cost_basis", 0.0),
            "economic_chain": dec.get("economic_chain", ""),
            "immediate_value": dec.get("immediate_value", 0.0),
            "future_value": dec.get("future_value", 0.0),
            "hourly_cost": econ.get("hourly_cost", 0.0),
            "grid_only_cost": econ.get("grid_only_cost", 0.0),
            "hourly_savings": econ.get("hourly_savings", 0.0),
            # Same formula backing the live dashboard's "Net Grid Cost" tile
            # (EconomicData.grid_cost, core/bess/models.py:232) -- wear-free,
            # import_cost - export_revenue. Net savings (grid_only_cost -
            # grid_cost) matches the dashboard's "Net Savings" exactly
            # (backend/api_dataclasses.py's netSavings).
            "grid_cost": econ.get("grid_cost", 0.0),
            # The DP's own two reward terms (core/bess/dp_battery_algorithm.py
            # _compute_reward: import_cost, export_revenue, battery_wear_cost),
            # so the chart can show reward = export_revenue - import_cost -
            # battery_wear_cost as its own breakdown, not just the result.
            "import_cost": econ.get("import_cost", 0.0),
            "export_revenue": econ.get("export_revenue", 0.0),
            "battery_wear_cost": econ.get("battery_cycle_cost", 0.0),
        }

    for pd_ in parsed["forecast"]:
        p = pd_["period"]
        if p in rows_by_period:
            continue  # actual/historical data takes precedence over the forecast
        e = pd_["energy"]
        econ = pd_["economic"]
        dec = pd_["decision"]
        rows_by_period[p] = {
            "period": p,
            "time": _fmt_time(p),
            "buy": econ.get("buy_price", 0.0),
            "sell": econ.get("sell_price", 0.0),
            "intent": dec.get("strategic_intent", "IDLE"),
            "soe_start": e["battery_soe_start"],
            "soe_end": e["battery_soe_end"],
            "solar": e["solar_production"],
            "load": e["home_consumption"],
            "grid_import": e["grid_imported"],
            "grid_export": e["grid_exported"],
            "batt_charged": e["battery_charged"],
            "batt_discharged": e["battery_discharged"],
            "solar_to_batt": _clean_flow(e["solar_to_battery"]),
            "grid_to_batt": _clean_flow(e["grid_to_battery"]),
            "batt_to_home": _clean_flow(e["battery_to_home"]),
            "batt_to_grid": _clean_flow(e["battery_to_grid"]),
            "solar_to_home": _clean_flow(e["solar_to_home"]),
            "solar_to_grid": _clean_flow(e["solar_to_grid"]),
            "grid_to_home": _clean_flow(e["grid_to_home"]),
            "source": "forecast",
            "shadow_price": dec.get("shadow_price", 0.0),
            "cost_basis": dec.get("cost_basis", 0.0),
            "economic_chain": dec.get("economic_chain", ""),
            "immediate_value": dec.get("immediate_value", 0.0),
            "future_value": dec.get("future_value", 0.0),
            "hourly_cost": econ.get("hourly_cost", 0.0),
            "grid_only_cost": econ.get("grid_only_cost", 0.0),
            "hourly_savings": econ.get("hourly_savings", 0.0),
            # Same formula backing the live dashboard's "Net Grid Cost" tile
            # (EconomicData.grid_cost, core/bess/models.py:232) -- wear-free,
            # import_cost - export_revenue. Net savings (grid_only_cost -
            # grid_cost) matches the dashboard's "Net Savings" exactly
            # (backend/api_dataclasses.py's netSavings).
            "grid_cost": econ.get("grid_cost", 0.0),
            # The DP's own two reward terms (core/bess/dp_battery_algorithm.py
            # _compute_reward: import_cost, export_revenue, battery_wear_cost),
            # so the chart can show reward = export_revenue - import_cost -
            # battery_wear_cost as its own breakdown, not just the result.
            "import_cost": econ.get("import_cost", 0.0),
            "export_revenue": econ.get("export_revenue", 0.0),
            "battery_wear_cost": econ.get("battery_cycle_cost", 0.0),
        }

    rows = [rows_by_period[p] for p in sorted(rows_by_period)]
    cycle_cost = parsed["battery_settings"].get("cycle_cost_per_kwh", 0.0)
    for r in rows:
        r["view"] = compute_decision_view(r, cycle_cost)
    return rows


def build_summary(rows: list[dict], battery_settings: dict) -> dict:
    return {
        "cycle_cost": battery_settings.get("cycle_cost_per_kwh", 0.0),
        "capacity": battery_settings.get("total_capacity", 0.0),
        "grid_only_cost": sum(r["grid_only_cost"] for r in rows),
        "actual_cost": sum(r["hourly_cost"] for r in rows),
        "savings": sum(r["hourly_savings"] for r in rows),
        "n_actual": sum(1 for r in rows if r["source"] == "actual"),
        "n_forecast": sum(1 for r in rows if r["source"] == "forecast"),
    }


def render(rows: list[dict], summary: dict, title: str, subtitle: str) -> str:
    head = (SCRIPT_DIR / "template_head.html").read_text()
    tail = (SCRIPT_DIR / "template_tail.js").read_text()

    head = head.replace("{{TITLE}}", title).replace("{{SUBTITLE}}", subtitle)
    rows_json = json.dumps(rows, separators=(",", ":"))
    summary_json = json.dumps(summary, separators=(",", ":"))

    return (
        head
        + f"const ROWS = {rows_json};\n"
        + f"const SUMMARY = {summary_json};\n"
        + tail
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="Path to a debug bundle .md file, or - for stdin")
    ap.add_argument("-o", "--output", required=True, help="Output HTML path")
    ap.add_argument(
        "--title", default=None, help="Chart title (default: derived from bundle)"
    )
    args = ap.parse_args()

    text = sys.stdin.read() if args.bundle == "-" else Path(args.bundle).read_text()

    parsed = parse_bundle(text)
    rows = build_rows(parsed)
    summary = build_summary(rows, parsed["battery_settings"])

    n_days = (rows[-1]["period"] // 96) + 1 if rows else 1
    title = (
        args.title
        or f"BESS Debug Log — {summary['n_actual']} actual + {summary['n_forecast']} forecast periods"
    )
    subtitle = (
        f"{len(rows)}-period trace ({n_days} day{'s' if n_days != 1 else ''}). "
        f"Periods 0&ndash;{summary['n_actual'] - 1} are actual sensor readings, recomputed against this "
        f"repo's current <code>core/bess/models.py</code> flow-split logic (not the bundle's own possibly-stale "
        f"stored values); the remainder is the latest optimization run's own forecast."
    )

    html = render(rows, summary, title, subtitle)
    Path(args.output).write_text(html)
    print(
        f"Wrote {args.output} ({len(rows)} periods, {summary['n_actual']} actual / {summary['n_forecast']} forecast)"
    )


if __name__ == "__main__":
    main()
