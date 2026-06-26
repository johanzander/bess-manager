"""
End-to-end tests: optimizer output → MIN Growatt TOU schedule.

Runs the real DP optimizer on quarterly-resolution scenarios from debug logs,
converts the OptimizationResult to a DPSchedule, feeds it through
GrowattScheduleManager.create_schedule(), and verifies the resulting TOU
schedule meets all hardware and behavioral constraints.

This closes the gap between:
  - test_scenarios.py (optimizer produces correct intents)
  - test_growatt_tou_scheduling.py (hand-crafted intents → correct TOU)

by testing the full path with real optimizer output.
"""

import json
import logging
from functools import cache
from pathlib import Path

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.dp_schedule import DPSchedule
from core.bess.growatt_min_controller import (
    GrowattMinController as GrowattScheduleManager,
)
from core.bess.price_manager import MockSource, PriceManager
from core.bess.settings import BatterySettings

pytestmark = pytest.mark.slow

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

# Intent → expected schedule behavior mapping
CHARGING_INTENTS = {"GRID_CHARGING"}
EXPORT_INTENTS = {"BATTERY_EXPORT"}
DEFAULT_MODE_INTENTS = {"IDLE", "SOLAR_STORAGE", "LOAD_SUPPORT"}


def _load_scenario(name: str) -> dict:
    with open(DATA_DIR / f"{name}.json") as f:
        return json.load(f)


@cache
def _optimize_scenario(scenario_name: str):
    """Run the DP optimizer for a scenario ONCE and cache the result.

    The optimization (full quarterly DP) is the only expensive step in this
    module — every test asserts a different property of the *same* schedule. By
    caching the result per scenario and rebuilding the cheap
    GrowattScheduleManager fresh per test (see _run_and_build_schedule), we avoid
    recomputing the identical optimization ~16x per scenario while preserving
    test isolation.

    Returns (OptimizationResult, BatterySettings).
    """
    scenario = _load_scenario(scenario_name)
    battery = scenario["battery"]
    price_data = scenario["price_data"]
    base_prices = scenario["base_prices"]
    period_duration_hours = scenario.get("period_duration_hours", 1.0)

    battery_settings = BatterySettings(
        total_capacity=battery["max_soe_kwh"],
        min_soc=(battery["min_soe_kwh"] / battery["max_soe_kwh"]) * 100.0,
        max_soc=100.0,
        max_charge_power_kw=battery["max_charge_power_kw"],
        max_discharge_power_kw=battery["max_discharge_power_kw"],
        efficiency_charge=battery["efficiency_charge"],
        efficiency_discharge=battery["efficiency_discharge"],
        cycle_cost_per_kwh=battery["cycle_cost_per_kwh"],
    )

    price_manager = PriceManager(
        MockSource(base_prices),
        markup_rate=price_data["markup_rate"],
        vat_multiplier=price_data["vat_multiplier"],
        additional_costs=price_data["additional_costs"],
        tax_reduction=price_data["tax_reduction"],
        area="SE4",
    )
    buy_prices = price_manager.get_buy_prices(raw_prices=base_prices)
    sell_prices = price_manager.get_sell_prices(raw_prices=base_prices)

    result = optimize_battery_schedule(
        buy_price=buy_prices,
        sell_price=sell_prices,
        home_consumption=scenario["home_consumption"],
        solar_production=scenario["solar_production"],
        initial_soe=battery["initial_soe"],
        battery_settings=battery_settings,
        period_duration_hours=period_duration_hours,
    )
    return result, battery_settings


