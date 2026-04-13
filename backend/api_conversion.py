"""Unified API conversion system - simple snake_case to camelCase conversion.

Also defines the canonical store→API field name mappings for each settings
section.  These dicts are the single source of truth for:
  - which fields are required at startup (_apply_settings in app.py)
  - how store snake_case names map to the camelCase names used by update_settings()

Both the startup path (app.py) and tests import from here so the mapping
can never drift between validation and usage.
"""

import re
from dataclasses import asdict, is_dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Canonical settings field mappings  (store snake_case → update_settings camelCase)
# ---------------------------------------------------------------------------

# Fields required at startup by build_system_settings().  Adding a key here
# makes it required in the bootstrap defaults and in contract tests.
# Note: charging_power_rate, efficiency_charge, efficiency_discharge are also
# in the store but have defaults and are not required at startup.
BATTERY_STORE_TO_API: dict[str, str] = {
    "total_capacity": "totalCapacity",
    "min_soc": "minSoc",
    "max_soc": "maxSoc",
    "cycle_cost_per_kwh": "cycleCostPerKwh",
    "max_charge_power_kw": "maxChargePowerKw",
    "max_discharge_power_kw": "maxDischargePowerKw",
    "min_action_profit_threshold": "minActionProfitThreshold",
}

HOME_STORE_TO_API: dict[str, str] = {
    "default_hourly": "defaultHourly",
    "currency": "currency",
    "max_fuse_current": "maxFuseCurrent",
    "voltage": "voltage",
    "safety_margin": "safetyMargin",
    "phase_count": "phaseCount",
    "consumption_strategy": "consumptionStrategy",
    "power_monitoring_enabled": "powerMonitoringEnabled",
}

PRICE_STORE_TO_API: dict[str, str] = {
    "area": "area",
    "markup_rate": "markupRate",
    "vat_multiplier": "vatMultiplier",
    "additional_costs": "additionalCosts",
    "tax_reduction": "taxReduction",
}


def build_system_settings(options: dict) -> dict:
    """Validate settings options and return the camelCase dict for update_settings().

    This is the pure transformation layer between the settings store (snake_case)
    and the in-memory system (camelCase).  It is intentionally a standalone
    function so it can be unit-tested without instantiating BESSController.

    Args:
        options: Dict with at minimum ``battery``, ``electricity_price``, and
                 ``home`` sections using store snake_case field names.

    Returns:
        Dict with ``battery``, ``home``, and ``price`` sections in camelCase,
        ready to pass to ``system.update_settings()``.

    Raises:
        ValueError: If a required section or field is missing.
    """
    required_sections = ["battery", "electricity_price", "home"]
    for section in required_sections:
        if section not in options:
            raise ValueError(
                f"Required configuration section '{section}' is missing"
            )

    battery_config = options["battery"]
    electricity_price_config = options["electricity_price"]
    home_config = options["home"]

    for key in BATTERY_STORE_TO_API:
        if key not in battery_config:
            raise ValueError(f"Required battery setting '{key}' is missing from config")
    for key in PRICE_STORE_TO_API:
        if key not in electricity_price_config:
            raise ValueError(
                f"Required electricity_price setting '{key}' is missing from config"
            )
    for key in HOME_STORE_TO_API:
        if key not in home_config:
            raise ValueError(f"Required home setting '{key}' is missing from config")

    return {
        "battery": {
            camel: battery_config[snake]
            for snake, camel in BATTERY_STORE_TO_API.items()
        },
        "home": {
            camel: home_config[snake]
            for snake, camel in HOME_STORE_TO_API.items()
        },
        "price": {
            camel: electricity_price_config[snake]
            for snake, camel in PRICE_STORE_TO_API.items()
        },
    }


def snake_to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(word.capitalize() for word in components[1:])


def camel_to_snake(camel_str: str) -> str:
    """Convert camelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", camel_str)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def convert_keys_to_camel_case(data: Any) -> Any:
    """Recursively convert all dict keys from snake_case to camelCase."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Convert snake_case to camelCase
            camel_key = snake_to_camel(key)
            result[camel_key] = convert_keys_to_camel_case(value)
        return result
    if isinstance(data, list):
        return [convert_keys_to_camel_case(item) for item in data]
    if is_dataclass(data) and not isinstance(data, type):
        # Convert dataclass instance to dict, then convert keys
        return convert_keys_to_camel_case(asdict(data))
    return data


def convert_keys_to_snake_case(data: Any) -> Any:
    """Recursively convert all dict keys from camelCase to snake_case."""
    if isinstance(data, dict):
        return {camel_to_snake(k): convert_keys_to_snake_case(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_keys_to_snake_case(item) for item in data]
    return data
