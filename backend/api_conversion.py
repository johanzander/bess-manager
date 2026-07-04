"""Unified API conversion system - simple snake_case to camelCase conversion.

Also defines the canonical settings field requirements for each section —
the single source of truth for which fields are required at startup
(_apply_settings in app.py). Battery/Home/Price all reach update_settings()
in snake_case (the store's native format) unchanged — none of the
BatterySettings/HomeSettings/PriceSettings.update() methods translate
camelCase (issue #197, extended to Battery/Home in #219). CamelCase API
payloads are converted to snake_case in the API layer, not in
core/bess/settings.py.

Both the startup path (app.py) and tests import from here so the
requirements can never drift between validation and usage.
"""

import dataclasses
import re
from dataclasses import asdict, is_dataclass
from typing import Any

from core.bess.settings import BatterySettings, HomeSettings

# ---------------------------------------------------------------------------
# Canonical settings field requirements
# ---------------------------------------------------------------------------

# Fields required at startup by build_system_settings(). Adding a key here
# makes it required in the bootstrap defaults and in contract tests.
# Note: charging_power_rate, efficiency_charge, efficiency_discharge are also
# in the store (see BATTERY_MODEL_ATTRS below) but have class defaults and
# are not required at startup — a store missing them still boots, using
# the default.
BATTERY_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "total_capacity",
        "min_soc",
        "max_soc",
        "cycle_cost_per_kwh",
        "max_charge_power_kw",
        "max_discharge_power_kw",
        "min_action_profit_threshold",
    }
)

# All BatterySettings/HomeSettings fields the store may hold — used to
# filter the store's battery/home sections before passing them to
# update_settings(), so a non-model key living alongside them in the store
# is never passed to update() directly: battery has temperature_derating (a
# nested dict, applied via a separate mechanism at BSM construction), and
# home can carry a stale pre-migration key (e.g. 'consumption') if it and
# its renamed successor ('default_hourly') ever coexisted in a persisted
# store (see settings_store.py's rename-if-absent migration guard). Derived
# from each dataclass so a newly added field is included automatically —
# this is what BATTERY_REQUIRED_FIELDS (a hand-picked subset) previously
# failed to do for charging_power_rate/efficiency_charge/efficiency_discharge:
# they were silently dropped at startup while still working via PATCH,
# reverting to class defaults on every restart (the #197 bug class, live on
# main for these three fields). Kept in sync by
# TestBatteryModelAttrsConsistency/TestHomeModelAttrsConsistency;
# BATTERY_MODEL_ATTRS is also imported directly by the PATCH handler in api.py.
BATTERY_MODEL_ATTRS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(BatterySettings) if f.init
)
HOME_MODEL_ATTRS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(HomeSettings) if f.init
)

HOME_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "default_hourly",
        "currency",
        "max_fuse_current",
        "voltage",
        "safety_margin",
        "phase_count",
        "consumption_strategy",
        "power_monitoring_enabled",
    }
)

# Price settings reach BSM in snake_case unchanged — PriceSettings.update()
# (core/bess/settings.py) does not translate camelCase, so startup and PATCH
# both pass the same store field names straight through. This set only
# validates presence at startup; kept in sync with the PriceSettings
# dataclass by TestPriceModelAttrsConsistency (issue #197). spot_multiplier/
# export_spot_multiplier are wizard-configurable and store-backed like the
# other required fields (issue #221); use_actual_price is excluded — it is
# an internal-only field, never read from the store or written by the
# wizard, matching min_profit's exclusion.
PRICE_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "area",
        "markup_rate",
        "vat_multiplier",
        "additional_costs",
        "tax_reduction",
        "spot_multiplier",
        "export_spot_multiplier",
    }
)

# Legacy inverter_type values ("MIN"/"SPH") → canonical inverter.platform.
# Used only by settings_store migration for old configs.
LEGACY_INVERTER_PLATFORM_MAP: dict[str, str] = {
    "MIN": "growatt_server_min",
    "SPH": "growatt_server_sph",
}

# Keep old name as alias for backward compat with PATCH /api/settings handler
UI_TYPE_TO_PLATFORM = LEGACY_INVERTER_PLATFORM_MAP


def build_system_settings(options: dict) -> dict:
    """Validate settings options and return the snake_case dict for update_settings().

    This is the pure transformation layer between the settings store and the
    in-memory system — both snake_case (issue #197).  It is intentionally a
    standalone function so it can be unit-tested without instantiating
    BESSController.

    Args:
        options: Dict with at minimum ``battery``, ``electricity_price``, and
                 ``home`` sections using store snake_case field names.

    Returns:
        Dict with ``battery``, ``home``, and ``price`` sections, snake_case,
        ready to pass to ``system.update_settings()``.

    Raises:
        ValueError: If a required section or field is missing.
    """
    required_sections = ["battery", "electricity_price", "home"]
    for section in required_sections:
        if section not in options:
            raise ValueError(f"Required configuration section '{section}' is missing")

    battery_config = options["battery"]
    electricity_price_config = options["electricity_price"]
    home_config = options["home"]

    for key in BATTERY_REQUIRED_FIELDS:
        if key not in battery_config:
            raise ValueError(f"Required battery setting '{key}' is missing from config")
    for key in PRICE_REQUIRED_FIELDS:
        if key not in electricity_price_config:
            raise ValueError(
                f"Required electricity_price setting '{key}' is missing from config"
            )
    for key in HOME_REQUIRED_FIELDS:
        if key not in home_config:
            raise ValueError(f"Required home setting '{key}' is missing from config")

    return {
        # Filtered to known BatterySettings/HomeSettings fields — their store
        # sections can carry non-model keys (battery's temperature_derating;
        # a stale pre-migration key for home — see BATTERY_MODEL_ATTRS/
        # HOME_MODEL_ATTRS comment above) that would raise AttributeError if
        # passed to update() directly.
        "battery": {
            k: v for k, v in battery_config.items() if k in BATTERY_MODEL_ATTRS
        },
        "home": {k: v for k, v in home_config.items() if k in HOME_MODEL_ATTRS},
        # Price is passed through unchanged — no non-model keys share its
        # store section.
        "price": dict(electricity_price_config),
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
        return {
            camel_to_snake(k): convert_keys_to_snake_case(v) for k, v in data.items()
        }
    if isinstance(data, list):
        return [convert_keys_to_snake_case(item) for item in data]
    return data
