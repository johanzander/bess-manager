"""API DataClasses with canonical camelCase field names."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


@dataclass
class APIBatterySettings:
    """API response dataclass with canonical camelCase fields."""
    
    totalCapacity: float
    reservedCapacity: float
    minSoc: float
    maxSoc: float
    minSocKwh: float
    maxSocKwh: float
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
            minSocKwh=battery.min_soc_kwh,
            maxSocKwh=battery.max_soc_kwh,
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
    batterySocStart: float
    batterySocEnd: float
    solarToHome: float = 0.0
    solarToBattery: float = 0.0
    solarToGrid: float = 0.0
    gridToHome: float = 0.0
    gridToBattery: float = 0.0
    batteryToHome: float = 0.0
    batteryToGrid: float = 0.0
    
    @classmethod
    def from_internal(cls, energy) -> APIEnergyData:
        """Convert from internal snake_case to canonical camelCase."""
        return cls(
            solarProduction=energy.solar_generated,
            homeConsumption=energy.home_consumed,
            gridImported=energy.grid_imported,
            gridExported=energy.grid_exported,
            batteryCharged=energy.battery_charged,
            batteryDischarged=energy.battery_discharged,
            batterySocStart=energy.battery_soc_start,
            batterySocEnd=energy.battery_soc_end,
            solarToHome=energy.solar_to_home,
            solarToBattery=energy.solar_to_battery,
            solarToGrid=energy.solar_to_grid,
            gridToHome=energy.grid_to_home,
            gridToBattery=energy.grid_to_battery,
            batteryToHome=energy.battery_to_home,
            batteryToGrid=energy.battery_to_grid,
        )


def flatten_hourly_data(hourly) -> dict:
    """Flatten HourlyData to a single dict for frontend."""
    api_energy = APIEnergyData.from_internal(hourly.energy)
    
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
        "batterySocStart": api_energy.batterySocStart,
        "batterySocEnd": api_energy.batterySocEnd,
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
            "hourlyCost": hourly.economic.hourly_cost,
            "hourlySavings": hourly.economic.hourly_savings,
            "batteryCycleCost": hourly.economic.battery_cycle_cost,
            "gridCost": hourly.economic.grid_cost,
            "baseCost": hourly.economic.base_case_cost,
            "solarOnlyCost": hourly.economic.solar_only_cost,
            "batterySolarCost": hourly.economic.hourly_cost,  # battery+solar cost = hourly_cost
            "totalCost": hourly.economic.hourly_cost,
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
    
    # Debug logging to verify grid_exported is being properly passed through
    if "gridExported" in result: # TODO REMOVE once validated
        logger.debug(f"Flattened hourly data includes gridExported: {result['gridExported']}")
    else:
        logger.warning(f"gridExported missing from flattened hourly data for hour {hourly.hour}")
        
    return result