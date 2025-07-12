"""API DataClasses with canonical camelCase field names."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class APIBatterySettings:
    """API response dataclass with canonical camelCase fields."""
    
    totalCapacity: float
    reservedCapacity: float
    minSoc: float
    maxSoc: float
    minSoeKwh: float  # State of Energy in kWh (not SOC percentage)
    maxSoeKwh: float  # State of Energy in kWh (not SOC percentage)
    maxChargePowerKw: float
    maxDischargePowerKw: float
    cycleCostPerKwh: float
    chargingPowerRate: float
    efficiencyCharge: float
    efficiencyDischarge: float
    estimatedConsumption: float
    
    @classmethod
    def from_internal(cls, battery, estimated_consumption: float) -> APIBatterySettings:
        """Convert from internal snake_case to canonical camelCase."""
        return cls(
            totalCapacity=battery.total_capacity,
            reservedCapacity=battery.reserved_capacity,
            minSoc=battery.min_soc,
            maxSoc=battery.max_soc,
            minSoeKwh=battery.min_soe_kwh,  # State of Energy in kWh
            maxSoeKwh=battery.max_soe_kwh,  # State of Energy in kWh
            maxChargePowerKw=battery.max_charge_power_kw,
            maxDischargePowerKw=battery.max_discharge_power_kw,
            cycleCostPerKwh=battery.cycle_cost_per_kwh,
            chargingPowerRate=battery.charging_power_rate,
            efficiencyCharge=battery.efficiency_charge,
            efficiencyDischarge=battery.efficiency_discharge,
            estimatedConsumption=estimated_consumption
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
            useActualPrice=price.use_actual_price
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
class APIHomeSettings:
    """API response dataclass with canonical camelCase fields for home settings."""
    
    maxFuseCurrent: int
    voltage: int
    safetyMargin: float
    defaultHourly: float
    minValid: float
    powerAdjustmentStep: int
    estimatedConsumption: float
    
    @classmethod
    def from_internal(cls, home) -> APIHomeSettings:
        """Convert from internal snake_case to canonical camelCase."""
        return cls(
            maxFuseCurrent=home.max_fuse_current,
            voltage=home.voltage,
            safetyMargin=home.safety_margin,
            defaultHourly=home.default_hourly,
            minValid=home.min_valid,
            powerAdjustmentStep=home.power_adjustment_step,
            estimatedConsumption=home.default_hourly  # Alias for frontend compatibility
        )
    
    def to_internal_update(self) -> dict:
        """Convert API updates back to internal snake_case."""
        return {
            "max_fuse_current": self.maxFuseCurrent,
            "voltage": self.voltage,
            "safety_margin": self.safetyMargin,
            "default_hourly": self.defaultHourly,
            "min_valid": self.minValid,
            "power_adjustment_step": self.powerAdjustmentStep,
        }


@dataclass
class APIEnergyData:
    """API response for energy data with canonical camelCase fields."""
    
    solarProduction: float
    homeConsumption: float
    gridImported: float
    gridExported: float
    batteryCharged: float
    batteryDischarged: float
    batterySoeStart: float  # State of Energy in kWh (renamed for clarity)
    batterySoeEnd: float    # State of Energy in kWh (renamed for clarity)
    batterySocStart: float  # Keep for backward compatibility (contains SOE values!)
    batterySocEnd: float    # Keep for backward compatibility (contains SOE values!)
    solarToHome: float = 0.0
    solarToBattery: float = 0.0
    solarToGrid: float = 0.0
    gridToHome: float = 0.0
    gridToBattery: float = 0.0
    batteryToHome: float = 0.0
    batteryToGrid: float = 0.0
    
    @classmethod
    def from_internal(cls, energy, battery_capacity: float = 30.0) -> APIEnergyData:
        """Convert from internal snake_case to canonical camelCase.
        
        Args:
            energy: Internal energy data with SOE values in kWh
            battery_capacity: Battery capacity in kWh for SOC conversion
        """
        # Convert SOE (kWh) to SOC (%) for backward compatibility
        soc_start = (energy.battery_soe_start / battery_capacity) * 100.0
        soc_end = (energy.battery_soe_end / battery_capacity) * 100.0
        
        return cls(
            solarProduction=energy.solar_generated,
            homeConsumption=energy.home_consumed,
            gridImported=energy.grid_imported,
            gridExported=energy.grid_exported,
            batteryCharged=energy.battery_charged,
            batteryDischarged=energy.battery_discharged,
            batterySoeStart=energy.battery_soe_start,  # Correct SOE field (kWh)
            batterySoeEnd=energy.battery_soe_end,      # Correct SOE field (kWh)
            batterySocStart=soc_start,  # Proper SOC field (%)
            batterySocEnd=soc_end,      # Proper SOC field (%)
            solarToHome=energy.solar_to_home,
            solarToBattery=energy.solar_to_battery,
            solarToGrid=energy.solar_to_grid,
            gridToHome=energy.grid_to_home,
            gridToBattery=energy.grid_to_battery,
            batteryToHome=energy.battery_to_home,
            batteryToGrid=energy.battery_to_grid,
        )


def flatten_hourly_data(hourly, battery_capacity: float = 30.0) -> dict:
    """Flatten HourlyData to a single dict for frontend.
    
    Args:
        hourly: HourlyData object to flatten
        battery_capacity: Battery capacity in kWh for SOC conversion
    """
    api_energy = APIEnergyData.from_internal(hourly.energy, battery_capacity)
    
    result = {
        "hour": hourly.hour,
        "dataSource": hourly.data_source,
        "timestamp": hourly.timestamp.isoformat() if hourly.timestamp else None,
        "solarProduction": api_energy.solarProduction,
        "homeConsumption": api_energy.homeConsumption,
        "gridImported": api_energy.gridImported,
        "gridExported": api_energy.gridExported,
        "batteryCharged": api_energy.batteryCharged,
        "batteryDischarged": api_energy.batteryDischarged,
        "batterySoeStart": api_energy.batterySoeStart,  # Correct SOE field (kWh)
        "batterySoeEnd": api_energy.batterySoeEnd,      # Correct SOE field (kWh)
        "batterySocStart": api_energy.batterySocStart,  # Proper SOC field (%)
        "batterySocEnd": api_energy.batterySocEnd,      # Proper SOC field (%)
        "solarToHome": api_energy.solarToHome,
        "solarToBattery": api_energy.solarToBattery,
        "solarToGrid": api_energy.solarToGrid,
        "gridToHome": api_energy.gridToHome,
        "gridToBattery": api_energy.gridToBattery,
        "batteryToHome": api_energy.batteryToHome,
        "batteryToGrid": api_energy.batteryToGrid,
    }
    
    if hourly.economic:
        result.update({
            "buyPrice": hourly.economic.buy_price,
            "sellPrice": hourly.economic.sell_price,
            "gridCost": hourly.economic.grid_cost,
            "batteryCycleCost": hourly.economic.battery_cycle_cost,
            "hourlyCost": hourly.economic.hourly_cost,
            "solarOnlyCost": hourly.economic.solar_only_cost,
            "gridOnlyCost": hourly.economic.grid_only_cost,  # Clear name for grid-only scenario
            "totalCost": hourly.economic.hourly_cost,  # Use hourly_cost as total_cost
            
            # Dashboard expects these specific field names (keeping for compatibility)
            "batterySolarCost": hourly.economic.hourly_cost,  # Dashboard looks for "batterySolarCost"
            "hourlySavings": hourly.economic.hourly_savings,  # Savings vs solar-only baseline
            
            # Calculate solar and battery savings with clear names
            "solarSavings": max(0, hourly.economic.grid_only_cost - hourly.economic.solar_only_cost),
            "batterySavings": hourly.economic.solar_only_cost - hourly.economic.hourly_cost,  # Allow negative savings
        })
    
    if hourly.decision:
        result.update({
            "strategicIntent": hourly.decision.strategic_intent,
            "batteryAction": hourly.decision.battery_action,
            "costBasis": hourly.decision.cost_basis,
            "patternName": hourly.decision.pattern_name,
            "description": hourly.decision.description,
            "economicChain": hourly.decision.economic_chain,
            "immediateValue": hourly.decision.immediate_value,
            "futureValue": hourly.decision.future_value,
            "netStrategyValue": hourly.decision.net_strategy_value,
        })
    
    return result