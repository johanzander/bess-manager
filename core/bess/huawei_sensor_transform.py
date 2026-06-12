"""Huawei Solar read-only sensor normalization helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic

logger = logging.getLogger(__name__)

UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}
DEFAULT_LOAD_TOLERANCE_W = 100.0
_WARNING_INTERVAL_SECONDS = 300.0
_last_negative_load_warning = 0.0


@dataclass(frozen=True)
class HuaweiPowerSnapshot:
    """Raw Huawei power values normalized to watts."""

    battery_power_w: float | None = None
    grid_power_w: float | None = None
    pv_power_w: float | None = None
    direct_house_load_power_w: float | None = None


@dataclass(frozen=True)
class HuaweiNormalizedPower:
    """BESS internal non-negative power channels in watts."""

    battery_charge_power: float | None = None
    battery_discharge_power: float | None = None
    import_power: float | None = None
    export_power: float | None = None
    local_load_power: float | None = None
    diagnostic_warning: str | None = None


def parse_ha_numeric_power(value, unit: str | None = None) -> float | None:
    """Parse a Home Assistant numeric state and return watts.

    Returns None for unavailable, missing, or malformed values. Values with a
    Home Assistant unit of kW are converted to W; W values are preserved.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in UNAVAILABLE_STATES:
            return None
        value = stripped
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    normalized_unit = (unit or "").strip().lower()
    if normalized_unit == "kw":
        return numeric * 1000.0
    return numeric


def normalize_huawei_power(
    snapshot: HuaweiPowerSnapshot,
    *,
    load_tolerance_w: float = DEFAULT_LOAD_TOLERANCE_W,
    warn: bool = True,
) -> HuaweiNormalizedPower:
    """Normalize Huawei signed channels to BESS internal power channels.

    Huawei conventions:
    - battery power: positive = charging, negative = discharging
    - grid power: negative = import, positive = export
    - calculated load: pv - grid - battery
    - optional direct house load: positive instantaneous consumption
    """
    battery_charge = battery_discharge = None
    if snapshot.battery_power_w is not None:
        battery_charge = max(snapshot.battery_power_w, 0.0)
        battery_discharge = max(-snapshot.battery_power_w, 0.0)

    import_power = export_power = None
    if snapshot.grid_power_w is not None:
        import_power = max(-snapshot.grid_power_w, 0.0)
        export_power = max(snapshot.grid_power_w, 0.0)

    local_load = None
    diagnostic = None
    if snapshot.direct_house_load_power_w is not None:
        local_load = abs(snapshot.direct_house_load_power_w)
    elif (
        snapshot.pv_power_w is not None
        and snapshot.grid_power_w is not None
        and snapshot.battery_power_w is not None
    ):
        calculated = (
            snapshot.pv_power_w - snapshot.grid_power_w - snapshot.battery_power_w
        )
        if calculated < -abs(load_tolerance_w):
            diagnostic = (
                "Huawei calculated house load is significantly negative "
                f"({calculated:.0f} W). Check sensor timing and sign conventions."
            )
            if warn:
                _rate_limited_warning(diagnostic)
        local_load = 0.0 if calculated < 0 else calculated

    return HuaweiNormalizedPower(
        battery_charge_power=battery_charge,
        battery_discharge_power=battery_discharge,
        import_power=import_power,
        export_power=export_power,
        local_load_power=local_load,
        diagnostic_warning=diagnostic,
    )


def _rate_limited_warning(message: str) -> None:
    global _last_negative_load_warning
    now = monotonic()
    if now - _last_negative_load_warning >= _WARNING_INTERVAL_SECONDS:
        logger.warning(message)
        _last_negative_load_warning = now
