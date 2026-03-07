"""Core configuration values and types for BESS using dataclasses.

IMPORTANT: This file contains DEFAULT VALUES only.

The values in this file serve as:
1. Settings for unit tests and development
2. Internal algorithm parameters not exposed to users

All user-facing settings should be configured and overridden via config.yaml:
- Battery settings (capacity, power, cycle_cost, min_action_profit_threshold)
- Electricity price settings (area, markup_rate, vat_multiplier, additional_costs, tax_reduction)
- Home settings (consumption, voltage, fuse_current, safety_margin_factor)

For production configuration, all user-facing values must be properly configured in config.yaml.
"""

import re
from dataclasses import dataclass, field
from typing import Any


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case.

    This matches the implementation in backend/api_conversion.py but is kept
    separate to maintain architectural separation between core and backend layers.
    """
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# Price settings defaults
DEFAULT_AREA = "SE4"
MARKUP_RATE = 0.08  # per kWh in configured currency
VAT_MULTIPLIER = 1.25  # 25% VAT
ADDITIONAL_COSTS = 1.03  # additional costs per kWh (grid fees, energy tax, etc.)
TAX_REDUCTION = 0.0518  # tax reduction for sold energy per kWh
MIN_PROFIT = 0.2  # Minimum profit per kWh to consider a charge/discharge cycle
USE_ACTUAL_PRICE = False  # Use raw Nordpool spot prices or include markup, VAT, etc.

# Battery settings defaults
BATTERY_STORAGE_SIZE_KWH = 30.0
BATTERY_MIN_SOC = 10  # percentage
BATTERY_MAX_SOC = 100  # percentage
BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW = 15.0
BATTERY_CHARGE_CYCLE_COST = 0.40  # per kWh excl. VAT
BATTERY_MIN_ACTION_PROFIT_THRESHOLD = (
    0.0  # fixed minimum profit threshold for any battery action (0.0 for tests)
)
BATTERY_DEFAULT_CHARGING_POWER_RATE = 40  # percentage
BATTERY_EFFICIENCY_CHARGE = 0.97  # Mix of solar (98%) and grid (95%) charging
BATTERY_EFFICIENCY_DISCHARGE = 0.95  # DC-AC conversion losses

# Default LFP temperature derating curve: (temp_celsius, charge_rate_percent)
# Based on LFP battery characteristics (Battery University, manufacturer data)
DEFAULT_TEMPERATURE_DERATING_CURVE: list[tuple[float, float]] = [
    (
        -1.0,
        20.0,
    ),  # Below 0°C: heavily limited (battery heaters may allow some charging)
    (0.0, 20.0),  # At 0°C: heavily limited
    (5.0, 50.0),  # At 5°C: significant derating
    (10.0, 80.0),  # At 10°C: mild derating
    (15.0, 100.0),  # At 15°C+: full rate
]

# Consumption settings defaults
HOME_HOURLY_CONSUMPTION_KWH = 4.6
MIN_CONSUMPTION = 0.1

# Home electrical defaults
HOUSE_MAX_FUSE_CURRENT_A = 25  # Maximum fuse current in amperes
HOUSE_VOLTAGE_V = 230  # Line voltage
SAFETY_MARGIN_FACTOR = 1.0  # Safety margin for power calculations (100%)
# Safe to use 1.0 based on fuse trip characteristics:
# - 108% load: many hours before trip
# - 128% load: 15min-2hrs before trip
# - We monitor every 5min, so 100% is safe

# Currency defaults
DEFAULT_CURRENCY = "SEK"  # Default currency for price display (override in config.yaml)


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
            # Convert camelCase to snake_case for compatibility with API layer
            snake_key = _camel_to_snake(key)
            if not hasattr(self, snake_key):
                raise AttributeError(
                    f"PriceSettings has no attribute '{snake_key}' (from key '{key}')"
                )
            setattr(self, snake_key, value)


@dataclass
class BatterySettings:
    """Battery settings with canonical snake_case names only."""

    total_capacity: float = BATTERY_STORAGE_SIZE_KWH
    min_soc: float = BATTERY_MIN_SOC  # percentage
    max_soc: float = BATTERY_MAX_SOC  # percentage
    max_charge_power_kw: float = BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
    max_discharge_power_kw: float = BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
    charging_power_rate: float = BATTERY_DEFAULT_CHARGING_POWER_RATE
    cycle_cost_per_kwh: float = BATTERY_CHARGE_CYCLE_COST
    min_action_profit_threshold: float = (
        BATTERY_MIN_ACTION_PROFIT_THRESHOLD  # NEW FIELD
    )
    efficiency_charge: float = BATTERY_EFFICIENCY_CHARGE
    efficiency_discharge: float = BATTERY_EFFICIENCY_DISCHARGE
    reserved_capacity: float = field(init=False)
    min_soe_kwh: float = field(init=False)
    max_soe_kwh: float = field(init=False)

    def __post_init__(self):
        self.min_soe_kwh = self.total_capacity * self.min_soc / 100.0
        self.max_soe_kwh = self.total_capacity * self.max_soc / 100.0
        self.reserved_capacity = self.min_soe_kwh

    def update(self, **kwargs: Any) -> None:
        """Update settings from dict."""
        for key, value in kwargs.items():
            # Convert camelCase to snake_case for compatibility with API layer
            snake_key = _camel_to_snake(key)
            if not hasattr(self, snake_key):
                raise AttributeError(
                    f"BatterySettings has no attribute '{snake_key}' (from key '{key}')"
                )
            setattr(self, snake_key, value)

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
                "cycle_cost_per_kwh", BATTERY_CHARGE_CYCLE_COST
            )
            self.min_action_profit_threshold = battery_config.get(
                "min_action_profit_threshold", BATTERY_MIN_ACTION_PROFIT_THRESHOLD
            )
            self.__post_init__()
        return self


@dataclass
class HomeSettings:
    """Home electrical settings."""

    max_fuse_current: int = HOUSE_MAX_FUSE_CURRENT_A
    voltage: int = HOUSE_VOLTAGE_V
    safety_margin: float = SAFETY_MARGIN_FACTOR
    phase_count: int = 3
    default_hourly: float = HOME_HOURLY_CONSUMPTION_KWH
    min_valid: float = MIN_CONSUMPTION
    currency: str = DEFAULT_CURRENCY
    consumption_strategy: str = "sensor"

    def __post_init__(self):
        assert self.phase_count in (
            1,
            3,
        ), f"phase_count must be 1 or 3, got {self.phase_count}"

    def update(self, **kwargs: Any) -> None:
        """Update settings from dict."""
        for key, value in kwargs.items():
            # Convert camelCase to snake_case for compatibility with API layer
            snake_key = _camel_to_snake(key)
            if not hasattr(self, snake_key):
                raise AttributeError(
                    f"HomeSettings has no attribute '{snake_key}' (from key '{key}')"
                )
            setattr(self, snake_key, value)
        self.__post_init__()

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
            self.phase_count = home_config.get("phase_count", 3)
            self.default_hourly = config["home"].get(
                "consumption", HOME_HOURLY_CONSUMPTION_KWH
            )
            self.currency = config["home"].get("currency", DEFAULT_CURRENCY)
            self.consumption_strategy = home_config.get(
                "consumption_strategy", "sensor"
            )
            self.__post_init__()
        return self


@dataclass
class TemperatureDeratingSettings:
    """Settings for temperature-based charge power derating.

    When enabled, the optimizer reduces max charge power based on forecasted
    outdoor temperature. This is important for batteries installed outdoors
    where cold temperatures reduce LFP charging capacity.

    Disabled by default since most batteries are installed indoors.
    """

    enabled: bool = False
    weather_entity: str = ""
    derating_curve: list[tuple[float, float]] = field(
        default_factory=lambda: list(DEFAULT_TEMPERATURE_DERATING_CURVE)
    )

    def from_ha_config(self, config: dict) -> "TemperatureDeratingSettings":
        """Load from add-on config."""
        battery_config = config.get("battery", {})
        derating_config = battery_config.get("temperature_derating", {})
        if derating_config:
            self.enabled = derating_config.get("enabled", False)
            self.weather_entity = derating_config.get("weather_entity", "")
            raw_curve = derating_config.get("derating_curve")
            if raw_curve:
                self.derating_curve = [
                    (float(point[0]), float(point[1])) for point in raw_curve
                ]
                self.derating_curve.sort(key=lambda p: p[0])
        return self


def interpolate_derating(temperature: float, curve: list[tuple[float, float]]) -> float:
    """Interpolate the derating curve to get charge rate percentage for a temperature.

    Args:
        temperature: Outdoor temperature in Celsius.
        curve: Sorted list of (temp_celsius, charge_rate_pct) points.

    Returns:
        Charge rate as a percentage (0-100).
    """
    if not curve:
        return 100.0

    # Below lowest point: use lowest point's value
    if temperature <= curve[0][0]:
        return curve[0][1]

    # Above highest point: use highest point's value
    if temperature >= curve[-1][0]:
        return curve[-1][1]

    # Find the two bracketing points and linearly interpolate
    for i in range(len(curve) - 1):
        t_low, rate_low = curve[i]
        t_high, rate_high = curve[i + 1]
        if t_low <= temperature <= t_high:
            fraction = (temperature - t_low) / (t_high - t_low)
            return rate_low + fraction * (rate_high - rate_low)

    return 100.0


def apply_temperature_derating(
    max_charge_power_kw: float,
    temperatures: list[float],
    derating_curve: list[tuple[float, float]],
) -> list[float]:
    """Calculate per-period max charge power based on temperature forecast.

    Args:
        max_charge_power_kw: Nominal max charge power in kW.
        temperatures: List of forecasted temperatures (one per period).
        derating_curve: Sorted list of (temp_celsius, charge_rate_pct) points.

    Returns:
        List of effective max charge power values (kW), one per period.
    """
    return [
        max_charge_power_kw * interpolate_derating(temp, derating_curve) / 100.0
        for temp in temperatures
    ]
