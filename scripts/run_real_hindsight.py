"""Audit and analyze an immutable BESS backup; never construct an HA client.

An incomplete week is attempted and reported as blocked. With explicit approval,
the same engine can additionally solve only genuine observed intervals. Its
costs are conditional model results, not a fabricated complete-week comparison.
"""

import argparse
import hashlib
import json
import logging
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.bess import time_utils
from core.bess.daily_view_store import DailyViewStore
from core.bess.performance_hindsight import (
    PRICE_REFERENCE_TOLERANCE,
    analyze_period,
    published_price_reference,
    retrospective_context,
)


def _manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )


def run_backup_analysis(
    data_dir: Path,
    settings_file: Path,
    week: date,
    timezone: str,
    output_dir: Path,
    approve: bool,
    allow_partial: bool,
    price_reference_dir: Path | None = None,
) -> dict[str, Any]:
    """Use copied assumptions and observations without editing source files."""
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(data_dir):
        raise ValueError("Analysis output must be outside the original backup")
    output_dir.mkdir(parents=True, exist_ok=True)
    before = _manifest(data_dir)
    _write(output_dir / "original-backup-sha256.json", before)
    time_utils.set_timezone(timezone)
    store = DailyViewStore(data_dir / "daily_views")
    settings_bytes = settings_file.read_bytes()
    settings = json.loads(settings_bytes)
    reference = None
    if price_reference_dir is not None:
        reference = published_price_reference(
            price_reference_dir,
            settings["electricity_price"],
            [week + timedelta(days=offset) for offset in range(8)],
        )
        price_audit: list[dict[str, Any]] = []
        for offset in range(7):
            day = week + timedelta(days=offset)
            view = store.load_day(day)
            if view is None:
                continue
            for p in view.periods:
                start = time_utils.period_start(day, p.period).isoformat()
                published = reference["prices"].get(start)
                price_audit.append(
                    {
                        "timestamp": start,
                        "data_source": p.data_source,
                        "recorded_buy": p.economic.buy_price,
                        "recorded_sell": p.economic.sell_price,
                        "published_buy": published[0] if published else None,
                        "published_sell": published[1] if published else None,
                        "matches": (
                            published is not None
                            and abs(p.economic.buy_price - published[0])
                            <= PRICE_REFERENCE_TOLERANCE
                            and abs(p.economic.sell_price - published[1])
                            <= PRICE_REFERENCE_TOLERANCE
                        ),
                    }
                )
        _write(
            output_dir / "price-reference-audit.json",
            {
                "source": reference["source"],
                "tolerance_per_kwh": PRICE_REFERENCE_TOLERANCE,
                "per_day_matching_quarters": {
                    (week + timedelta(days=offset)).isoformat(): sum(
                        row["matches"]
                        for row in price_audit
                        if row["timestamp"].startswith(
                            (week + timedelta(days=offset)).isoformat()
                        )
                    )
                    for offset in range(7)
                },
                "quarters": price_audit,
            },
        )
    strict = analyze_period(store, week, price_reference=reference)
    _write(output_dir / "verified-full-week-attempt.json", strict)
    audit = []
    gaps = []
    for offset in range(7):
        day = week + timedelta(days=offset)
        view = store.load_day(day)
        if view is None:
            audit.append({"date": day.isoformat(), "file_missing": True})
            continue
        actual = [p for p in view.periods if p.data_source == "actual"]
        audit.append(
            {
                "date": day.isoformat(),
                "quarters": len(view.periods),
                "actual": len(actual),
                "predicted": sum(p.data_source == "predicted" for p in view.periods),
                "energy_kwh_actual": {
                    key: sum(p.energy.__dict__[key] for p in actual)
                    for key in (
                        "solar_production",
                        "home_consumption",
                        "grid_imported",
                        "grid_exported",
                        "battery_charged",
                        "battery_discharged",
                    )
                },
                "initial_soe_kwh": (
                    actual[0].energy.battery_soe_start if actual else None
                ),
                "last_observed_soe_kwh": (
                    actual[-1].energy.battery_soe_end if actual else None
                ),
            }
        )
        following = store.load_day(day + timedelta(days=1))
        opening = (
            next(
                (
                    p
                    for p in following.periods
                    if p.period == 0 and p.data_source == "actual"
                ),
                None,
            )
            if following
            else None
        )
        for p in view.periods:
            if p.data_source == "actual":
                continue
            prior = next((q for q in actual if q.period == p.period - 1), None)
            gaps.append(
                {
                    "date": day.isoformat(),
                    "period": p.period,
                    "source": p.data_source,
                    "buy_price": p.economic.buy_price,
                    "sell_price": p.economic.sell_price,
                    "opening_soc_energy_from_prior_actual": (
                        prior.energy.battery_soe_end if prior else None
                    ),
                    "closing_soc_energy_from_following_day": (
                        opening.energy.battery_soe_start
                        if opening and p.period == time_utils.get_period_count(day) - 1
                        else None
                    ),
                    "energy_recoverable": False,
                    "reason": "Adjacent SOC readings do not determine household/grid/solar energy or battery throughput. Complete cumulative boundary readings are absent from this backup.",
                }
            )
    _write(output_dir / "daily-coverage-audit.json", audit)
    _write(output_dir / "unrecovered-quarters.json", gaps)
    midnight_evidence = []
    logs = data_dir / "logs"
    if logs.exists():
        for path in sorted(logs.glob("*.zip")):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    for number, line in enumerate(
                        archive.read(name)
                        .decode("utf-8", errors="replace")
                        .splitlines(),
                        1,
                    ):
                        if "00:00:" in line and any(
                            word in line
                            for word in (
                                "Cleared all historical data",
                                "Skipping data collection",
                                "Setting initial SOC",
                            )
                        ):
                            midnight_evidence.append(
                                {
                                    "archive": path.name,
                                    "member": name,
                                    "line": number,
                                    "text": line,
                                }
                            )
    _write(output_dir / "midnight-log-evidence.json", midnight_evidence)
    result = strict
    if approve:
        source = f"{settings_file.name} (SHA-256 {hashlib.sha256(settings_bytes).hexdigest()[:16]})"
        context = retrospective_context(settings, source, timezone)
        _write(output_dir / "approved-assumptions.json", context)
        complete_attempt = analyze_period(
            store,
            week,
            mode="estimated",
            assumed_context=context,
            price_reference=reference,
        )
        _write(output_dir / "estimated-full-week-attempt.json", complete_attempt)
        result = analyze_period(
            store,
            week,
            mode="estimated",
            assumed_context=context,
            allow_partial=allow_partial,
            price_reference=reference,
        )
        _write(output_dir / "observed-interval-analysis.json", result)
    after = _manifest(data_dir)
    if before != after:
        raise RuntimeError("Original backup changed during analysis")
    summary = {
        "status": result["status"],
        "mode": result["mode"],
        "scope": result["scope"],
        "timezone": timezone,
        "original_backup_unchanged": True,
        "source_file_count": len(before),
        "full_week_attempt_status": strict["status"],
        "diagnostics": result["diagnostics"],
        "actual": result["actual"],
        "hindsight_model": result["optimal"],
        "observed_cost_model_difference": result["model_cost_difference"],
        "full_week_missed_savings": result["missed_savings"],
        "captured_percent": result["captured_percent"],
        "warnings": result["warnings"],
        "issues": result["issues"],
        "solve_seconds": result.get("solve_seconds"),
        "initial_energy_kwh": result.get("initial_energy_kwh"),
        "terminal_energy_kwh": result.get("terminal_energy_kwh"),
        "model_terminal_energy_kwh": result.get("model_terminal_energy_kwh"),
        "terminal_evidence": result.get("terminal_evidence"),
        "actual_validation": result.get("actual_validation"),
        "model_validation": result.get("model_validation"),
        "huawei_tou_blocks": result.get("huawei_tou_blocks"),
        "huawei_feasible": result.get("huawei_feasible"),
        "solar_only": result["solar_only"],
        "grid_only": result["grid_only"],
        "relaxed_bound_label": result.get("relaxed_bound_label"),
        "price_reference_source": result.get("price_reference_source"),
        "gap_boundaries": result.get("gap_boundaries"),
        "excluded_intervals": result.get("excluded_intervals"),
        "comparison_start": result.get("comparison_start"),
        "comparison_end": result.get("comparison_end"),
        "execution_verified": result.get("execution_verified"),
    }
    _write(output_dir / "summary.json", summary)
    _write(output_dir / "analysis-command.json", sys.orig_argv)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--week", required=True, type=date.fromisoformat)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--approve-backup-assumptions", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument(
        "--price-reference-dir",
        type=Path,
        help="Nord Pool data-portal DayAheadPrices JSON files (<area>-<date>.json)",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    result = run_backup_analysis(
        args.data_dir,
        args.settings,
        args.week,
        args.timezone,
        args.output_dir,
        args.approve_backup_assumptions,
        args.allow_partial,
        args.price_reference_dir,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