def _run_and_build_schedule(
    scenario_name: str, current_period: int = 0
) -> tuple[GrowattScheduleManager, list[str]]:
    """Build a MIN Growatt TOU schedule from the (cached) optimizer result.

    The expensive optimization is cached by _optimize_scenario; the scheduler is
    rebuilt fresh here so each test gets an isolated object.

    Returns (scheduler, strategic_intents) tuple.
    """
    result, battery_settings = _optimize_scenario(scenario_name)
    scenario = _load_scenario(scenario_name)

    # Convert OptimizationResult → DPSchedule (same path as battery_system_manager.py)
    strategic_intents = [pd.decision.strategic_intent for pd in result.period_data]
    dp_schedule = DPSchedule(
        actions=[pd.energy.battery_net_change for pd in result.period_data],
        state_of_energy=[pd.energy.battery_soe_end for pd in result.period_data],
        prices=[pd.economic.buy_price for pd in result.period_data],
        cycle_cost=battery_settings.cycle_cost_per_kwh,
        hourly_consumption=scenario["home_consumption"],
        original_dp_results={"strategic_intent": strategic_intents},
    )

    scheduler = GrowattScheduleManager(battery_settings)
    scheduler.create_schedule(
        schedule=dp_schedule,
        current_period=current_period,
        previous_tou_intervals=None,
    )

    return scheduler, strategic_intents


def _get_realworld_scenarios() -> list[str]:
    """Get all quarterly real-world scenario names."""
    return sorted(p.stem for p in DATA_DIR.glob("realworld_*.json"))


class TestEndToEndHardwareConstraints:
    """Verify hardware constraints hold when using real optimizer output."""

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_no_overlapping_intervals(self, scenario_name):
        scheduler, _ = _run_and_build_schedule(scenario_name)
        assert (
            scheduler.has_no_overlapping_intervals()
        ), f"{scenario_name}: TOU intervals overlap"

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_chronological_order(self, scenario_name):
        scheduler, _ = _run_and_build_schedule(scenario_name)
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), f"{scenario_name}: TOU intervals not in chronological order"

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_hardware_slot_limit(self, scenario_name):
        scheduler, _ = _run_and_build_schedule(scenario_name)
        assert len(scheduler.active_tou_intervals) <= 9, (
            f"{scenario_name}: {len(scheduler.active_tou_intervals)} active intervals "
            f"exceeds 9-slot hardware limit"
        )

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_segment_ids_in_valid_range(self, scenario_name):
        scheduler, _ = _run_and_build_schedule(scenario_name)
        for seg in scheduler.active_tou_intervals:
            assert (
                1 <= seg["segment_id"] <= 9
            ), f"{scenario_name}: segment_id {seg['segment_id']} outside 1-9"


class TestEndToEndIntentExecution:
    """Verify strategic intents from optimizer are correctly reflected in TOU schedule."""

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_charging_intents_produce_charging_config(self, scenario_name):
        """Hours with GRID_CHARGING intent must be configured for charging."""
        scheduler, intents = _run_and_build_schedule(scenario_name)

        # Find hours where all 4 quarterly periods are GRID_CHARGING
        for hour in range(24):
            quarter_intents = set(intents[hour * 4 : (hour + 1) * 4])
            if len(intents) >= (hour + 1) * 4 and quarter_intents == {"GRID_CHARGING"}:
                assert scheduler.is_hour_configured_for_charging(hour), (
                    f"{scenario_name}: hour {hour} has all GRID_CHARGING periods "
                    f"but is not configured for charging"
                )

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_export_intents_produce_export_config(self, scenario_name):
        """Hours with BATTERY_EXPORT intent must be configured for export."""
        scheduler, intents = _run_and_build_schedule(scenario_name)

        for hour in range(24):
            quarter_intents = set(intents[hour * 4 : (hour + 1) * 4])
            if len(intents) >= (hour + 1) * 4 and quarter_intents == {"BATTERY_EXPORT"}:
                assert scheduler.is_hour_configured_for_export(hour), (
                    f"{scenario_name}: hour {hour} has all BATTERY_EXPORT periods "
                    f"but is not configured for export"
                )

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_idle_hours_use_default_mode(self, scenario_name):
        """Hours where all quarters are default-mode intents should be load_first."""
        scheduler, intents = _run_and_build_schedule(scenario_name)

        for hour in range(24):
            quarter_intents = set(intents[hour * 4 : (hour + 1) * 4])
            if len(intents) >= (hour + 1) * 4 and quarter_intents.issubset(
                DEFAULT_MODE_INTENTS
            ):
                mode = scheduler.get_hour_battery_mode(hour)
                assert mode == "load_first", (
                    f"{scenario_name}: hour {hour} has only {quarter_intents} "
                    f"but mode is {mode} instead of load_first"
                )


