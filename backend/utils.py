"""Utility functions for API compatibility."""

import re


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    # Insert underscore before uppercase letters and convert to lowercase
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def to_camel_case(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split('_')
    return components[0] + ''.join(word.capitalize() for word in components[1:])


def convert_keys_to_snake(data):
    """Convert all camelCase keys to snake_case recursively."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            snake_key = camel_to_snake(key)
            result[snake_key] = convert_keys_to_snake(value)
        return result
    elif isinstance(data, list):
        return [convert_keys_to_snake(item) for item in data]
    else:
        return data


def add_camel_case_keys(data):
    """Add camelCase versions of all snake_case keys for API compatibility."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Add original key
            result[key] = add_camel_case_keys(value)
            
            # Add camelCase version if key contains underscores
            if '_' in key:
                camel_key = to_camel_case(key)
                if camel_key != key:  # Avoid duplicates
                    result[camel_key] = add_camel_case_keys(value)
        
        return result
    elif isinstance(data, list):
        return [add_camel_case_keys(item) for item in data]
    else:
        return data