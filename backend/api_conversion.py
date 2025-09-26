"""Unified API conversion system - simple snake_case to camelCase conversion."""

import re
from dataclasses import asdict, is_dataclass
from typing import Any


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

