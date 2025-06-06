"""Core configuration values and types for BESS using dataclasses."""

from dataclasses import dataclass, field
from typing import Any

# Price settings defaults
DEFAULT_AREA = "SE4"
MARKUP_RATE = 0.08  # 8 öre/kWh
VAT_MULTIPLIER = 1.25  # 25% VAT
ADDITIONAL_COSTS = (
    1.03  # överföringsavgift: 28.90 öre, energiskatt: 53.50 öre + 25% moms
)
TAX_REDUCTION = 0.6518  # 60 öre skattereduktion + 5.18 öre förlustersättning
MIN_PROFIT = 0.2  # Minimim profit (SEK/kWh) to consider a charge/discharge cycle
USE_ACTUAL_PRICE = False  # Use raw Nordpool spot prices or includue markup, VAT, etc.

# Battery settings defaults
BATTERY_STORAGE_SIZE_KWH = 30.0
BATTERY_MIN_SOC = 10  # percentage
BATTERY_MAX_SOC = 100  # percentage
BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW = 15.0
BATTERY_CHARGE_CYCLE_COST_SEK = 0.40  # SEK/kWh excl. VAT
BATTERY_DEFAULT_CHARGING_POWER_RATE = 40  # percentage
BATTERY_EFFICIENCY_CHARGE = 0.95  # 95% charging efficiency
BATTERY_EFFICIENCY_DISCHARGE = 0.95  # 95% discharging efficiency

# Consumption settings defaults
HOME_HOURLY_CONSUMPTION_KWH = 4.6
MIN_CONSUMPTION = 0.1

# Home electrical defaults
HOUSE_MAX_FUSE_CURRENT_A = 25  # Maximum fuse current in amperes
HOUSE_VOLTAGE_V = 230  # Line voltage
SAFETY_MARGIN_FACTOR = 0.95  # Safety margin for power calculations (95%)

# Replace Enum with a simple constant
AREA_CODES = ["SE1", "SE2", "SE3", "SE4"]


@dataclass
class PriceSettings:
    """Price settings for electricity costs."""

    area: str = DEFAULT_AREA
    markup_rate: float = MARKUP_RATE
    vat_multiplier: float = VAT_MULTIPLIER
    additional_costs: float = ADDITIONAL_COSTS
    tax_reduction: float = TAX_REDUCTION
    min_profit: float = MIN_PROFIT
    use_actual_price: bool = USE_ACTUAL_PRICE

    def asdict(self) -> dict:
        """Convert to dictionary for API."""
        return {
            "area": self.area,
            "markupRate": self.markup_rate,
            "vatMultiplier": self.vat_multiplier,
            "additionalCosts": self.additional_costs,
            "taxReduction": self.tax_reduction,
            "useActualPrice": self.use_actual_price,
        }

    def update(self, **kwargs: dict[str, Any]) -> None:
        """Update settings from dict."""
        conversions = {
            "markupRate": "markup_rate",
            "vatMultiplier": "vat_multiplier",
            "additionalCosts": "additional_costs",
            "taxReduction": "tax_reduction",
            "minProfit": "min_profit",
            "useActualPrice": "use_actual_price",
        }

        for key, value in kwargs.items():
            internal_key = conversions.get(key, key)
            if hasattr(self, internal_key):
                setattr(self, internal_key, value)


