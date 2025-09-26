"""API DataClasses with canonical camelCase field names."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FormattedValue:
    """Formatted value structure for frontend display."""
    value: float
    display: str
    unit: str
    text: str


def create_formatted_value(value: float, unit_type: str, battery_capacity: float = 30.0, precision: int | None = None) -> FormattedValue:
    """Create FormattedValue with optional precision override.

    Args:
        value: The numeric value to format
        unit_type: Type of unit ("currency", "energy_kwh_only", "percentage", "price", etc.)
        battery_capacity: Battery capacity for SOE to SOC conversion
        precision: Override default decimal places (None = use defaults: currency=2, energy=2, percentage=1, price=2)
    """
    if unit_type == "currency":
        prec = precision if precision is not None else 2
        return FormattedValue(
            value=value,
            display=f"{value:,.{prec}f}",
            unit="SEK",
            text=f"{value:,.{prec}f} SEK"
        )
    elif unit_type == "energy_kwh_only":
        # Always use kWh units to ensure consistency in savings view
        # Small values like 0.2 kWh should remain as "0.2 kWh", not "200 Wh"
        prec = precision if precision is not None else 1
        return FormattedValue(
            value=value,
            display=f"{value:.{prec}f}",
            unit="kWh",
            text=f"{value:.{prec}f} kWh"
        )
    elif unit_type == "percentage":
        prec = precision if precision is not None else 0
        return FormattedValue(
            value=value,
            display=f"{value:.{prec}f}",
            unit="%",
            text=f"{value:.{prec}f} %"
        )
    elif unit_type == "price":
        prec = precision if precision is not None else 2
        return FormattedValue(
            value=value,
            display=f"{value:.{prec}f}",
            unit="öre/kWh",
            text=f"{value:.{prec}f} öre/kWh"
        )
    else:
        # Default fallback
        return FormattedValue(
            value=value,
            display=f"{value:.2f}",
            unit="",
            text=f"{value:.2f}"
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
    hour: int
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
    gridImportNeeded: FormattedValue  # How much grid import needed in solar-only scenario
    solarExcess: FormattedValue       # How much solar excess in solar-only scenario
    solarSavings: FormattedValue      # Savings from solar vs grid-only

    # Raw values for logic only
    strategicIntent: str
    directSolar: float

    @classmethod
    def from_internal(cls, hourly, battery_capacity: float) -> APIDashboardHourlyData:
        """Convert internal HourlyData to API format using pure dataclass approach."""
        def safe_format(value, unit_type):
            """Helper to safely format values using pure dataclass approach"""
            return create_formatted_value(value or 0, unit_type, battery_capacity)

        # Calculate derived values
        solar_production = hourly.energy.solar_production if hourly.energy else 0
        home_consumption = hourly.energy.home_consumption if hourly.energy else 0
        direct_solar = min(solar_production, home_consumption)

        return cls(
            # Metadata
            hour=hourly.hour,
            dataSource="actual" if hourly.data_source == "actual" else "predicted",
            timestamp=hourly.timestamp.isoformat() if hourly.timestamp else None,

            # Energy flows
            solarProduction=safe_format(solar_production, "energy_kwh_only"),
            homeConsumption=safe_format(home_consumption, "energy_kwh_only"),

            # Battery state
            batterySocStart=safe_format(
                (hourly.energy.battery_soe_start / battery_capacity) * 100.0
                if hasattr(hourly.energy, 'battery_soe_start') and hourly.energy
                else getattr(hourly.energy, 'battery_soc_start', 0) if hourly.energy else 0,
                "percentage"
            ),
            batterySocEnd=safe_format(
                (hourly.energy.battery_soe_end / battery_capacity) * 100.0
                if hasattr(hourly.energy, 'battery_soe_end') and hourly.energy
                else getattr(hourly.energy, 'battery_soc_end', 0) if hourly.energy else 0,
                "percentage"
            ),
            batterySoeStart=safe_format(
                getattr(hourly.energy, 'battery_soe_start', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            batterySoeEnd=safe_format(
                getattr(hourly.energy, 'battery_soe_end', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),

            # Economic data
            buyPrice=safe_format(hourly.economic.buy_price if hourly.economic else 0, "price"),
            sellPrice=safe_format(hourly.economic.sell_price if hourly.economic else 0, "price"),
            hourlyCost=safe_format(hourly.economic.hourly_cost if hourly.economic else 0, "currency"),
            hourlySavings=safe_format(hourly.economic.hourly_savings if hourly.economic else 0, "currency"),
            gridOnlyCost=safe_format(hourly.economic.grid_only_cost if hourly.economic else 0, "currency"),
            solarOnlyCost=safe_format(hourly.economic.solar_only_cost if hourly.economic else 0, "currency"),

            # Battery control
            batteryAction=safe_format(
                getattr(hourly.decision, 'battery_action', 0) if hourly.decision else 0,
                "energy_kwh_only"
            ),
            batteryCharged=safe_format(
                getattr(hourly.energy, 'battery_charged', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            batteryDischarged=safe_format(
                getattr(hourly.energy, 'battery_discharged', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),

            # Grid interactions
            gridImported=safe_format(
                getattr(hourly.energy, 'grid_imported', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            gridExported=safe_format(
                getattr(hourly.energy, 'grid_exported', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),

            # Detailed energy flows - using existing calculated fields from backend models
            solarToHome=safe_format(
                getattr(hourly.energy, 'solar_to_home', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            solarToBattery=safe_format(
                getattr(hourly.energy, 'solar_to_battery', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            solarToGrid=safe_format(
                getattr(hourly.energy, 'solar_to_grid', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            gridToHome=safe_format(
                getattr(hourly.energy, 'grid_to_home', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            gridToBattery=safe_format(
                getattr(hourly.energy, 'grid_to_battery', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            batteryToHome=safe_format(
                getattr(hourly.energy, 'battery_to_home', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),
            batteryToGrid=safe_format(
                getattr(hourly.energy, 'battery_to_grid', 0) if hourly.energy else 0,
                "energy_kwh_only"
            ),

            # Solar-only scenario calculations
            gridImportNeeded=safe_format(
                max(0, home_consumption - solar_production),  # Grid import needed if solar < consumption
                "energy_kwh_only"
            ),
            solarExcess=safe_format(
                max(0, solar_production - home_consumption),  # Solar excess if solar > consumption
                "energy_kwh_only"
            ),
            solarSavings=safe_format(
                getattr(hourly.economic, 'solar_savings', 0) if hourly.economic else 0,
                "currency"
            ),

            # Raw values for logic
            strategicIntent=getattr(hourly.decision, 'strategic_intent', '') if hourly.decision else '',
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
    def from_totals(cls, totals: dict, costs: dict, battery_capacity: float) -> APIDashboardSummary:
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
            gridOnlyCost=create_formatted_value(total_grid_only_cost, "currency", battery_capacity),
            solarOnlyCost=create_formatted_value(total_solar_only_cost, "currency", battery_capacity),
            optimizedCost=create_formatted_value(total_optimized_cost, "currency", battery_capacity),

            # Savings calculations
            totalSavings=create_formatted_value(total_savings, "currency", battery_capacity),
            solarSavings=create_formatted_value(solar_savings, "currency", battery_capacity),
            batterySavings=create_formatted_value(battery_savings, "currency", battery_capacity),

            # Energy totals
            totalSolarProduction=create_formatted_value(totals["totalSolarProduction"], "energy_kwh_only", battery_capacity),
            totalHomeConsumption=create_formatted_value(totals["totalHomeConsumption"], "energy_kwh_only", battery_capacity),
            totalBatteryCharged=create_formatted_value(totals["totalBatteryCharged"], "energy_kwh_only", battery_capacity),
            totalBatteryDischarged=create_formatted_value(totals["totalBatteryDischarged"], "energy_kwh_only", battery_capacity),
            totalGridImported=create_formatted_value(totals["totalGridImport"], "energy_kwh_only", battery_capacity),
            totalGridExported=create_formatted_value(totals["totalGridExport"], "energy_kwh_only", battery_capacity),

            # Detailed energy flows
            totalSolarToHome=create_formatted_value(totals["totalSolarToHome"], "energy_kwh_only", battery_capacity),
            totalSolarToBattery=create_formatted_value(totals["totalSolarToBattery"], "energy_kwh_only", battery_capacity),
            totalSolarToGrid=create_formatted_value(totals["totalSolarToGrid"], "energy_kwh_only", battery_capacity),
            totalGridToHome=create_formatted_value(totals["totalGridToHome"], "energy_kwh_only", battery_capacity),
            totalGridToBattery=create_formatted_value(totals["totalGridToBattery"], "energy_kwh_only", battery_capacity),
            totalBatteryToHome=create_formatted_value(totals["totalBatteryToHome"], "energy_kwh_only", battery_capacity),
            totalBatteryToGrid=create_formatted_value(totals["totalBatteryToGrid"], "energy_kwh_only", battery_capacity),

            # Percentages
            totalSavingsPercentage=create_formatted_value(safe_percentage(total_savings, total_grid_only_cost), "percentage", battery_capacity),
            solarSavingsPercentage=create_formatted_value(safe_percentage(solar_savings, total_grid_only_cost), "percentage", battery_capacity),
            batterySavingsPercentage=create_formatted_value(safe_percentage(battery_savings, total_solar_only_cost), "percentage", battery_capacity),
            gridToHomePercentage=create_formatted_value(safe_percentage(totals["totalGridToHome"], totals["totalGridImport"]), "percentage", battery_capacity),
            gridToBatteryPercentage=create_formatted_value(safe_percentage(totals["totalGridToBattery"], totals["totalGridImport"]), "percentage"),
            solarToGridPercentage=create_formatted_value(safe_percentage(totals["totalSolarToGrid"], totals["totalGridExport"]), "percentage"),
            batteryToGridPercentage=create_formatted_value(safe_percentage(totals["totalBatteryToGrid"], totals["totalGridExport"]), "percentage"),
            solarToBatteryPercentage=create_formatted_value(safe_percentage(totals["totalSolarToBattery"], totals["totalBatteryCharged"]), "percentage"),
            gridToBatteryChargedPercentage=create_formatted_value(safe_percentage(totals["totalGridToBattery"], totals["totalBatteryCharged"]), "percentage"),
            batteryToHomePercentage=create_formatted_value(safe_percentage(totals["totalBatteryToHome"], totals["totalBatteryDischarged"]), "percentage"),
            batteryToGridDischargedPercentage=create_formatted_value(safe_percentage(totals["totalBatteryToGrid"], totals["totalBatteryDischarged"]), "percentage"),
            selfConsumptionPercentage=create_formatted_value(safe_percentage(totals["totalSolarProduction"], totals["totalHomeConsumption"]), "percentage"),

            # Efficiency metrics
            cycleCount=create_formatted_value(totals["totalBatteryCharged"] / battery_capacity if battery_capacity > 0 else 0.0, "", battery_capacity),
            netBatteryAction=create_formatted_value(totals["totalBatteryCharged"] - totals["totalBatteryDischarged"], "energy_kwh_only", battery_capacity),
            averagePrice=create_formatted_value(totals.get("avgBuyPrice", 0), "price", battery_capacity),
            finalBatterySoe=create_formatted_value(totals.get("finalBatterySoe", 0), "energy_kwh_only", battery_capacity),
        )


@dataclass
class APIDashboardResponse:
    """Complete dashboard response with canonical dataclass structure."""

    # Core metadata
    date: str
    currentHour: int

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
        hourly_data_instances: list | None = None
    ) -> APIDashboardResponse:
        """Create complete dashboard response from internal data."""

        # Use pre-created hourly data instances to avoid duplication
        if hourly_data_instances is not None:
            hourly_data = hourly_data_instances
        else:
            # Fallback: create instances if not provided (for backward compatibility)
            hourly_data = [
                APIDashboardHourlyData.from_internal(hour, battery_capacity)
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

        # Combine basic totals with detailed flow totals
        complete_totals = {**totals, **detailed_flow_totals}

        # Create summary
        summary = APIDashboardSummary.from_totals(complete_totals, costs, battery_capacity)

        # Create real-time power data
        real_time_power = APIRealTimePower.from_controller(controller)

        # Calculate derived financial values
        current_hour = daily_view.current_hour
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
            currentHour=current_hour,

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
            batterySoc=create_formatted_value(battery_soc, "percentage", battery_capacity),
            batterySoe=create_formatted_value(battery_soe, "energy_kwh_only", battery_capacity),

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
    acPower: FormattedValue
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
        ac_power = controller.get_ac_power()
        self_power = controller.get_self_power()
        
        def create_formatted_power(value):
            """Create formatted power value structure with thousands separators"""
            if abs(value) >= 1000:
                return FormattedValue(
                    value=value,
                    display=f"{value/1000:.1f}",
                    unit="kW",
                    text=f"{value/1000:.1f} kW"
                )
            else:
                return FormattedValue(
                    value=value,
                    display=f"{value:,.0f}",
                    unit="W",
                    text=f"{value:,.0f} W"
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
            acPower=create_formatted_power(ac_power),
            selfPower=create_formatted_power(self_power),
        )






