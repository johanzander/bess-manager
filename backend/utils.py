"""Utility functions for the BESS Manager backend."""


def snake_to_camel(snake_str):
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def add_camel_case_keys(data):
    """
    Add camelCase versions of all snake_case keys in a dict or list of dicts.
    Does not modify the original data structure.
    """
    if data is None:
        return None

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Keep the original key-value pair
            result[key] = add_camel_case_keys(value)

            # If this is a snake_case key, add a camelCase version
            if "_" in key:
                camel_key = snake_to_camel(key)
                result[camel_key] = add_camel_case_keys(value)
        return result

    elif isinstance(data, list):
        return [add_camel_case_keys(item) for item in data]

    else:
        return data