@dataclass
class BatterySettings:
    """Battery settings with canonical, modern attribute names only."""

    total_capacity: float = BATTERY_STORAGE_SIZE_KWH
    min_soc: float = BATTERY_MIN_SOC  # percentage
    max_soc: float = BATTERY_MAX_SOC  # percentage
    max_charge_power_kw: float = BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
    max_discharge_power_kw: float = BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
    charging_power_rate: float = BATTERY_DEFAULT_CHARGING_POWER_RATE
    cycle_cost_per_kwh: float = BATTERY_CHARGE_CYCLE_COST_SEK
    efficiency_charge: float = BATTERY_EFFICIENCY_CHARGE
    efficiency_discharge: float = BATTERY_EFFICIENCY_DISCHARGE
    reserved_capacity: float = field(init=False)
    min_soc_kwh: float = field(init=False)
    max_soc_kwh: float = field(init=False)
    cycle_cost: float = field(init=False)

    def __post_init__(self):
        self.reserved_capacity = self.total_capacity * self.min_soc / 100.0
        self.min_soc_kwh = self.reserved_capacity
        self.max_soc_kwh = self.total_capacity
        self.cycle_cost = self.cycle_cost_per_kwh

    def asdict(self) -> dict:
        """Convert to dictionary for API, using only canonical (snake_case) keys."""
        return {
            "total_capacity": self.total_capacity,
            "reserved_capacity": self.reserved_capacity,
            "min_soc": self.min_soc,
            "max_soc": self.max_soc,
            "min_soc_kwh": self.min_soc_kwh,
            "max_soc_kwh": self.max_soc_kwh,
            "max_charge_power_kw": self.max_charge_power_kw,
            "max_discharge_power_kw": self.max_discharge_power_kw,
            "cycle_cost": self.cycle_cost,
            "charging_power_rate": self.charging_power_rate,
            "efficiency_charge": self.efficiency_charge,
            "efficiency_discharge": self.efficiency_discharge,
        }

    def update(self, **kwargs: dict[str, Any]) -> None:
        from loguru import logger

        logger.debug(f"BatterySettings.update called with: {kwargs}")

        conversions = {
            "totalCapacity": "total_capacity",
            "minSoc": "min_soc",
            "maxSoc": "max_soc",
            "maxChargeDischarge": "max_charge_power_kw",  # Keep this for compatibility
            "chargeCycleCost": "cycle_cost",
            "chargingPowerRate": "charging_power_rate",
            "efficiencyCharge": "efficiency_charge",
            "efficiencyDischarge": "efficiency_discharge",
        }

        # Handle special case for combined charge/discharge power
        # This ensures both values get updated when either is present
        if "maxChargeDischarge" in kwargs:
            value = kwargs["maxChargeDischarge"]
            logger.debug(
                f"Setting max_charge_power_kw and max_discharge_power_kw to {value} from maxChargeDischarge"
            )
            self.max_charge_power_kw = value
            self.max_discharge_power_kw = value

        if "maxChargeDischargePower" in kwargs:
            value = kwargs["maxChargeDischargePower"]
            logger.debug(
                f"Setting max_charge_power_kw and max_discharge_power_kw to {value} from maxChargeDischargePower"
            )
            self.max_discharge_power_kw = kwargs["maxChargeDischargePower"]

        # Process all other keys normally
        for key, value in kwargs.items():
            if key != "maxChargeDischarge" and key != "maxChargeDischargePower":
                internal_key = conversions.get(key, key)
                if hasattr(self, internal_key):
                    from loguru import logger

                    logger.debug(f"Setting {internal_key} to {value} from {key}")
                    setattr(self, internal_key, value)

        # Add logging to show final values
        from loguru import logger

        logger.debug(
            f"After update: max_charge_power_kw={self.max_charge_power_kw}, max_discharge_power_kw={self.max_discharge_power_kw}"
        )
        self.__post_init__()

    def from_ha_config(self, config: dict) -> "BatterySettings":
        if "battery" in config:
            battery_config = config["battery"]
            self.total_capacity = battery_config.get(
                "total_capacity", BATTERY_STORAGE_SIZE_KWH
            )
            self.max_charge_power_kw = battery_config.get(
                "max_charge_power_kw", BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
            )
            self.max_discharge_power_kw = battery_config.get(
                "max_discharge_power_kw", BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
            )
            if "cycle_cost" in battery_config:  # TODO FIXME
                self.cycle_cost_per_kwh = battery_config.get(
                    "cycle_cost", BATTERY_CHARGE_CYCLE_COST_SEK
                )
            else:
                self.cycle_cost_per_kwh = battery_config.get(
                    "cycle_cost_per_kwh", BATTERY_CHARGE_CYCLE_COST_SEK
                )
            self.__post_init__()
        return self


@dataclass
class HomeSettings:
    """Home electrical settings."""

    max_fuse_current: int = HOUSE_MAX_FUSE_CURRENT_A
    voltage: int = HOUSE_VOLTAGE_V
    safety_margin: float = SAFETY_MARGIN_FACTOR
    default_hourly: float = HOME_HOURLY_CONSUMPTION_KWH
    min_valid: float = MIN_CONSUMPTION
    power_adjustment_step: int = 10

    def asdict(self) -> dict:
        """Convert to dictionary for API."""
        return {
            "maxFuseCurrent": self.max_fuse_current,
            "voltage": self.voltage,
            "safetyMargin": self.safety_margin,
            "defaultHourly": self.default_hourly,
            "minValid": self.min_valid,
            "estimatedConsumption": self.default_hourly,
        }

    def update(self, **kwargs: dict[str, Any]) -> None:
        """Update settings from dict."""
        conversions = {
            "maxFuseCurrent": "max_fuse_current",
            "voltage": "voltage",
            "safetyMargin": "safety_margin",
            "defaultHourly": "default_hourly",
            "minValid": "min_valid",
        }

        for key, value in kwargs.items():
            internal_key = conversions.get(key, key)
            if hasattr(self, internal_key):
                setattr(self, internal_key, value)

    def from_ha_config(self, config: dict) -> "HomeSettings":
        """Create instance from Home Assistant add-on config."""
        if "home" in config:
            home_config = config["home"]
            self.max_fuse_current = home_config.get(
                "max_fuse_current", HOUSE_MAX_FUSE_CURRENT_A
            )
            self.voltage = home_config.get("voltage", HOUSE_VOLTAGE_V)
            self.safety_margin = home_config.get(
                "safety_margin_factor", SAFETY_MARGIN_FACTOR
            )
            self.default_hourly = config["home"].get(
                "consumption", HOME_HOURLY_CONSUMPTION_KWH
            )
        return self
