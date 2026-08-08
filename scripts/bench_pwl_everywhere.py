#!/usr/bin/env python3
"""Benchmark: is full-horizon PWL affordable enough to retire the hybrid?

The #450 design keeps the grid DP as the primary solver and re-solves only
near-tied windows with the exact PWL DP, on the premise that PWL is rare and
slow. `dp_battery_algorithm.py` records that PWL actually fires on ~25% of
real solves at 20-40x latency -- which, if true suite-wide, guts the premise.

This measures the three modes on every fixture in the canonical corpus:

  grid    -- grid DP only, tie detection forced to return no windows
  hybrid  -- exactly what ships today
  pwl     -- tie detection forced to return one window spanning the horizon

All three run through the *same* `optimize_battery_schedule` code path; the
only difference is what `detect_tie_windows` returns. No solver logic is
reimplemented here, so a mode's cost is directly comparable to the others.

IMPORTANT CAVEAT ON `pwl` MODE
------------------------------
`run_pwl_window_backward_induction` has no terminal-value mode: its terminal
row is always a hard SOE pin (`_pinned_terminal_row`, pwl_window_dp.py:748).
So even a horizon-spanning window inherits the *grid DP's* terminal SOE. This
benchmark therefore answers "can PWL decide every period affordably, holding
terminal SOE fixed?" -- it does NOT show PWL replacing the grid DP outright.
Retiring the grid DP entirely additionally requires giving the PWL solver a
real terminal value row. Objective deltas here are clean (both modes end at
the same SOE, so no terminal-value confound); latency is the decisive number.

Usage:
    .venv/bin/python scripts/bench_pwl_everywhere.py
    .venv/bin/python scripts/bench_pwl_everywhere.py --only regression_ --timeout 300
    .venv/bin/python scripts/bench_pwl_everywhere.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from core.bess import tie_detection  # noqa: E402
from core.bess.tests.helpers import _scenario_inputs  # noqa: E402
from core.bess.tie_detection import Window  # noqa: E402

DATA_DIR = repo_root / "core" / "bess" / "tests" / "unit" / "data"

# The optimizer logs at INFO on every solve; silence it so the table is
# readable. Failures are surfaced by this script, not by the log.
import logging  # noqa: E402

logging.disable(logging.CRITICAL)


class Timeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise Timeout()


def _run_mode(scenario: dict, mode: str, repeats: int, timeout_s: int) -> dict:
    """Run one fixture in one mode. Returns a result dict (never raises).

    `detect_tie_windows` is imported inside `optimize_battery_schedule`, so
    patching the module attribute takes effect per call.
    """
    from core.bess.dp_battery_algorithm import optimize_battery_schedule

    real_detect = tie_detection.detect_tie_windows
    diag: dict = {}

    def no_windows(tie_margins, value_slopes, soe_step_kwh, pad=2):
        return []

    def whole_horizon(tie_margins, value_slopes, soe_step_kwh, pad=2):
        return [Window(0, len(tie_margins))]

    patch = {"grid": no_windows, "hybrid": real_detect, "pwl": whole_horizon}[mode]

    inputs = _scenario_inputs(scenario)
    if mode == "hybrid":
        inputs["tie_diagnostics"] = diag

    tie_detection.detect_tie_windows = patch
    try:
        best = None
        result = None
        for _ in range(repeats):
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_s)
            try:
                t0 = time.perf_counter()
                result = optimize_battery_schedule(**inputs)
                elapsed = time.perf_counter() - t0
            finally:
                signal.alarm(0)
            best = elapsed if best is None else min(best, elapsed)
        return {
            "status": "ok",
            "seconds": best,
            "cost": result.economic_summary.battery_solar_cost,
            "savings": result.economic_summary.grid_to_battery_solar_savings,
            "windows": [(w.start, w.end) for w in diag.get("windows", [])],
        }
    except Timeout:
        return {"status": "timeout", "seconds": float(timeout_s)}
    except Exception as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        tie_detection.detect_tie_windows = real_detect


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="substring filter on fixture name")
    ap.add_argument("--timeout", type=int, default=600, help="per-run seconds")
    ap.add_argument("--repeats", type=int, default=3, help="repeats for grid/hybrid")
    ap.add_argument("--json", default="", help="write full results to this path")
    args = ap.parse_args()

    fixtures = sorted(p for p in DATA_DIR.glob("*.json") if args.only in p.stem)
    if not fixtures:
        print(f"No fixtures matching {args.only!r} in {DATA_DIR}", file=sys.stderr)
        return 1

    print(
        f"{len(fixtures)} fixtures | timeout {args.timeout}s | repeats {args.repeats}"
    )
    print()
    header = (
        f"{'fixture':<48} {'H':>4} "
        f"{'grid s':>9} {'hybrid s':>9} {'pwl s':>10} {'pwl/grid':>9} "
        f"{'win':>4} {'d cost SEK':>11}"
    )
    print(header)
    print("-" * len(header))

    results = []
    for path in fixtures:
        with open(path) as f:
            scenario = json.load(f)
        name = path.stem

        try:
            horizon = len(_scenario_inputs(scenario)["buy_price"])
        except Exception as exc:
            print(f"{name:<48} SKIP (inputs): {type(exc).__name__}: {exc}", flush=True)
            results.append(
                {"fixture": name, "status": "input-error", "error": str(exc)}
            )
            continue

        grid = _run_mode(scenario, "grid", args.repeats, args.timeout)
        hybrid = _run_mode(scenario, "hybrid", args.repeats, args.timeout)
        pwl = _run_mode(scenario, "pwl", 1, args.timeout)

        row = {
            "fixture": name,
            "horizon": horizon,
            "grid": grid,
            "hybrid": hybrid,
            "pwl": pwl,
        }
        results.append(row)

        def fmt(m, width):
            if m["status"] == "ok":
                return f"{m['seconds']:>{width}.3f}"
            return f"{m['status'][:width]:>{width}}"

        ratio = (
            f"{pwl['seconds'] / grid['seconds']:>9.1f}"
            if pwl["status"] == "ok" and grid["status"] == "ok" and grid["seconds"] > 0
            else f"{'-':>9}"
        )
        nwin = len(hybrid.get("windows", [])) if hybrid["status"] == "ok" else 0
        dcost = (
            f"{pwl['cost'] - hybrid['cost']:>+11.4f}"
            if pwl["status"] == "ok" and hybrid["status"] == "ok"
            else f"{'-':>11}"
        )
        print(
            f"{name:<48} {horizon:>4} "
            f"{fmt(grid, 9)} {fmt(hybrid, 9)} {fmt(pwl, 10)} {ratio} "
            f"{nwin:>4} {dcost}",
            flush=True,
        )
        if pwl["status"] == "error":
            print(f"{'':<48}   pwl: {pwl['error']}", flush=True)

    ok = [r for r in results if r.get("pwl", {}).get("status") == "ok"]
    print()
    print(f"pwl mode succeeded on {len(ok)}/{len(results)} fixtures")
    if ok:
        worst = max(ok, key=lambda r: r["pwl"]["seconds"])
        total_pwl = sum(r["pwl"]["seconds"] for r in ok)
        total_hybrid = sum(
            r["hybrid"]["seconds"] for r in ok if r["hybrid"]["status"] == "ok"
        )
        improved = [r for r in ok if r["pwl"]["cost"] < r["hybrid"]["cost"] - 1e-9]
        worse = [r for r in ok if r["pwl"]["cost"] > r["hybrid"]["cost"] + 1e-9]
        print(f"slowest pwl solve: {worst['pwl']['seconds']:.2f}s ({worst['fixture']})")
        print(f"total pwl {total_pwl:.1f}s vs total hybrid {total_hybrid:.1f}s")
        print(
            f"pwl cheaper on {len(improved)}, costlier on {len(worse)}, tied on {len(ok) - len(improved) - len(worse)}"
        )
        if worse:
            mx = max(worse, key=lambda r: r["pwl"]["cost"] - r["hybrid"]["cost"])
            print(
                f"worst regression: {mx['pwl']['cost'] - mx['hybrid']['cost']:+.4f} SEK ({mx['fixture']})"
            )

    failures = [
        r for r in results if r.get("pwl", {}).get("status") not in ("ok", None)
    ]
    if failures:
        print()
        print("pwl-mode failures (a raise is a real finding, not a script bug):")
        for r in failures:
            detail = r["pwl"].get("error", r["pwl"]["status"])
            print(f"  {r['fixture']}: {detail}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
