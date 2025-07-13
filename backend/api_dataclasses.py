"""API DataClasses with canonical camelCase field names."""

from __future__ import annotations

from dataclasses import dataclass

from api_conversion import APIConverter


@dataclass
class APIBatterySettings:
    """Battery settings with clear SOC/SOE naming."""
    
    totalCapacity: float        # kWh - total battery capacity
    reservedCapacity: float     # kWh - reserved capacity
    
    # State of Charge limits (%)
    minSoc: float              # % (0-100) - minimum charge percentage
    maxSoc: float              # % (0-100) - maximum charge percentage  
    
    # State of Energy limits (kWh) - calculated from SOC
    minSoeKwh: float           # kWh - minimum energy (calculated)
    maxSoeKwh: float           # kWh - maximum energy (calculated)
    
    # Power limits (kW)
    maxChargePowerKw: float    # kW - maximum charge power
    maxDischargePowerKw: float # kW - maximum discharge power
    
    # Economic settings
    cycleCostPerKwh: float     # SEK/kWh - cost per cycle
    chargingPowerRate: float   # % - charging power rate
    efficiencyCharge: float    # % - charging efficiency
    efficiencyDischarge: float # % - discharge efficiency
    estimatedConsumption: float # kWh - estimated daily consumption
    
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


def flatten_hourly_data(hourly, battery_capacity: float = 30.0) -> dict:
    """Convert HourlyData to API dict using unified conversion system."""
    converter = APIConverter(battery_capacity)
    return converter.convert_hourly_data(hourly)