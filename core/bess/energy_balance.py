"""Energy-balance identities shared by the sensor and flow layers.

House load is not measured on every platform (SolaX native, Solis and Huawei
have no load register), so it has to be derived from the counters that every
platform does provide. That derivation was duplicated — once over lifetime
totals in ``ha_api_controller`` and once over period deltas in
``energy_flow_calculator`` — and the two copies drifted: the lifetime copy
omitted the battery terms entirely and reported load plus net battery charge
(issue #528). One definition, two callers, so they cannot drift again.
"""


def derive_load_consumption(
    *,
    solar_production: float,
    import_from_grid: float,
    export_to_grid: float,
    battery_charged: float,
    battery_discharged: float,
) -> float:
    """Derive house load consumption from the five core energy counters.

    Decomposing into the seven physical flows::

        solar       = solar_to_home + solar_to_battery + solar_to_grid
        import      = grid_to_home  + grid_to_battery
        export      = solar_to_grid + battery_to_grid
        charged     = solar_to_battery + grid_to_battery
        discharged  = battery_to_home + battery_to_grid

    gives ``load = solar_to_home + battery_to_home + grid_to_home``, which
    reduces to the balance below. Dropping the battery terms yields
    ``load + (charged - discharged)`` — the issue #528 defect.

    The result is returned unclamped: over a consistent set of counters it is
    physically non-negative, so a negative value means the inputs disagree and
    must stay visible rather than being laundered into a plausible zero (per
    ``docs/agents/rules.md`` — no silent fallbacks). Callers working with
    per-period deltas, where sensor noise can legitimately produce a small
    negative, clamp it themselves.

    Args:
        solar_production: Solar energy produced, kWh.
        import_from_grid: Energy imported from the grid, kWh.
        export_to_grid: Energy exported to the grid, kWh.
        battery_charged: Energy charged into the battery, kWh.
        battery_discharged: Energy discharged from the battery, kWh.

    Returns:
        House load consumption in kWh.
    """
    return (
        solar_production
        + import_from_grid
        + battery_discharged
        - battery_charged
        - export_to_grid
    )
