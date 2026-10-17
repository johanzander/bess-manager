"""Closed-loop tests for fuse protection while grid charging (#816).

The phase-current sensors are grid-side meters, so what they read while the
battery grid-charges is house load PLUS the battery's own draw. The monitor
must derive its headroom from the house-only load, otherwise it sees its own
charging as house load, drops to 0 %, then sees an empty phase and jumps back
to 100 % -- a 0/100 oscillation that let the grid draw reach ~20 kW on a 25 A
fuse.

These tests run the monitor against a controller that models the meter, so the
assertion is on the outcome (grid load per phase), not on the command written.
"""

from typing import Any, cast

import pytest  # type: ignore

from core.bess.power_monitor import HomePowerMonitor
from core.bess.settings import BatterySettings, HomeSettings

VOLTAGE = 230
FUSE_A = 25
LIMIT_W = VOLTAGE * FUSE_A  # 5750 W per phase


class GridMeterController:
    """Controller whose phase sensors read house load + the battery's grid draw."""

    def __init__(
        self,
        house_phase_w: list[float],
        hardware_max_w: float,
        grid_charge_state: bool = True,
    ) -> None:
        self.house_phase_w = house_phase_w
        self.hardware_max_w = hardware_max_w
        self.rate = 0
        self.grid_charge_state = grid_charge_state

    def battery_draw_w(self) -> float:
        return self.rate / 100 * self.hardware_max_w

    def _phase_current(self, i: int) -> float:
        return (self.house_phase_w[i] + self.battery_draw_w() / 3) / VOLTAGE

    def get_l1_current(self) -> float:
        return self._phase_current(0)

    def get_l2_current(self) -> float:
        return self._phase_current(1)

    def get_l3_current(self) -> float:
        return self._phase_current(2)

    def get_battery_charge_power(self) -> float | None:
        return self.battery_draw_w()

    def grid_charge_enabled(self) -> bool:
        return self.grid_charge_state

    def get_charging_power_rate(self) -> int:
        return self.rate

    def set_charging_power_rate(self, rate: int) -> None:
        self.rate = rate

    def worst_phase_w(self) -> float:
        return max(self.house_phase_w[i] + self.battery_draw_w() / 3 for i in range(3))


def _monitor(
    controller: GridMeterController, max_charge_kw: float = 12.0
) -> HomePowerMonitor:
    home = HomeSettings(
        max_fuse_current=FUSE_A,
        voltage=VOLTAGE,
        safety_margin=1.0,
        phase_count=3,
        power_monitoring_enabled=True,
    )
    battery = BatterySettings(
        max_charge_power_kw=max_charge_kw, charging_power_rate=100
    )
    monitor = HomePowerMonitor(cast(Any, controller), home, battery)
    monitor.update_target_charging_power(100)
    return monitor


def test_rate_converges_and_stays_inside_fuse_limit() -> None:
    """House 5.6 kW unbalanced + 12 kW battery: no 0/100 alternation, no overload."""
    controller = GridMeterController([2800, 1400, 1400], hardware_max_w=12000)
    monitor = _monitor(controller)

    rates = []
    for _ in range(8):
        monitor.adjust_battery_charging(grid_charging=True)
        rates.append(controller.rate)
        assert controller.worst_phase_w() <= LIMIT_W + 1

    # Settles after the first adjustment: a limit, not an on/off switch.
    assert len(set(rates[1:])) == 1, f"rate keeps changing: {rates}"
    assert 0 < rates[-1] < 100, f"rate should be throttled, got {rates}"


def test_period_boundary_is_fuse_checked_when_grid_charge_state_reads_stale_off() -> (
    None
):
    """The plan says GRID_CHARGING; the HA switch still reads off (7 s apply lag).

    The decision must come from the plan, so the 100 % target is throttled
    instead of being applied unchecked at the boundary.
    """
    controller = GridMeterController(
        [2800, 1400, 1400], hardware_max_w=12000, grid_charge_state=False
    )
    monitor = _monitor(controller)

    monitor.adjust_battery_charging(grid_charging=True)
    # Next tick: the battery now draws, which the monitor must see through.
    monitor.adjust_battery_charging(grid_charging=True)

    assert controller.worst_phase_w() <= LIMIT_W + 1


def test_solar_only_period_is_not_throttled() -> None:
    """No grid charging planned -> no fuse risk -> full target, as before."""
    controller = GridMeterController([2800, 1400, 1400], hardware_max_w=12000)
    monitor = _monitor(controller)

    monitor.adjust_battery_charging(grid_charging=False)

    assert controller.rate == 100


def test_house_only_load_excludes_battery_draw() -> None:
    controller = GridMeterController([2800, 1400, 1400], hardware_max_w=12000)
    controller.rate = 100  # battery pulls 4000 W per phase
    monitor = _monitor(controller)

    assert monitor.get_house_phase_loads_w() == pytest.approx((2800, 1400, 1400))


def test_house_only_load_clamps_at_zero_when_solar_feeds_battery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Battery charging from PV does not show on the meter -> never negative."""
    controller = GridMeterController([0, 0, 0], hardware_max_w=12000)
    controller.rate = 100
    # Meter reads only 1000 W/phase even though the battery draws 12 kW:
    monkeypatch.setattr(controller, "get_l1_current", lambda: 1000 / VOLTAGE)
    monkeypatch.setattr(controller, "get_l2_current", lambda: 1000 / VOLTAGE)
    monkeypatch.setattr(controller, "get_l3_current", lambda: 1000 / VOLTAGE)
    monitor = _monitor(controller)

    assert monitor.get_house_phase_loads_w() == (0.0, 0.0, 0.0)


def test_missing_battery_charge_sensor_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent fallback: an unreadable battery draw cannot be subtracted."""
    controller = GridMeterController([1000, 1000, 1000], hardware_max_w=12000)
    monkeypatch.setattr(controller, "get_battery_charge_power", lambda: None)
    monitor = _monitor(controller)

    with pytest.raises(ValueError, match="battery_charge_power"):
        monitor.get_house_phase_loads_w()
