"""Terminal report formatter for benchmark results."""

from .runner import BenchmarkResult


def _format_time(period: int, period_duration_hours: float) -> str:
    total_minutes = round(period * period_duration_hours * 60)
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def _format_horizon(remaining: int, period_duration_hours: float) -> str:
    hours = remaining * period_duration_hours
    if hours == int(hours):
        return f"{int(hours):2d}h"
    return f"{hours:.1f}h"


def _decision(active: bool) -> str:
    return "ACTIVE" if active else "IDLE  "


def _change_label(results: dict, variant_names: list[str]) -> str:
    if len(variant_names) < 2:
        return "-"
    a = results[variant_names[0]].active
    b = results[variant_names[1]].active
    if a == b:
        return "-"
    if not a and b:
        return "IDLE→ACT ⬆"
    return "ACT→IDLE ⬇"


def print_report(benchmark_results: list[BenchmarkResult], title: str = "") -> None:
    """Print a formatted comparison table to stdout."""
    if not benchmark_results:
        print("No results to report.")
        return

    variant_names = list(benchmark_results[0].variant_results.keys())
    col_scenario = 45
    col_start = 6
    col_horizon = 5

    # Header
    print()
    separator = "=" * 100
    print(separator)
    if title:
        print(f"  {title}")
        print(separator)

    # Column headers
    variant_header = "  ".join(
        f"{'Threshold':>9}  {'Savings':>8}  {'Decision':>8}" for _ in variant_names
    )
    print(
        f"{'Scenario':<{col_scenario}}  {'Start':>{col_start}}  {'Rem':>{col_horizon}}"
        f"  {variant_header}  Changed?"
    )

    # Variant sub-headers
    variant_subheader = "  ".join(
        f"  [{name:>7}]  {'':>8}  {'':>8}" for name in variant_names
    )
    print(
        f"{'':>{col_scenario}}  {'':>{col_start}}  {'':>{col_horizon}}"
        f"  {variant_subheader}"
    )
    print("-" * 100)

    # Track summary stats
    unlocked_count = 0
    locked_count = 0
    unlocked_savings = 0.0

    for r in benchmark_results:
        remaining = r.total_periods - r.start_period
        time_str = _format_time(r.start_period, r.period_duration_hours)
        horizon_str = _format_horizon(remaining, r.period_duration_hours)
        change = _change_label(r.variant_results, variant_names)

        variant_cols = "  ".join(
            f"  {r.variant_results[n].effective_threshold:>9.2f}"
            f"  {r.variant_results[n].savings:>8.2f}"
            f"  {_decision(r.variant_results[n].active):>8}"
            for n in variant_names
        )

        # Truncate long scenario names
        name = r.scenario_name
        if len(name) > col_scenario:
            name = name[: col_scenario - 1] + "…"

        flag = f"  {change}" if change != "-" else ""
        print(
            f"{name:<{col_scenario}}  {time_str:>{col_start}}  {horizon_str:>{col_horizon}}"
            f"  {variant_cols}{flag}"
        )

        if change == "IDLE→ACT ⬆" and len(variant_names) >= 2:
            unlocked_count += 1
            unlocked_savings += r.variant_results[variant_names[1]].savings
        elif change == "ACT→IDLE ⬇":
            locked_count += 1

    # Summary
    print("=" * 100)
    print("\nSUMMARY")
    print(f"  Total runs          : {len(benchmark_results)}")
    print(
        f"  Decision unchanged  : {len(benchmark_results) - unlocked_count - locked_count}"
    )
    if unlocked_count:
        print(
            f"  IDLE → ACTIVE (fix unlocks) : {unlocked_count}"
            f"  (total savings unlocked: {unlocked_savings:.2f})"
        )
    if locked_count:
        print(f"  ACTIVE → IDLE (fix blocks)  : {locked_count}")
    print()
