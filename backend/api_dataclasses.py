"""API DataClasses with canonical camelCase field names."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class FormattedValue:
    """Formatted value structure for frontend display."""

    value: float
    display: str
    unit: str
    text: str


def create_formatted_value(
    value: float, unit_type: str, currency: str, precision: int | None = None
) -> FormattedValue:
    """Create FormattedValue with currency parameter.

    Args:
        value: The numeric value to format
        unit_type: Type of unit ("currency", "energy_kwh_only", "percentage", "price", etc.)
        currency: Currency code (SEK, NOK, EUR, USD, etc.)
        precision: Override default decimal places (None = use defaults: currency=2, energy=2, percentage=1, price=2)
    """
    if unit_type == "currency":
        prec = precision if precision is not None else 2
        return FormattedValue(
            value=value,
            display=f"{value:,.{prec}f}",
            unit=currency,
            text=f"{value:,.{prec}f} {currency}",
        )
    elif unit_type == "energy_kwh_only":
        # Always use kWh units to ensure consistency in savings view
        # Small values like 0.2 kWh should remain as "0.2 kWh", not "200 Wh"
        prec = precision if precision is not None else 1
        return FormattedValue(
            value=value,
            display=f"{value:.{prec}f}",
            unit="kWh",
            text=f"{value:.{prec}f} kWh",
        )
    elif unit_type == "percentage":
        prec = precision if precision is not None else 0
        return FormattedValue(
            value=value,
            display=f"{value:.{prec}f}",
            unit="%",
            text=f"{value:.{prec}f} %",
        )
    elif unit_type == "price":
        prec = precision if precision is not None else 2
        price_unit = f"{currency}/kWh"
        return FormattedValue(
            value=value,
            display=f"{value:.{prec}f}",
            unit=price_unit,
            text=f"{value:.{prec}f} {price_unit}",
        )
    else:
        # Default fallback
        return FormattedValue(
            value=value, display=f"{value:.2f}", unit="", text=f"{value:.2f}"
        )


@dataclass
class APIBatterySettings:
    """Battery settings with clear SOC/SOE naming."""

    totalCapacity: float  # kWh - total battery capacity
    reservedCapacity: float  # kWh - reserved capacity

    # State of Charge limits (%)
    minSoc: float  # % (0-100) - minimum charge percentage
    maxSoc: float  # % (0-100) - maximum charge percentage

    # State of Energy limits (kWh) - calculated from SOC
    minSoeKwh: float  # kWh - minimum energy (calculated)
    maxSoeKwh: float  # kWh - maximum energy (calculated)

    # Power limits (kW)
    maxChargePowerKw: float  # kW - maximum charge power
    maxDischargePowerKw: float  # kW - maximum discharge power

    # Economic settings
    cycleCostPerKwh: float  # SEK/kWh - cost per cycle
    chargingPowerRate: float  # % - charging power rate
    efficiencyCharge: float  # % - charging efficiency
    efficiencyDischarge: float  # % - discharge efficiency
    estimatedConsumption: float  # kWh - estimated daily consumption

    @classmethod
    def from_internal(cls, battery, estimated_consumption: float) -> APIBatterySettings:
        """Convert from internal snake_case to canonical camelCase."""
        return cls(
            totalCapacity=battery.total_capacity,
            reservedCapacity=battery.reserved_capacity,
            minSoc=battery.min_soc,
            maxSoc=battery.max_soc,
            minSoeKwh=battery.min_soe_kwh,
            maxSoeKwh=battery.max_soe_kwh,
            maxChargePowerKw=battery.max_charge_power_kw,
            maxDischargePowerKw=battery.max_discharge_power_kw,
            cycleCostPerKwh=battery.cycle_cost_per_kwh,
            chargingPowerRate=battery.charging_power_rate,
            efficiencyCharge=battery.efficiency_charge,
            efficiencyDischarge=battery.efficiency_discharge,
            estimatedConsumption=estimated_consumption,
        )

    def to_internal_update(self) -> dict:
        """Convert API updates back to internal snake_case."""
        return {
            "total_capacity": self.totalCapacity,
            "min_soc": self.minSoc,
            "max_soc": self.maxSoc,
            "max_charge_power_kw": self.maxChargePowerKw,
            "max_discharge_power_kw": self.maxDischargePowerKw,
            "cycle_cost_per_kwh": self.cycleCostPerKwh,
            "charging_power_rate": self.chargingPowerRate,
            "efficiency_charge": self.efficiencyCharge,
            "efficiency_discharge": self.efficiencyDischarge,
        }


@dataclass
class APIPriceSettings:
    """API response dataclass with canonical camelCase fields."""

    area: str
    markupRate: float
    vatMultiplier: float
    additionalCosts: float
    taxReduction: float
    minProfit: float
    useActualPrice: bool

    @classmethod
    def from_internal(cls, price) -> APIPriceSettings:
        """Convert from internal snake_case to canonical camelCase."""
        return cls(
            area=price.area,
            markupRate=price.markup_rate,
            vatMultiplier=price.vat_multiplier,
            additionalCosts=price.additional_costs,
            taxReduction=price.tax_reduction,
            minProfit=price.min_profit,
            useActualPrice=price.use_actual_price,
        )


@dataclass
class APIPredictionSnapshot:
    """API representation of PredictionSnapshot."""

    snapshotTimestamp: str  # ISO format
    optimizationPeriod: int
    predictedDailySavings: FormattedValue
    periodCount: int  # From daily_view
    actualCount: int  # From daily_view
    growattScheduleCount: int  # Number of TOU intervals

    @classmethod
    def from_internal(cls, snapshot, currency: str) -> APIPredictionSnapshot:
        """Convert from internal PredictionSnapshot to API format.

        Args:
            snapshot: PredictionSnapshot object
            currency: Currency code for formatting

        Returns:
            APIPredictionSnapshot with camelCase fields
        """
        return cls(
            snapshotTimestamp=snapshot.snapshot_timestamp.isoformat(),
            optimizationPeriod=snapshot.optimization_period,
            predictedDailySavings=create_formatted_value(
                snapshot.predicted_daily_savings, "currency", currency
            ),
            periodCount=len(snapshot.daily_view.periods),
            actualCount=snapshot.daily_view.actual_count,
            growattScheduleCount=len(snapshot.growatt_schedule),
        )


@dataclass
class APIPeriodDeviation:
    """API representation of period-level deviation."""

    period: int
    predictedBatteryAction: FormattedValue
    actualBatteryAction: FormattedValue
    batteryActionDeviation: FormattedValue
    predictedConsumption: FormattedValue
    actualConsumption: FormattedValue
    consumptionDeviation: FormattedValue
    predictedSolar: FormattedValue
    actualSolar: FormattedValue
    solarDeviation: FormattedValue
    predictedSavings: FormattedValue
    actualSavings: FormattedValue
    savingsDeviation: FormattedValue
    deviationType: str

    @classmethod
    def from_internal(cls, period_deviation, currency: str) -> APIPeriodDeviation:
        """Convert from internal PeriodDeviation to API format.

        Args:
            period_deviation: PeriodDeviation object
            currency: Currency code for formatting

        Returns:
            APIPeriodDeviation with camelCase fields
        """
        return cls(
            period=period_deviation.period,
            predictedBatteryAction=create_formatted_value(
                period_deviation.predicted_battery_action, "energy_kwh_only", currency
            ),
            actualBatteryAction=create_formatted_value(
                period_deviation.actual_battery_action, "energy_kwh_only", currency
            ),
            batteryActionDeviation=create_formatted_value(
                period_deviation.battery_action_deviation, "energy_kwh_only", currency
            ),
            predictedConsumption=create_formatted_value(
                period_deviation.predicted_consumption, "energy_kwh_only", currency
            ),
            actualConsumption=create_formatted_value(
                period_deviation.actual_consumption, "energy_kwh_only", currency
            ),
            consumptionDeviation=create_formatted_value(
                period_deviation.consumption_deviation, "energy_kwh_only", currency
            ),
            predictedSolar=create_formatted_value(
                period_deviation.predicted_solar, "energy_kwh_only", currency
            ),
            actualSolar=create_formatted_value(
                period_deviation.actual_solar, "energy_kwh_only", currency
            ),
            solarDeviation=create_formatted_value(
                period_deviation.solar_deviation, "energy_kwh_only", currency
            ),
            predictedSavings=create_formatted_value(
                period_deviation.predicted_savings, "currency", currency
            ),
            actualSavings=create_formatted_value(
                period_deviation.actual_savings, "currency", currency
            ),
            savingsDeviation=create_formatted_value(
                period_deviation.savings_deviation, "currency", currency
            ),
            deviationType=period_deviation.deviation_type,
        )


@dataclass
class APISnapshotComparison:
    """API representation of snapshot comparison."""

    snapshotTimestamp: str
    snapshotPeriod: int
    comparisonTime: str
    periodDeviations: list[dict]  # List of APIPeriodDeviation as dicts
    totalPredictedSavings: FormattedValue
    totalActualSavings: FormattedValue
    savingsDeviation: FormattedValue
    primaryDeviationCause: str
    predictedGrowattSchedule: list[dict]  # TOU intervals from snapshot
    currentGrowattSchedule: list[dict]  # Current TOU intervals

    @classmethod
    def from_internal(cls, snapshot_comparison, currency: str) -> APISnapshotComparison:
        """Convert from internal SnapshotComparison to API format.

        Args:
            snapshot_comparison: SnapshotComparison object
            currency: Currency code for formatting

        Returns:
            APISnapshotComparison with camelCase fields
        """
        return cls(
            snapshotTimestamp=snapshot_comparison.reference_snapshot.snapshot_timestamp.isoformat(),
            snapshotPeriod=snapshot_comparison.reference_snapshot.optimization_period,
            comparisonTime=datetime.now().isoformat(),
            periodDeviations=[
                APIPeriodDeviation.from_internal(dev, currency).__dict__
                for dev in snapshot_comparison.period_deviations
            ],
            totalPredictedSavings=create_formatted_value(
                snapshot_comparison.total_predicted_savings, "currency", currency
            ),
            totalActualSavings=create_formatted_value(
                snapshot_comparison.total_actual_savings, "currency", currency
            ),
            savingsDeviation=create_formatted_value(
                snapshot_comparison.savings_deviation, "currency", currency
            ),
            primaryDeviationCause=snapshot_comparison.primary_deviation_cause,
            predictedGrowattSchedule=snapshot_comparison.predicted_growatt_schedule,
            currentGrowattSchedule=snapshot_comparison.current_growatt_schedule,
        )

    def to_internal_update(self) -> dict:
        """Convert API updates back to internal snake_case."""
        return {
            "area": self.area,
            "markup_rate": self.markupRate,
            "vat_multiplier": self.vatMultiplier,
            "additional_costs": self.additionalCosts,
            "tax_reduction": self.taxReduction,
            "min_profit": self.minProfit,
            "use_actual_price": self.useActualPrice,
        }


@dataclass
class APIDashboardHourlyData:
    """Dashboard hourly data with canonical FormattedValue interface."""

    # Metadata
    period: int
    dataSource: str
    timestamp: str | None

    # All user-facing data via FormattedValue - canonical naming
    solarProduction: FormattedValue
    homeConsumption: FormattedValue
    batterySocStart: FormattedValue
    batterySocEnd: FormattedValue
    batterySoeStart: FormattedValue
    batterySoeEnd: FormattedValue
    buyPrice: FormattedValue
    sellPrice: FormattedValue
    hourlyCost: FormattedValue
    hourlySavings: FormattedValue
    gridOnlyCost: FormattedValue
    solarOnlyCost: FormattedValue
    batteryAction: FormattedValue
    batteryCharged: FormattedValue
    batteryDischarged: FormattedValue
    gridImported: FormattedValue
    gridExported: FormattedValue

    # Detailed energy flows - automatically calculated in backend models
    solarToHome: FormattedValue
    solarToBattery: FormattedValue
    solarToGrid: FormattedValue
    gridToHome: FormattedValue
    gridToBattery: FormattedValue
    batteryToHome: FormattedValue
    batteryToGrid: FormattedValue

    # Solar-only scenario fields
    gridImportNeeded: (
        FormattedValue  # How much grid import needed in solar-only scenario
    )
    solarExcess: FormattedValue  # How much solar excess in solar-only scenario
    solarSavings: FormattedValue  # Savings from solar vs grid-only

    # Raw values for logic only
    strategicIntent: str
    directSolar: float

    @classmethod
    def from_internal(
        cls, hourly, battery_capacity: float, currency: str
    ) -> APIDashboardHourlyData:
        """Convert internal HourlyData to API format using pure dataclass approach."""

        def safe_format(value, unit_type):
            """Helper to safely format values using pure dataclass approach"""
            return create_formatted_value(value or 0, unit_type, currency)

        # Calculate derived values
        solar_production = hourly.energy.solar_production
        home_consumption = hourly.energy.home_consumption
        direct_solar = min(solar_production, home_consumption)

        # Period index (0-23 for hourly, 0-95 for quarterly)
        # Frontend correctly handles different resolutions via resolution parameter
        return cls(
            # Metadata
            period=hourly.period,
            dataSource="actual" if hourly.data_source == "actual" else "predicted",
            timestamp=hourly.timestamp.isoformat() if hourly.timestamp else None,
            # Energy flows
            solarProduction=safe_format(solar_production, "energy_kwh_only"),
            homeConsumption=safe_format(home_consumption, "energy_kwh_only"),
            # Battery state - EnergyData uses battery_soe (State of Energy in kWh)
            batterySocStart=safe_format(
                (hourly.energy.battery_soe_start / battery_capacity) * 100.0,
                "percentage",
            ),
            batterySocEnd=safe_format(
                (hourly.energy.battery_soe_end / battery_capacity) * 100.0,
                "percentage",
            ),
            batterySoeStart=safe_format(
                hourly.energy.battery_soe_start,
                "energy_kwh_only",
            ),
            batterySoeEnd=safe_format(
                hourly.energy.battery_soe_end,
                "energy_kwh_only",
            ),
            # Economic data
            buyPrice=safe_format(hourly.economic.buy_price, "price"),
            sellPrice=safe_format(hourly.economic.sell_price, "price"),
            hourlyCost=safe_format(hourly.economic.hourly_cost, "currency"),
            hourlySavings=safe_format(hourly.economic.hourly_savings, "currency"),
            gridOnlyCost=safe_format(hourly.economic.grid_only_cost, "currency"),
            solarOnlyCost=safe_format(hourly.economic.solar_only_cost, "currency"),
            # Battery control - use actual charge/discharge for historical data
            batteryAction=safe_format(
                (
                    # For historical data, calculate from actual charge/discharge
                    (hourly.energy.battery_charged - hourly.energy.battery_discharged)
                    if hourly.data_source == "actual"
                    # For predicted data, use the optimization decision
                    else (hourly.decision.battery_action or 0)
                ),
                "energy_kwh_only",
            ),
            batteryCharged=safe_format(
                hourly.energy.battery_charged,
                "energy_kwh_only",
            ),
            batteryDischarged=safe_format(
                hourly.energy.battery_discharged,
                "energy_kwh_only",
            ),
            # Grid interactions
            gridImported=safe_format(
                hourly.energy.grid_imported,
                "energy_kwh_only",
            ),
            gridExported=safe_format(
                hourly.energy.grid_exported,
                "energy_kwh_only",
            ),
            # Detailed energy flows - using existing calculated fields from backend models
            solarToHome=safe_format(
                hourly.energy.solar_to_home,
                "energy_kwh_only",
            ),
            solarToBattery=safe_format(
                hourly.energy.solar_to_battery,
                "energy_kwh_only",
            ),
            solarToGrid=safe_format(
                hourly.energy.solar_to_grid,
                "energy_kwh_only",
            ),
            gridToHome=safe_format(
                hourly.energy.grid_to_home,
                "energy_kwh_only",
            ),
            gridToBattery=safe_format(
                hourly.energy.grid_to_battery,
                "energy_kwh_only",
            ),
            batteryToHome=safe_format(
                hourly.energy.battery_to_home,
                "energy_kwh_only",
            ),
            batteryToGrid=safe_format(
                hourly.energy.battery_to_grid,
                "energy_kwh_only",
            ),
            # Solar-only scenario calculations
            gridImportNeeded=safe_format(
                max(0, home_consumption - solar_production),
                "energy_kwh_only",
            ),
            solarExcess=safe_format(
                max(0, solar_production - home_consumption),
                "energy_kwh_only",
            ),
            solarSavings=safe_format(
                hourly.economic.solar_savings,
                "currency",
            ),
            # Raw values for logic
            strategicIntent=hourly.decision.strategic_intent,
            directSolar=direct_solar,
        )


@dataclass
class APICostAndSavings:
    """Cost and savings data for SystemStatusCard component."""

    todaysCost: FormattedValue
    todaysSavings: FormattedValue
    gridOnlyCost: FormattedValue
    percentageSaved: FormattedValue


@dataclass
class APIDashboardSummary:
    """Dashboard summary with canonical FormattedValue interface."""

    # Cost scenarios
    gridOnlyCost: FormattedValue
    solarOnlyCost: FormattedValue
    optimizedCost: FormattedValue

    # Savings calculations
    totalSavings: FormattedValue
    solarSavings: FormattedValue
    batterySavings: FormattedValue

    # Energy totals
    totalSolarProduction: FormattedValue
    totalHomeConsumption: FormattedValue
    totalBatteryCharged: FormattedValue
    totalBatteryDischarged: FormattedValue
    totalGridImported: FormattedValue
    totalGridExported: FormattedValue

    # Detailed energy flows
    totalSolarToHome: FormattedValue
    totalSolarToBattery: FormattedValue
    totalSolarToGrid: FormattedValue
    totalGridToHome: FormattedValue
    totalGridToBattery: FormattedValue
    totalBatteryToHome: FormattedValue
    totalBatteryToGrid: FormattedValue

    # Percentages
    totalSavingsPercentage: FormattedValue
    solarSavingsPercentage: FormattedValue
    batterySavingsPercentage: FormattedValue
    gridToHomePercentage: FormattedValue
    gridToBatteryPercentage: FormattedValue
    solarToGridPercentage: FormattedValue
    batteryToGridPercentage: FormattedValue
    solarToBatteryPercentage: FormattedValue
    gridToBatteryChargedPercentage: FormattedValue
    batteryToHomePercentage: FormattedValue
    batteryToGridDischargedPercentage: FormattedValue
    selfConsumptionPercentage: FormattedValue

    # Efficiency metrics
    cycleCount: FormattedValue
    netBatteryAction: FormattedValue
    averagePrice: FormattedValue
    finalBatterySoe: FormattedValue

    @classmethod
    def from_totals(
        cls, totals: dict, costs: dict, battery_capacity: float, currency: str
    ) -> APIDashboardSummary:
        """Create summary from totals and cost calculations."""
        # Extract cost values
        total_grid_only_cost = costs["gridOnly"]
        total_solar_only_cost = costs["solarOnly"]
        total_optimized_cost = costs["optimized"]

        # Calculate savings
        solar_savings = total_grid_only_cost - total_solar_only_cost
        battery_savings = total_solar_only_cost - total_optimized_cost
        total_savings = total_grid_only_cost - total_optimized_cost

        def safe_percentage(numerator: float, denominator: float) -> float:
            """Safely calculate percentage"""
            return (numerator / denominator * 100) if denominator > 0 else 0

        return cls(
            # Cost scenarios
            gridOnlyCost=create_formatted_value(
                total_grid_only_cost, "currency", currency
            ),
            solarOnlyCost=create_formatted_value(
                total_solar_only_cost, "currency", currency
            ),
            optimizedCost=create_formatted_value(
                total_optimized_cost, "currency", currency
            ),
            # Savings calculations
            totalSavings=create_formatted_value(total_savings, "currency", currency),
            solarSavings=create_formatted_value(solar_savings, "currency", currency),
            batterySavings=create_formatted_value(
                battery_savings, "currency", currency
            ),
            # Energy totals
            totalSolarProduction=create_formatted_value(
                totals["totalSolarProduction"], "energy_kwh_only", currency
            ),
            totalHomeConsumption=create_formatted_value(
                totals["totalHomeConsumption"], "energy_kwh_only", currency
            ),
            totalBatteryCharged=create_formatted_value(
                totals["totalBatteryCharged"], "energy_kwh_only", currency
            ),
            totalBatteryDischarged=create_formatted_value(
                totals["totalBatteryDischarged"], "energy_kwh_only", currency
            ),
            totalGridImported=create_formatted_value(
                totals["totalGridImport"], "energy_kwh_only", currency
            ),
            totalGridExported=create_formatted_value(
                totals["totalGridExport"], "energy_kwh_only", currency
            ),
            # Detailed energy flows
            totalSolarToHome=create_formatted_value(
                totals["totalSolarToHome"], "energy_kwh_only", currency
            ),
            totalSolarToBattery=create_formatted_value(
                totals["totalSolarToBattery"], "energy_kwh_only", currency
            ),
            totalSolarToGrid=create_formatted_value(
                totals["totalSolarToGrid"], "energy_kwh_only", currency
            ),
            totalGridToHome=create_formatted_value(
                totals["totalGridToHome"], "energy_kwh_only", currency
            ),
            totalGridToBattery=create_formatted_value(
                totals["totalGridToBattery"], "energy_kwh_only", currency
            ),
            totalBatteryToHome=create_formatted_value(
                totals["totalBatteryToHome"], "energy_kwh_only", currency
            ),
            totalBatteryToGrid=create_formatted_value(
                totals["totalBatteryToGrid"], "energy_kwh_only", currency
            ),
            # Percentages
            totalSavingsPercentage=create_formatted_value(
                safe_percentage(total_savings, total_grid_only_cost),
                "percentage",
                currency,
            ),
            solarSavingsPercentage=create_formatted_value(
                safe_percentage(solar_savings, total_grid_only_cost),
                "percentage",
                currency,
            ),
            batterySavingsPercentage=create_formatted_value(
                safe_percentage(battery_savings, total_solar_only_cost),
                "percentage",
                currency,
            ),
            gridToHomePercentage=create_formatted_value(
                safe_percentage(totals["totalGridToHome"], totals["totalGridImport"]),
                "percentage",
                currency,
            ),
            gridToBatteryPercentage=create_formatted_value(
                safe_percentage(
                    totals["totalGridToBattery"], totals["totalGridImport"]
                ),
                "percentage",
                currency,
            ),
            solarToGridPercentage=create_formatted_value(
                safe_percentage(totals["totalSolarToGrid"], totals["totalGridExport"]),
                "percentage",
                currency,
            ),
            batteryToGridPercentage=create_formatted_value(
                safe_percentage(
                    totals["totalBatteryToGrid"], totals["totalGridExport"]
                ),
                "percentage",
                currency,
            ),
            solarToBatteryPercentage=create_formatted_value(
                safe_percentage(
                    totals["totalSolarToBattery"], totals["totalBatteryCharged"]
                ),
                "percentage",
                currency,
            ),
            gridToBatteryChargedPercentage=create_formatted_value(
                safe_percentage(
                    totals["totalGridToBattery"], totals["totalBatteryCharged"]
                ),
                "percentage",
                currency,
            ),
            batteryToHomePercentage=create_formatted_value(
                safe_percentage(
                    totals["totalBatteryToHome"], totals["totalBatteryDischarged"]
                ),
                "percentage",
                currency,
            ),
            batteryToGridDischargedPercentage=create_formatted_value(
                safe_percentage(
                    totals["totalBatteryToGrid"], totals["totalBatteryDischarged"]
                ),
                "percentage",
                currency,
            ),
            selfConsumptionPercentage=create_formatted_value(
                safe_percentage(
                    totals["totalSolarProduction"], totals["totalHomeConsumption"]
                ),
                "percentage",
                currency,
            ),
            # Efficiency metrics
            cycleCount=create_formatted_value(
                (
                    totals["totalBatteryCharged"] / battery_capacity
                    if battery_capacity > 0
                    else 0.0
                ),
                "",
                currency,
            ),
            netBatteryAction=create_formatted_value(
                totals["totalBatteryCharged"] - totals["totalBatteryDischarged"],
                "energy_kwh_only",
                currency,
            ),
            averagePrice=create_formatted_value(
                totals.get("avgBuyPrice", 0), "price", currency
            ),
            finalBatterySoe=create_formatted_value(
                totals.get("finalBatterySoe", 0), "energy_kwh_only", currency
            ),
        )


@dataclass
class APIDashboardResponse:
    """Complete dashboard response with canonical dataclass structure."""

    # Core metadata
    date: str
    currentPeriod: int

    # Financial summary
    totalDailySavings: float
    actualSavingsSoFar: float
    predictedRemainingSavings: float

    # Data structure info
    actualHoursCount: int
    predictedHoursCount: int
    dataSources: list[str]

    # Battery state
    batteryCapacity: float
    batterySoc: FormattedValue
    batterySoe: FormattedValue

    # Main data structures
    hourlyData: list[APIDashboardHourlyData]
    summary: APIDashboardSummary
    costAndSavings: APICostAndSavings
    realTimePower: APIRealTimePower
    strategicIntentSummary: dict[str, int]

    @classmethod
    def from_dashboard_data(
        cls,
        daily_view,
        controller,
        totals: dict,
        costs: dict,
        strategic_summary: dict,
        battery_soc: float,
        battery_capacity: float,
        currency: str,
        hourly_data_instances: list | None = None,
        resolution: str = "quarter-hourly",
    ) -> APIDashboardResponse:
        """Create complete dashboard response from internal data."""

        # Use pre-created hourly data instances to avoid duplication
        if hourly_data_instances is not None:
            hourly_data = hourly_data_instances
        else:
            # Fallback: create instances if not provided (for backward compatibility)
            hourly_data = [
                APIDashboardHourlyData.from_internal(hour, battery_capacity, currency)
                for hour in daily_view.hourly_data
            ]

        # Calculate detailed flow totals from the converted hourly data
        # (detailed flows are only available after APIDashboardHourlyData conversion)
        detailed_flow_totals = {
            "totalSolarToHome": sum(h.solarToHome.value for h in hourly_data),
            "totalSolarToBattery": sum(h.solarToBattery.value for h in hourly_data),
            "totalSolarToGrid": sum(h.solarToGrid.value for h in hourly_data),
            "totalGridToHome": sum(h.gridToHome.value for h in hourly_data),
            "totalGridToBattery": sum(h.gridToBattery.value for h in hourly_data),
            "totalBatteryToHome": sum(h.batteryToHome.value for h in hourly_data),
            "totalBatteryToGrid": sum(h.batteryToGrid.value for h in hourly_data),
        }

        # Override battery charged/discharged totals to match detailed flows perspective
        # Detailed flows represent GROSS energy (before efficiency losses)
        # This ensures percentages are correct: solar_to_battery + grid_to_battery = total_charged
        totals["totalBatteryCharged"] = (
            detailed_flow_totals["totalSolarToBattery"]
            + detailed_flow_totals["totalGridToBattery"]
        )
        totals["totalBatteryDischarged"] = (
            detailed_flow_totals["totalBatteryToHome"]
            + detailed_flow_totals["totalBatteryToGrid"]
        )

        # Combine basic totals with detailed flow totals
        complete_totals = {**totals, **detailed_flow_totals}

        # Create summary
        summary = APIDashboardSummary.from_totals(
            complete_totals, costs, battery_capacity, currency
        )

        # Create real-time power data
        real_time_power = APIRealTimePower.from_controller(controller)

        # Calculate current index based on resolution
        now = datetime.now()
        if resolution == "hourly":
            # For hourly resolution, use hour number (0-23)
            current_index = now.hour
            logger.debug(
                f"Hourly mode: currentPeriod={current_index} (hour={now.hour})"
            )
        else:
            # For quarterly resolution, use period index (0-95)
            current_index = now.hour * 4 + now.minute // 15
            logger.debug(
                f"Quarterly mode: currentPeriod={current_index} (hour={now.hour}, minute={now.minute})"
            )

        actual_data = [h for h in hourly_data if h.dataSource == "actual"]
        predicted_data = [h for h in hourly_data if h.dataSource == "predicted"]

        actual_savings = sum(h.hourlySavings.value for h in actual_data)
        predicted_savings = sum(h.hourlySavings.value for h in predicted_data)
        total_daily_savings = actual_savings + predicted_savings

        # Battery SOE calculation
        battery_soe = (battery_soc / 100.0) * battery_capacity

        # Create cost and savings data structure for SystemStatusCard
        cost_and_savings = APICostAndSavings(
            todaysCost=summary.optimizedCost,
            todaysSavings=summary.totalSavings,
            gridOnlyCost=summary.gridOnlyCost,
            percentageSaved=summary.totalSavingsPercentage,
        )

        return cls(
            # Core metadata
            date=daily_view.date.isoformat(),
            currentPeriod=current_index,
            # Financial summary
            totalDailySavings=total_daily_savings,
            actualSavingsSoFar=actual_savings,
            predictedRemainingSavings=predicted_savings,
            # Data structure info
            actualHoursCount=len(actual_data),
            predictedHoursCount=len(predicted_data),
            dataSources=list({h.dataSource for h in hourly_data}),
            # Battery state
            batteryCapacity=battery_capacity,
            batterySoc=create_formatted_value(battery_soc, "percentage", currency),
            batterySoe=create_formatted_value(battery_soe, "energy_kwh_only", currency),
            # Main data structures
            hourlyData=hourly_data,
            summary=summary,
            costAndSavings=cost_and_savings,
            realTimePower=real_time_power,
            strategicIntentSummary=strategic_summary,
        )


@dataclass
class APIRealTimePower:
    """Real-time power data with unified FormattedValue interface."""

    # Unified formatted values (no duplicates)
    solarPower: FormattedValue
    homeLoadPower: FormattedValue
    gridImportPower: FormattedValue
    gridExportPower: FormattedValue
    batteryChargePower: FormattedValue
    batteryDischargePower: FormattedValue
    netBatteryPower: FormattedValue
    netGridPower: FormattedValue
    selfPower: FormattedValue

    @classmethod
    def from_controller(cls, controller) -> APIRealTimePower:
        """Convert from controller readings to canonical camelCase."""

        # Get raw power values
        solar_power = controller.get_pv_power()
        home_load_power = controller.get_local_load_power()
        grid_import_power = controller.get_import_power()
        grid_export_power = controller.get_export_power()
        battery_charge_power = controller.get_battery_charge_power()
        battery_discharge_power = controller.get_battery_discharge_power()
        net_battery_power = controller.get_net_battery_power()
        net_grid_power = controller.get_net_grid_power()
        self_power = controller.get_self_power()

        def create_formatted_power(value):
            """Create formatted power value structure with thousands separators"""
            if abs(value) >= 1000:
                return FormattedValue(
                    value=value,
                    display=f"{value/1000:.1f}",
                    unit="kW",
                    text=f"{value/1000:.1f} kW",
                )
            else:
                return FormattedValue(
                    value=value,
                    display=f"{value:,.0f}",
                    unit="W",
                    text=f"{value:,.0f} W",
                )

        return cls(
            # Unified formatted values (no duplicates)
            solarPower=create_formatted_power(solar_power),
            homeLoadPower=create_formatted_power(home_load_power),
            gridImportPower=create_formatted_power(grid_import_power),
            gridExportPower=create_formatted_power(grid_export_power),
            batteryChargePower=create_formatted_power(battery_charge_power),
            batteryDischargePower=create_formatted_power(battery_discharge_power),
            netBatteryPower=create_formatted_power(net_battery_power),
            netGridPower=create_formatted_power(net_grid_power),
            selfPower=create_formatted_power(self_power),
        )
