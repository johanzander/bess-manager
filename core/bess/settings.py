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
BATTERY_EFFICIENCY_CHARGE = 0.97  # Mix of solar (98%) and grid (95%) charging
BATTERY_EFFICIENCY_DISCHARGE = 0.95  # DC-AC conversion losses

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

    def update(self, **kwargs: Any) -> None:
        """Update settings from dict."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


@dataclass
class BatterySettings:
    """Battery settings with canonical snake_case names only."""

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

    def __post_init__(self):
        self.reserved_capacity = self.total_capacity * self.min_soc / 100.0
        self.min_soc_kwh = self.reserved_capacity
        self.max_soc_kwh = self.total_capacity

    def update(self, **kwargs: Any) -> None:
        """Update settings from dict."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                # Handle combined power settings
                if key == "max_charge_power_kw":
                    self.max_discharge_power_kw = value

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

    def update(self, **kwargs: Any) -> None:
        """Update settings from dict."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

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