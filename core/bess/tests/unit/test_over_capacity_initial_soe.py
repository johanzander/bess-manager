"""An over-capacity initial_soe must clamp, not brick the optimizer.

Field regression (Growatt MOD): the inverter charged to 93% while the
configured maxSoc was 90%, so initial_soe (14.0 kWh) exceeded max_soe
(13.5 kWh). optimize_battery_schedule raised ValueError every cycle; the
caller swallowed it, so no schedule was produced. The battery then sat idle
through a peak-price evening and — unable to discharge — stayed over-max,
self-locking the failure for the whole day (69 consecutive failed cycles).

A start state slightly above max is as real as one below min (a live SOC
sensor/register offset, or a maxSoc lowered below the current charge). The
symmetric below-min case already warns and proceeds; over-max must do the
same — clamp to max and let the optimizer discharge back into range.
"""

import logging

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.models import OptimizationResult
from core.bess.settings import BatterySettings
from core.bess.tests.helpers import make_battery_settings


def _run(initial_soe: float, settings: BatterySettings) -> OptimizationResult:
    horizon = 8
    return optimize_battery_schedule(
        buy_price=[2.0] * horizon,
        sell_price=[1.0] * horizon,
        home_consumption=[0.5] * horizon,
        solar_production=[0.0] * horizon,
        initial_soe=initial_soe,
        battery_settings=settings,
        period_duration_hours=0.25,
    )


def test_initial_soe_above_max_is_clamped_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_battery_settings()
    over = settings.max_soe_kwh + 0.5  # e.g. inverter charged past the ceiling

    with caplog.at_level(logging.WARNING):
        result = _run(over, settings)

    # It must produce a schedule, not raise/brick.
    assert result is not None
    assert result.period_data
    # And it must surface the anomaly (explicit-failure discipline: warn, don't
    # hide) rather than silently clamping.
    assert "above" in caplog.text.lower() and "max" in caplog.text.lower()


def test_initial_soe_below_min_still_proceeds() -> None:
    # Regression: the symmetric below-min case already proceeds; keep it working.
    settings = make_battery_settings()
    under = max(0.0, settings.min_soe_kwh - 0.5)
    result = _run(under, settings)
    assert result is not None
    assert result.period_data
