"""
Benchmark runner: execute multiple algorithm variants against a set of scenarios
and collect results for comparison.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import (
    ADDITIONAL_COSTS,
    MARKUP_RATE,
    TAX_REDUCTION,
    VAT_MULTIPLIER,
    BatterySettings,
)

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkScenario:
    """A scenario to run through the optimizer, optionally sliced from a start period."""

    name: str
    buy_prices: list[float]
    sell_prices: list[float]
    consumption: list[float]
    solar: list[float]
    battery_settings: BatterySettings
    initial_soe: float
    start_period: int = 0
    period_duration_hours: float = 1.0


@dataclass
class Variant:
    """
    An algorithm variant defined by how it transforms BatterySettings before
    running the optimizer.

    apply(settings, remaining_periods, total_periods) -> settings for this run
    """

    name: str
    apply: Callable[[BatterySettings, int, int], BatterySettings]


@dataclass
class VariantResult:
    """Result of running one variant against one scenario."""

    savings: float
    active: bool  # False means the IDLE fallback was triggered
    effective_threshold: float
    total_charged: float
    total_discharged: float


@dataclass
class BenchmarkResult:
    """Comparison of all variants for one (scenario, start_period) combination."""

    scenario_name: str
    start_period: int
    total_periods: int
    period_duration_hours: float
    variant_results: dict[str, VariantResult]  # variant name → result


def _load_scenario_from_json(path: Path) -> BenchmarkScenario:
    """Load a scenario from a JSON file and compute buy/sell prices via PriceManager."""
    with open(path) as f:
        data = json.load(f)

    base_prices: list[float] = data["base_prices"]
    battery: dict = data["battery"]
    price_data: dict = data.get("price_data", {})

    price_manager = PriceManager(
        MockSource(base_prices),
        markup_rate=price_data.get("markup_rate", MARKUP_RATE),
        vat_multiplier=price_data.get("vat_multiplier", VAT_MULTIPLIER),
        additional_costs=price_data.get("additional_costs", ADDITIONAL_COSTS),
        tax_reduction=price_data.get("tax_reduction", TAX_REDUCTION),
        area=price_data.get("area", "SE4"),
    )

    buy_prices = price_manager.get_buy_prices(raw_prices=base_prices)
    sell_prices = price_manager.get_sell_prices(raw_prices=base_prices)

    min_soe_kwh: float = battery["min_soe_kwh"]
    max_soe_kwh: float = battery["max_soe_kwh"]

    battery_settings = BatterySettings(
        total_capacity=max_soe_kwh,
        min_soc=(min_soe_kwh / max_soe_kwh) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=battery["max_charge_power_kw"],
        max_discharge_power_kw=battery["max_discharge_power_kw"],
        efficiency_charge=battery["efficiency_charge"],
        efficiency_discharge=battery["efficiency_discharge"],
        cycle_cost_per_kwh=battery["cycle_cost_per_kwh"],
    )

    return BenchmarkScenario(
        name=data["name"],
        buy_prices=buy_prices,
        sell_prices=sell_prices,
        consumption=data["home_consumption"],
        solar=data["solar_production"],
        battery_settings=battery_settings,
        initial_soe=battery["initial_soe"],
    )


def load_scenarios_from_dir(
    data_dir: Path, start_periods: list[int]
) -> list[BenchmarkScenario]:
    """
    Load all JSON scenario files from a directory and expand each into multiple
    BenchmarkScenarios — one per start_period — to simulate mid-day optimizer runs.
    """
    scenarios: list[BenchmarkScenario] = []

    for path in sorted(data_dir.glob("*.json")):
        base = _load_scenario_from_json(path)
        total = len(base.buy_prices)

        for start in start_periods:
            if start >= total:
                logger.warning(
                    "Skipping start_period=%d for scenario '%s' (total=%d periods)",
                    start,
                    base.name,
                    total,
                )
                continue

            scenarios.append(
                BenchmarkScenario(
                    name=base.name,
                    buy_prices=base.buy_prices,
                    sell_prices=base.sell_prices,
                    consumption=base.consumption,
                    solar=base.solar,
                    battery_settings=base.battery_settings,
                    initial_soe=base.initial_soe,
                    start_period=start,
                    period_duration_hours=base.period_duration_hours,
                )
            )

    return scenarios


def _is_active(result_data: list) -> bool:
    """Return True if the optimizer produced any battery action (not all-IDLE)."""
    return any(
        h.decision.battery_action is not None and abs(h.decision.battery_action) > 0.01
        for h in result_data
    )


def run_benchmark(
    scenarios: list[BenchmarkScenario],
    variants: list[Variant],
) -> list[BenchmarkResult]:
    """Run all variants against all scenarios and return structured results."""
    results: list[BenchmarkResult] = []

    for scenario in scenarios:
        total_periods = len(scenario.buy_prices)
        start = scenario.start_period
        remaining = total_periods - start

        buy = scenario.buy_prices[start:]
        sell = scenario.sell_prices[start:]
        consumption = scenario.consumption[start:]
        solar = scenario.solar[start:]

        variant_results: dict[str, VariantResult] = {}

        for variant in variants:
            settings = variant.apply(
                scenario.battery_settings, remaining, total_periods
            )

            opt = optimize_battery_schedule(
                buy_price=buy,
                sell_price=sell,
                home_consumption=consumption,
                solar_production=solar,
                initial_soe=scenario.initial_soe,
                battery_settings=settings,
                period_duration_hours=scenario.period_duration_hours,
            )

            variant_results[variant.name] = VariantResult(
                savings=opt.economic_summary.grid_to_battery_solar_savings,
                active=_is_active(opt.period_data),
                effective_threshold=settings.min_action_profit_threshold,
                total_charged=opt.economic_summary.total_charged,
                total_discharged=opt.economic_summary.total_discharged,
            )

            logger.debug(
                "  [%s] start=%d remaining=%d threshold=%.2f savings=%.2f active=%s",
                variant.name,
                start,
                remaining,
                settings.min_action_profit_threshold,
                opt.economic_summary.grid_to_battery_solar_savings,
                variant_results[variant.name].active,
            )

        results.append(
            BenchmarkResult(
                scenario_name=scenario.name,
                start_period=start,
                total_periods=total_periods,
                period_duration_hours=scenario.period_duration_hours,
                variant_results=variant_results,
            )
        )

    return results