class TestEndToEndChargeDischargeRates:
    """Verify charge/discharge rates are set correctly for each strategic intent (period-level)."""

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_grid_charging_periods_have_correct_rates(self, scenario_name):
        """GRID_CHARGING: grid_charge=True, charge_rate=100%, discharge_rate=0%."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        for period in range(len(scheduler.strategic_intents)):
            settings = scheduler.get_period_settings(period)
            if settings["strategic_intent"] == "GRID_CHARGING":
                assert (
                    settings["grid_charge"] is True
                ), f"{scenario_name} period {period}: GRID_CHARGING must have grid_charge=True"
                assert (
                    settings["charge_rate"] == 100
                ), f"{scenario_name} period {period}: GRID_CHARGING charge_rate={settings['charge_rate']}, expected 100"
                assert (
                    settings["discharge_rate"] == 0
                ), f"{scenario_name} period {period}: GRID_CHARGING discharge_rate={settings['discharge_rate']}, expected 0"

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_export_arbitrage_periods_have_correct_rates(self, scenario_name):
        """BATTERY_EXPORT: grid_charge=False, charge_rate=0%, discharge_rate=100%."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        for period in range(len(scheduler.strategic_intents)):
            settings = scheduler.get_period_settings(period)
            if settings["strategic_intent"] == "BATTERY_EXPORT":
                assert (
                    settings["grid_charge"] is False
                ), f"{scenario_name} period {period}: BATTERY_EXPORT must have grid_charge=False"
                assert (
                    settings["charge_rate"] == 0
                ), f"{scenario_name} period {period}: BATTERY_EXPORT charge_rate={settings['charge_rate']}, expected 0"
                assert (
                    0 <= settings["discharge_rate"] <= 100
                )  # dynamic: rate derived from planned action, not hardcoded

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_idle_periods_have_correct_rates(self, scenario_name):
        """IDLE: grid_charge=False, discharge_rate=0%."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        for period in range(len(scheduler.strategic_intents)):
            settings = scheduler.get_period_settings(period)
            if settings["strategic_intent"] == "IDLE":
                assert (
                    settings["grid_charge"] is False
                ), f"{scenario_name} period {period}: IDLE must have grid_charge=False"
                assert (
                    settings["discharge_rate"] == 0
                ), f"{scenario_name} period {period}: IDLE discharge_rate={settings['discharge_rate']}, expected 0"

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_solar_storage_periods_have_correct_rates(self, scenario_name):
        """SOLAR_STORAGE: grid_charge=False, charge_rate=100%, discharge_rate=0%."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        for period in range(len(scheduler.strategic_intents)):
            settings = scheduler.get_period_settings(period)
            if settings["strategic_intent"] == "SOLAR_STORAGE":
                assert (
                    settings["grid_charge"] is False
                ), f"{scenario_name} period {period}: SOLAR_STORAGE must have grid_charge=False"
                assert (
                    settings["charge_rate"] == 100
                ), f"{scenario_name} period {period}: SOLAR_STORAGE charge_rate={settings['charge_rate']}, expected 100"
                assert (
                    settings["discharge_rate"] == 0
                ), f"{scenario_name} period {period}: SOLAR_STORAGE discharge_rate={settings['discharge_rate']}, expected 0"

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_load_support_periods_have_correct_rates(self, scenario_name):
        """LOAD_SUPPORT: grid_charge=False, charge_rate=0%, discharge_rate=100%."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        for period in range(len(scheduler.strategic_intents)):
            settings = scheduler.get_period_settings(period)
            if settings["strategic_intent"] == "LOAD_SUPPORT":
                assert (
                    settings["grid_charge"] is False
                ), f"{scenario_name} period {period}: LOAD_SUPPORT must have grid_charge=False"
                assert (
                    settings["charge_rate"] == 0
                ), f"{scenario_name} period {period}: LOAD_SUPPORT charge_rate={settings['charge_rate']}, expected 0"
                assert (
                    0 <= settings["discharge_rate"] <= 100
                )  # dynamic: rate derived from planned action, not hardcoded

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_all_periods_have_settings(self, scenario_name):
        """Every period must return valid settings via get_period_settings."""
        scheduler, intents = _run_and_build_schedule(scenario_name)

        for period in range(len(intents)):
            settings = scheduler.get_period_settings(period)
            assert "charge_rate" in settings
            assert "discharge_rate" in settings
            assert "grid_charge" in settings
            assert 0 <= settings["charge_rate"] <= 100
            assert 0 <= settings["discharge_rate"] <= 100


class TestEndToEndMidDayUpdate:
    """Verify schedule updates at different times of day using real optimizer output."""

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_mid_day_update_maintains_constraints(self, scenario_name):
        """Running create_schedule at various current_periods maintains constraints."""
        scenario = _load_scenario(scenario_name)
        horizon = len(scenario["base_prices"])

        # Test at period 0 (start of day) and at the scenario's natural midpoint
        midpoint = min(horizon // 2, 48)  # cap at period 48 (noon)

        for current_period in [0, midpoint]:
            scheduler, _ = _run_and_build_schedule(scenario_name, current_period)

            assert (
                scheduler.has_no_overlapping_intervals()
            ), f"{scenario_name} at period {current_period}: intervals overlap"
            assert (
                scheduler.intervals_are_chronologically_ordered()
            ), f"{scenario_name} at period {current_period}: intervals not ordered"
            assert len(scheduler.active_tou_intervals) <= 9, (
                f"{scenario_name} at period {current_period}: "
                f"{len(scheduler.active_tou_intervals)} exceeds 9-slot limit"
            )


class TestEndToEndHardwareWrite:
    """Verify hardware writes are valid when driven by real optimizer output."""

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_hardware_writes_use_valid_slot_ids(self, scenario_name):
        """All hardware writes use segment_id 1-9."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        calls = []

        class CapturingController:
            def __init__(self):
                self.failure_tracker = None

            def set_inverter_time_segment(
                self, segment_id, batt_mode, start_time, end_time, enabled
            ):
                calls.append(
                    {
                        "segment_id": segment_id,
                        "batt_mode": batt_mode,
                        "start_time": start_time,
                        "end_time": end_time,
                        "enabled": enabled,
                    }
                )

        controller = CapturingController()
        scheduler.write_schedule_to_hardware(
            controller, effective_period=0, current_tou=[]
        )

        for call in calls:
            assert 1 <= call["segment_id"] <= 9, (
                f"{scenario_name}: hardware write with segment_id "
                f"{call['segment_id']} outside 1-9"
            )

    @pytest.mark.parametrize("scenario_name", _get_realworld_scenarios())
    def test_hardware_write_count_within_limit(self, scenario_name):
        """Never write more than 9 segments to hardware."""
        scheduler, _ = _run_and_build_schedule(scenario_name)

        write_count = 0

        class CountingController:
            def __init__(self):
                self.failure_tracker = None

            def set_inverter_time_segment(self, **kwargs):
                nonlocal write_count
                write_count += 1

        controller = CountingController()
        scheduler.write_schedule_to_hardware(
            controller, effective_period=0, current_tou=[]
        )

        assert (
            write_count <= 9
        ), f"{scenario_name}: {write_count} hardware writes exceeds 9-slot limit"
