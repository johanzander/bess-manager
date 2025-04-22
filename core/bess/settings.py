# bess/settings.py

"""Core configuration values and types for BESS."""

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

# Consumption settings defaults
HOME_HOURLY_CONSUMPTION_KWH = 4.5
MIN_CONSUMPTION = 0.1

# Home electrical defaults
HOUSE_MAX_FUSE_CURRENT_A = 25  # Maximum fuse current in amperes
HOUSE_VOLTAGE_V = 230  # Line voltage
SAFETY_MARGIN_FACTOR = 0.95  # Safety margin for power calculations (95%)

# Replace Enum with a simple constant
AREA_CODES = ["SE1", "SE2", "SE3", "SE4"]


class PriceSettings:
    """Internal price settings."""

    def __init__(self) -> None:
        """Initialize with defaults."""
        self.area = DEFAULT_AREA
        self.markup_rate = MARKUP_RATE
        self.vat_multiplier = VAT_MULTIPLIER
        self.additional_costs = ADDITIONAL_COSTS
        self.tax_reduction = TAX_REDUCTION
        self.min_profit = MIN_PROFIT
        self.use_actual_price = USE_ACTUAL_PRICE

    def asdict(self):
        """Convert to dictionary for API."""
        return {
            "area": self.area,
            "markupRate": self.markup_rate,
            "vatMultiplier": self.vat_multiplier,
            "additionalCosts": self.additional_costs,
            "taxReduction": self.tax_reduction,
            "useActualPrice": self.use_actual_price,
        }

    def update(self, **kwargs) -> None:
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


class BatterySettings:
    """Internal battery settings."""

    def __init__(self) -> None:
        """Initialize with defaults."""
        self.total_capacity = BATTERY_STORAGE_SIZE_KWH
        self.min_soc = BATTERY_MIN_SOC
        self.max_soc = BATTERY_MAX_SOC
        self.max_charge_power_kw = BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW
        self.charging_power_rate = BATTERY_DEFAULT_CHARGING_POWER_RATE
        self.reserved_capacity = BATTERY_STORAGE_SIZE_KWH * self.min_soc / 100
        self.cycle_cost = BATTERY_CHARGE_CYCLE_COST_SEK

    def asdict(self):
        """Convert to dictionary for API."""
        return {
            "totalCapacity": self.total_capacity,
            "reservedCapacity": self.reserved_capacity,
            "minSoc": self.min_soc,
            "maxSoc": self.max_soc,
            "maxChargeDischarge": self.max_charge_power_kw,
            "chargeCycleCost": self.cycle_cost,
            "chargingPowerRate": self.charging_power_rate,
            "estimatedConsumption": 25.0 # FIXME
        }

    def update(self, **kwargs):
        """Update settings from dict."""
        conversions = {
            "totalCapacity": "total_capacity",
            "minSoc": "min_soc",
            "maxSoc": "max_soc",
            "maxChargeDischarge": "max_charge_rate",
            "chargeCycleCost": "cycle_cost",
            "chargingPowerRate": "charging_power_rate",
        }

        for key, value in kwargs.items():
            internal_key = conversions.get(key, key)
            if hasattr(self, internal_key):
                setattr(self, internal_key, value)


class ConsumptionSettings:
    """Internal consumption settings."""

    def __init__(self) -> None:
        """Initialize with defaults."""
        self.default_hourly = HOME_HOURLY_CONSUMPTION_KWH
        self.min_valid = MIN_CONSUMPTION

    def asdict(self):
        """Convert to dictionary for API."""
        return {
            "defaultHourly": self.default_hourly, 
            "minValid": self.min_valid,
            "estimatedConsumption": self.default_hourly}

    def update(self, **kwargs):
        """Update settings from dict."""
        conversions = {"defaultHourly": "default_hourly", "minValid": "min_valid"}

        for key, value in kwargs.items():
            internal_key = conversions.get(key, key)
            if hasattr(self, internal_key):
                setattr(self, internal_key, value)


class HomeSettings:
    """Internal home electrical settings."""

    def __init__(self) -> None:
        """Initialize with defaults."""
        self.max_fuse_current = HOUSE_MAX_FUSE_CURRENT_A
        self.voltage = HOUSE_VOLTAGE_V
        self.safety_margin = SAFETY_MARGIN_FACTOR

    def asdict(self):
        """Convert to dictionary for API."""
        return {
            "maxFuseCurrent": self.max_fuse_current,
            "voltage": self.voltage,
            "safetyMargin": self.safety_margin,
        }

    def update(self, **kwargs):
        """Update settings from dict."""
        conversions = {
            "maxFuseCurrent": "max_fuse_current",
            "voltage": "voltage",
            "safetyMargin": "safety_margin",
        }

        for key, value in kwargs.items():
            internal_key = conversions.get(key, key)
            if hasattr(self, internal_key):
                setattr(self, internal_key, value)
