#!/usr/bin/env python3
"""Extract all decision evidence for a single slot from a BESS debug bundle.

A debug bundle holds the SAME slot in several places, and they can disagree:

- the LATEST optimization run, as a `### Period Decisions` markdown table and a
  structured "Full Schedule JSON" block (the reliable source for economics:
  sell_price / buy_price / cost_basis / shadow_price); and
- EARLIER runs, only as box-drawing tables dumped in `## System Logs` — compact
  per-period rows (`║ 63 ║ … BATTERY_EXPORT`) and inverter TOU schedule blocks
  (`║ 15:45-15:59 ║ … 4%`).

The analyst's recurring failure is reading only the latest run and concluding "it
didn't happen" when an earlier run scheduled the very action the user asked about.
This script gathers every occurrence of one slot across all those sources and flags
cross-run disagreement, so the agent cannot miss it.

Usage:
    python scripts/extract_decision_evidence.py <bundle.md> --time 15:45
    python scripts/extract_decision_evidence.py <bundle.md> --period 63
"""

from __future__ import annotations

import argparse
import json
import re
import sys

INTENTS = {
    "GRID_CHARGING",
    "SOLAR_STORAGE",
    "LOAD_SUPPORT",
    "BATTERY_EXPORT",
    "SOLAR_EXPORT",
    "IDLE",
}

BOX = "║"  # ║ column separator used in log tables
PRICE_RE = re.compile(r"^\d+\.\d+/\d+\.\d+$")
TIMERANGE_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


def period_to_time(period: int) -> str:
    return f"{period // 4:02d}:{(period % 4) * 15:02d}"


def time_to_period(t: str) -> int:
    h, m = (int(x) for x in t.split(":"))
    return h * 4 + m // 15


def minutes(t: str) -> int:
    h, m = (int(x) for x in t.split(":"))
    return h * 60 + m


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.split(BOX)]


def parse_period_decisions(text: str, period: int) -> dict | None:
    """The latest run's `### Period Decisions` markdown table row for `period`."""
    in_table = False
    for line in text.splitlines():
        if line.strip().startswith("### Period Decisions"):
            in_table = True
            continue
        if in_table:
            if line.startswith("|"):
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cols) >= 8 and cols[0].isdigit() and int(cols[0]) == period:
                    return {
                        "period": int(cols[0]),
                        "time": cols[1],
                        "intent": cols[2],
                        "observed": cols[3],
                        "battery_action": cols[4],
                        "soe": cols[5],
                        "buy_price": cols[6],
                        "savings": cols[7],
                    }
            elif line.strip().startswith("##"):
                break
    return None


def parse_compact_rows(text: str, period: int) -> list[dict]:
    """Box-drawing per-period rows from log dumps of earlier runs.

    Example: ║ 63 ║ 1.06/0.46 ║ ... ║ -0.1 ║ BATTERY_EXPORT ║ ...
    """
    rows = []
    for ln, line in enumerate(text.splitlines(), 1):
        if BOX not in line:
            continue
        cells = [c for c in _cells(line) if c != ""]
        if not cells or not cells[0].isdigit() or int(cells[0]) != period:
            continue
        intent_idx = next((i for i, c in enumerate(cells) if c in INTENTS), None)
        if intent_idx is None:
            continue  # not a per-period decision row
        price = next((c for c in cells if PRICE_RE.match(c)), None)
        batt = cells[intent_idx - 1] if intent_idx >= 1 else None
        rows.append(
            {
                "line": ln,
                "intent": cells[intent_idx],
                "battery_action": batt,
                "buy_sell": price,
            }
        )
    return rows


def parse_tou_rows(text: str, target_min: int) -> list[dict]:
    """Inverter TOU schedule rows (box-drawing) whose window covers the slot.

    Example: ║ 15:45-15:59 ║ 15min ║ BATTERY_EXPORT ║ grid_first ║ False ║ 0% ║ 4% ║
    """
    rows = []
    for ln, line in enumerate(text.splitlines(), 1):
        if BOX not in line:
            continue
        cells = _cells(line)
        cells = [c for c in cells if c != ""]
        if len(cells) < 4:
            continue
        m = TIMERANGE_RE.match(cells[0])
        if not m:
            continue
        start = int(m.group(1)) * 60 + int(m.group(2))
        end = int(m.group(3)) * 60 + int(m.group(4))
        if not (start <= target_min <= end):
            continue
        intent = next((c for c in cells if c in INTENTS), None)
        mode = next(
            (c for c in cells if c in {"load_first", "grid_first", "battery_first"}),
            None,
        )
        pcts = [c for c in cells if c.endswith("%")]
        rows.append(
            {
                "line": ln,
                "window": cells[0],
                "intent": intent,
                "mode": mode,
                "charge_pct": pcts[0] if len(pcts) >= 1 else None,
                "discharge_pct": pcts[1] if len(pcts) >= 2 else None,
            }
        )
    return rows


