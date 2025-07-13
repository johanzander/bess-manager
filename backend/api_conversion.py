"""Unified API conversion system - simple snake_case to camelCase conversion."""

import re
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.bess.models import HourlyData

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

def dataclass_to_api_dict(obj: Any, battery_capacity: float = 30.0) -> dict[str, Any]:
    """Convert any dataclass to API-ready camelCase dict."""
    if not is_dataclass(obj) or isinstance(obj, type):
        msg = f"Object must be a dataclass instance, got {type(obj)}"
        raise ValueError(msg)

    # Convert to dict
    data_dict = asdict(obj)

    # Special handling for battery SOE → SOC conversion
    if "battery_soe_start" in data_dict and "battery_soe_end" in data_dict:
        # Add calculated SOC fields (%) from SOE fields (kWh)
        data_dict["battery_soc_start"] = (
            data_dict["battery_soe_start"] / battery_capacity
        ) * 100.0
        data_dict["battery_soc_end"] = (
            data_dict["battery_soe_end"] / battery_capacity
        ) * 100.0

    # Convert all keys to camelCase
    return convert_keys_to_camel_case(data_dict)

def hourly_data_to_api_dict(
    hourly: "HourlyData", battery_capacity: float = 30.0
) -> dict[str, Any]:
    """Convert HourlyData to flat API dict - SINGLE CONVERSION FUNCTION."""
    # Convert each component dataclass
    energy_dict = dataclass_to_api_dict(hourly.energy, battery_capacity)
    economic_dict = (
        dataclass_to_api_dict(hourly.economic, battery_capacity)
        if hourly.economic
        else {}
    )
    decision_dict = (
        dataclass_to_api_dict(hourly.decision, battery_capacity)
        if hourly.decision
        else {}
    )

    # Merge all fields into single flat dict
    result = {
        "hour": hourly.hour,
        "dataSource": hourly.data_source,
        "timestamp": hourly.timestamp.isoformat() if hourly.timestamp else None,
        **energy_dict,    # All energy fields automatically converted
        **economic_dict,  # All economic fields automatically converted
        **decision_dict,  # All decision fields automatically converted
    }

    return result

class APIConverter:
    """Main API conversion class - replaces all manual conversion methods."""

    def __init__(self, battery_capacity: float = 30.0) -> None:
        """Initialize with battery capacity for SOE→SOC conversion."""
        self.battery_capacity = battery_capacity

    def convert_hourly_data(self, hourly: "HourlyData") -> dict[str, Any]:
        """Convert HourlyData to API dict."""
        return hourly_data_to_api_dict(hourly, self.battery_capacity)

    def convert_hourly_data_list(
        self, hourly_list: list["HourlyData"]
    ) -> list[dict[str, Any]]:
        """Convert list of HourlyData to API dicts."""
        return [self.convert_hourly_data(hourly) for hourly in hourly_list]

    def convert_settings(self, settings_obj: Any) -> dict[str, Any]:
        """Convert any settings dataclass to API dict."""
        return dataclass_to_api_dict(settings_obj, self.battery_capacity)

    def convert_any_dataclass(self, obj: Any) -> dict[str, Any]:
        """Convert any dataclass to API dict."""
        return dataclass_to_api_dict(obj, self.battery_capacity)
