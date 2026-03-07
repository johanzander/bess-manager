"""
Benchmark: fixed threshold vs. proportionally scaled threshold (issue #26).

Compares the current behavior (fixed min_action_profit_threshold) against the
proposed fix (threshold scaled by remaining horizon fraction with a 15% floor).

Usage:
    python scripts/benchmark_threshold.py [--threshold VALUE] [--floor VALUE]

Examples:
    python scripts/benchmark_threshold.py
    python scripts/benchmark_threshold.py --threshold 5.0 --floor 0.10
"""

import argparse
import copy
import logging
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.bess.benchmark import (  # noqa: E402
    Variant,
    load_scenarios_from_dir,
    print_report,
    run_benchmark,
)
from core.bess.settings import BatterySettings  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
# Suppress verbose optimizer logging — only show benchmark-level messages
logging.getLogger("core.bess").setLevel(logging.ERROR)


def _with_threshold(settings: BatterySettings, threshold: float) -> BatterySettings:
    """Return a copy of settings with the given threshold applied."""
    updated = copy.copy(settings)
    updated.min_action_profit_threshold = threshold
    updated.__post_init__()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=float,
        default=8.0,
        help="Configured min_action_profit_threshold (in your currency, default: 8.0)",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=0.15,
        help="Minimum fraction of threshold to apply at end of day (default: 0.15)",
    )
    args = parser.parse_args()

    configured_threshold: float = args.threshold
    floor: float = args.floor

    # Variant A: current behavior — fixed threshold regardless of horizon
    baseline = Variant(
        name="baseline",
        apply=lambda s, _rem, _tot: _with_threshold(s, configured_threshold),
    )

    # Variant B: proposed fix — scale threshold by remaining horizon fraction
    def scaled_apply(s: BatterySettings, remaining: int, total: int) -> BatterySettings:
        fraction = max(floor, remaining / total)
        return _with_threshold(s, configured_threshold * fraction)

    scaled = Variant(name="scaled", apply=scaled_apply)

    data_dir = (
        Path(__file__).parent.parent / "core" / "bess" / "tests" / "unit" / "data"
    )

    # Run each scenario at midnight (full day), mid-morning, and late afternoon
    # to exercise different remaining-horizon fractions
    start_periods = [0, 8, 16]

    print(f"Loading scenarios from {data_dir} ...")
    scenarios = load_scenarios_from_dir(data_dir, start_periods)
    print(f"Loaded {len(scenarios)} (scenario, start_period) combinations.\n")

    print("Running benchmark ...")
    results = run_benchmark(scenarios, [baseline, scaled])

    print_report(
        results,
        title=(
            f"Threshold scaling benchmark  |  configured={configured_threshold:.2f}  "
            f"floor={floor:.0%}  start_periods={start_periods}"
        ),
    )


if __name__ == "__main__":
    main()