def parse_json_economics(text: str, period: int) -> list[dict]:
    """Per-period economics from every ```json block that contains the period."""
    results = []
    for block in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL):
        try:
            data = json.loads(block)
        except (ValueError, json.JSONDecodeError):
            continue
        for entry in _find_period_entries(data, period):
            econ = entry.get("economic", {})
            dec = entry.get("decision", {})
            results.append(
                {
                    "intent": dec.get("strategic_intent"),
                    "battery_action": dec.get("battery_action"),
                    "sell_price": econ.get("sell_price"),
                    "buy_price": econ.get("buy_price"),
                    "cost_basis": dec.get("cost_basis"),
                    "shadow_price": dec.get("shadow_price"),
                    "battery_to_grid": entry.get("energy", {}).get("battery_to_grid"),
                    "soe_start": entry.get("energy", {}).get("battery_soe_start"),
                    "soe_end": entry.get("energy", {}).get("battery_soe_end"),
                }
            )
    return results


def _find_period_entries(node, period: int):
    """Recursively yield dicts that look like a period entry for `period`."""
    if isinstance(node, dict):
        if node.get("period") == period and ("decision" in node or "economic" in node):
            yield node
        for v in node.values():
            yield from _find_period_entries(v, period)
    elif isinstance(node, list):
        for v in node:
            yield from _find_period_entries(v, period)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="path to the debug bundle .md file")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--time", help="slot clock time, e.g. 15:45")
    g.add_argument("--period", type=int, help="period number, e.g. 63")
    args = ap.parse_args()

    if args.period is not None:
        period = args.period
        time = period_to_time(period)
    else:
        time = args.time
        period = time_to_period(time)

    with open(args.bundle, encoding="utf-8") as f:
        text = f.read()

    pd_row = parse_period_decisions(text, period)
    econ = parse_json_economics(text, period)
    compact = parse_compact_rows(text, period)
    tou = parse_tou_rows(text, minutes(time))

    out = []
    out.append(f"# Decision evidence for period {period} ({time})\n")

    out.append("## Latest run — facts (Period Decisions table)")
    if pd_row:
        out.append(
            f"- intent={pd_row['intent']}  battery_action={pd_row['battery_action']}"
            f"  SOE={pd_row['soe']}  buy={pd_row['buy_price']}"
        )
    else:
        out.append("- (not found)")

    out.append("\n## Latest run — economics (Full Schedule JSON)")
    if econ:
        for e in econ:
            out.append(
                f"- intent={e['intent']}  sell={e['sell_price']}  buy={e['buy_price']}"
                f"  cost_basis={e['cost_basis']}  shadow_price={e['shadow_price']}"
                f"  battery_to_grid={e['battery_to_grid']}"
                f"  SOE={e['soe_start']}→{e['soe_end']}"
            )
    else:
        out.append("- (not found)")

    out.append("\n## Earlier runs — compact per-period rows (log dumps)")
    if compact:
        for r in compact:
            out.append(
                f"- line {r['line']}: intent={r['intent']}"
                f"  battery_action={r['battery_action']}  buy/sell={r['buy_sell']}"
            )
    else:
        out.append("- (none)")

    out.append("\n## Earlier runs — inverter TOU schedule segments covering this slot")
    if tou:
        for r in tou:
            out.append(
                f"- line {r['line']}: {r['window']}  intent={r['intent']}"
                f"  mode={r['mode']}  charge={r['charge_pct']}"
                f"  discharge={r['discharge_pct']}"
            )
    else:
        out.append("- (none)")

    # Disagreement flag — the whole point of the script.
    intents_seen = set()
    if pd_row:
        intents_seen.add(pd_row["intent"])
    for e in econ:
        if e["intent"]:
            intents_seen.add(e["intent"])
    for r in compact:
        intents_seen.add(r["intent"])
    for r in tou:
        if r["intent"]:
            intents_seen.add(r["intent"])
    discharge_in_tou = any(
        r["discharge_pct"] and r["discharge_pct"] != "0%" for r in tou
    )

    out.append("\n## Cross-run reconciliation")
    if len(intents_seen) > 1:
        out.append(
            f"- DISAGREEMENT: this slot appears with different intents across "
            f"sources: {sorted(intents_seen)}."
        )
        out.append(
            "  Do NOT answer from the latest run alone — explain WHY runs differ "
            "(near-threshold shadow_price volatility is the usual cause) and which "
            "plan actually executes."
        )
    else:
        out.append(f"- All sources agree: intent={sorted(intents_seen) or '(none)'}.")
    if discharge_in_tou:
        out.append(
            "- An inverter TOU segment for this slot has a NON-ZERO discharge rate: "
            "the battery WAS scheduled to export here in at least one run, even if "
            "the latest Period Decisions row shows no discharge."
        )

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
