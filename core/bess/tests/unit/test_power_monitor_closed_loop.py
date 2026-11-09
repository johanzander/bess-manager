"""Closed-loop tests for fuse protection while grid charging (#816, #877).

The phase-current sensors are grid-side meters, so what they read while the
battery grid-charges is house load PLUS the battery's own draw. The monitor
must account for that, otherwise it sees its own charging as house load, drops
to 0 %, then sees an empty phase and jumps back to 100 % -- a 0/100 oscillation
that let the grid draw reach ~20 kW on a 25 A fuse. Battery power sensors can
be minutes old, so they cannot be what corrects for it.

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


class LaggedSensorController(GridMeterController):
    """Growatt-cloud shape: live phase meters, battery power sampled every 5 min.

    The AC draw at 100 % can differ from the configured max_charge_power_kw and
    the battery can be limited below the commanded rate (BMS taper).
    """

    def __init__(
        self,
        house_phase_w: list[float],
        hardware_max_w: float,
        initial_rate: int,
        sensor_w: float,
    ) -> None:
        super().__init__(house_phase_w, hardware_max_w)
        self.rate = initial_rate
        self.sensor_w = sensor_w
        self.draw_cap_w: float | None = None

    def battery_draw_w(self) -> float:
        commanded = self.rate / 100 * self.hardware_max_w
        return commanded if self.draw_cap_w is None else min(commanded, self.draw_cap_w)

    def get_battery_charge_power(self) -> float | None:
        return self.sensor_w

    def sample_sensor(self) -> None:
        self.sensor_w = self.battery_draw_w()


def _run_minutes(
    controller: LaggedSensorController, monitor: HomePowerMonitor, minutes: int
) -> tuple[list[int], list[float]]:
    rates, worst = [], []
    for minute in range(minutes):
        if minute % 5 == 0:
            controller.sample_sensor()
        monitor.adjust_battery_charging(grid_charging=True)
        rates.append(controller.rate)
        worst.append(controller.worst_phase_w())
    return rates, worst


REAL_DRAW_W = 15100
HEAVY_HOUSE_W = [3200.0, 1600.0, 2400.0]
SETTLED_TOLERANCE_W = LIMIT_W * 1.01


@pytest.mark.parametrize("configured_kw", [12.0, 15.0, 20.0])
def test_throttle_settles_under_fuse_limit_despite_stale_battery_sensor(
    configured_kw: float,
) -> None:
    """Holds for a correct, too-low and too-high configured charge power."""
    controller = LaggedSensorController(
        HEAVY_HOUSE_W, REAL_DRAW_W, initial_rate=100, sensor_w=0
    )
    monitor = _monitor(controller, max_charge_kw=configured_kw)

    rates, worst = _run_minutes(controller, monitor, 25)

    assert max(worst[6:]) <= SETTLED_TOLERANCE_W, f"over the fuse: {worst}"
    assert max(rates[6:]) - min(rates[6:]) <= 2, f"rate alternates: {rates}"


def test_rate_cut_is_not_reversed_by_the_current_drop_it_caused() -> None:
    """Replay of the live 22:19 tick (#877): 12280 W sensor from before a 39 % cut.

    Phases had just fallen to 21.8/14.1/18.3 A because of that cut. The old
    monitor read the drop as an empty house and wrote 100 %, putting L1 at 35 A.
    """
    meter_a = [21.8, 14.1, 18.3]
    rate = 39
    house = [a * VOLTAGE - rate / 100 * REAL_DRAW_W / 3 for a in meter_a]
    controller = LaggedSensorController(
        house, REAL_DRAW_W, initial_rate=rate, sensor_w=12280
    )
    monitor = _monitor(controller, max_charge_kw=12.0)

    monitor.adjust_battery_charging(grid_charging=True)

    assert controller.worst_phase_w() <= LIMIT_W * 1.05


def test_charge_start_with_sensor_still_near_zero_does_not_cut_to_zero() -> None:
    """Live 21:50 shape: charging at full draw while the sensor still reads 105 W."""
    controller = LaggedSensorController(
        [1200.0, 900.0, 1900.0], REAL_DRAW_W, initial_rate=100, sensor_w=105
    )
    monitor = _monitor(controller, max_charge_kw=15.0)

    rates = []
    for _ in range(4):
        monitor.adjust_battery_charging(grid_charging=True)
        rates.append(controller.rate)

    assert min(rates) > 0, f"charging was cut off: {rates}"
    assert max(rates) - min(rates) <= 2, f"rate alternates: {rates}"


def test_tapering_battery_recovers_inside_limit_when_the_cap_lifts() -> None:
    """A commanded rate above actual draw may overshoot for one tick, not more."""
    controller = LaggedSensorController(
        HEAVY_HOUSE_W, REAL_DRAW_W, initial_rate=100, sensor_w=0
    )
    controller.draw_cap_w = 6000
    monitor = _monitor(controller, max_charge_kw=15.0)

    _, tapered = _run_minutes(controller, monitor, 6)
    controller.draw_cap_w = None
    _, released = _run_minutes(controller, monitor, 6)

    assert max(tapered) <= LIMIT_W
    assert max(released[1:]) <= SETTLED_TOLERANCE_W, f"over the fuse: {released}"


def test_fuse_protection_does_not_depend_on_the_battery_power_sensor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LaggedSensorController(
        HEAVY_HOUSE_W, REAL_DRAW_W, initial_rate=100, sensor_w=0
    )
    monkeypatch.setattr(controller, "get_battery_charge_power", lambda: None)
    monitor = _monitor(controller, max_charge_kw=15.0)

    monitor.adjust_battery_charging(grid_charging=True)

    assert controller.worst_phase_w() <= SETTLED_TOLERANCE_W
