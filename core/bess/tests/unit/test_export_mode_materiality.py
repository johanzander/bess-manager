"""Behavioral tests for the grid_first export-materiality gate (issue #352).

A period classified BATTERY_EXPORT commits the inverter to grid_first, whose
discharge rate is a forced power command with no load-following. When the
planned export is small relative to the period's home load, that commitment
trades pennies of export revenue for import exposure on any intra-period load
spike. These tests pin the decoupling: classification (reporting/accounting)
stays BATTERY_EXPORT, but hardware only gets grid_first when the planned
export is material — above the 0.1 kWh flow-resolution floor AND either
export-dominant (larger than planned battery_to_home) or larger than the
load-following headroom the grid_first commitment forfeits (a near-full-rate
export has no headroom left to protect, however large the home share).

Demotion only applies on platforms where discharge_rate is a load-following
ceiling (discharge_rate_is_load_following) — on VPP-style direct power
control, writing rate 100 would force a full-power discharge (#324).
"""

import pytest  # type: ignore

from core.bess.dp_schedule import DPSchedule
from core.bess.growatt_min_controller import GrowattMinController
from core.bess.models import EnergyData, PeriodData
from core.bess.settings import BatterySettings

NUM_PERIODS = 96


@pytest.fixture
def battery_settings():
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def controller(battery_settings):
    return GrowattMinController(battery_settings)


def make_export_energy(battery_to_home_kwh: float, export_kwh: float) -> EnergyData:
    """Planned EnergyData for a discharge period serving home plus grid export.

    Constructed via the aggregates so it passes through the same
    _calculate_detailed_flows as real DP-planned data (including the #350/#351
    sub-0.1 kWh fold) — the returned flows are what the controller would see.
    """
    discharged = battery_to_home_kwh + export_kwh
    return EnergyData(
        solar_production=0.0,
        home_consumption=battery_to_home_kwh,
        battery_charged=0.0,
        battery_discharged=discharged,
        grid_imported=0.0,
        grid_exported=export_kwh,
        battery_soe_start=8.0,
        battery_soe_end=8.0 - discharged,
    )


def make_schedule(
    export_periods: dict[int, EnergyData], intent: str = "BATTERY_EXPORT"
) -> DPSchedule:
    """Full-day schedule with the given periods set to BATTERY_EXPORT."""
    intents = ["IDLE"] * NUM_PERIODS
    period_data: list[PeriodData | None] = [None] * NUM_PERIODS
    actions = [0.0] * NUM_PERIODS
    for period, energy in export_periods.items():
        intents[period] = intent
        period_data[period] = PeriodData(period=period, energy=energy)
        actions[period] = -energy.battery_discharged
    return DPSchedule(
        actions=actions,
        state_of_energy=[8.0] * NUM_PERIODS,
        prices=[1.0] * NUM_PERIODS,
        original_dp_results={
            "strategic_intent": intents,
            "period_data": period_data,
        },
    )


class TestExportMaterialityRates:
    """compute_rates_for_period demotes non-material BATTERY_EXPORT periods."""

    def test_home_dominant_small_export_demoted_to_full_load_following(
        self, controller
    ):
        """Issue #352: 0.15 kWh planned export against 0.3 kWh home load must
        not commit grid_first at a forced sub-load rate — the period gets
        load_first semantics with rate 100 so firmware can cover load spikes."""
        schedule = make_schedule({84: make_export_energy(0.3, 0.15)})
        controller.create_schedule(schedule)

        grid_charge, discharge_rate, _ = controller.compute_rates_for_period(84, -1.8)
        assert grid_charge is False
        assert discharge_rate == 100
        assert controller.mode_for_period(84) == "load_first"

    def test_export_dominant_period_keeps_grid_first_with_scaled_rate(self, controller):
        """A genuine arbitrage export (2.29 kWh export vs 0.21 kWh home) keeps
        the existing grid_first behavior and action-scaled rate."""
        schedule = make_schedule({84: make_export_energy(0.21, 2.29)})
        controller.create_schedule(schedule)

        grid_charge, discharge_rate, _ = controller.compute_rates_for_period(84, -2.5)
        assert grid_charge is False
        assert discharge_rate == 50  # 2.5 kW of 5 kW max
        assert controller.mode_for_period(84) == "grid_first"

    def test_sub_resolution_export_with_no_home_deficit_demoted(self, controller):
        """A sub-0.1 kWh export with no home deficit survives the #351 fold
        (battery_to_home == 0) and still classifies BATTERY_EXPORT, but is
        below the materiality floor — hardware must not commit grid_first
        for it."""
        energy = make_export_energy(0.0, 0.05)
        assert energy.battery_to_grid == pytest.approx(0.05)
        schedule = make_schedule({84: energy})
        controller.create_schedule(schedule)

        assert controller.compute_rates_for_period(84, -0.2)[:2] == (False, 100)
        assert controller.mode_for_period(84) == "load_first"

    def test_full_rate_home_dominant_spike_export_stays_grid_first(self, controller):
        """A near-full-rate export at a price spike (1.24 kWh discharge of a
        1.25 kWh max) must keep grid_first even though home dominates
        (0.95 kWh to home vs 0.29 kWh export): the commitment forfeits no
        load-following headroom, so there is no spike exposure to buy back
        by demoting — only export revenue to lose. Observed live in mock-HA
        E2E: a 6 SEK/kWh sell spike against a 0.95 kWh/period house load."""
        schedule = make_schedule({84: make_export_energy(0.95, 0.29)})
        controller.create_schedule(schedule)

        grid_charge, discharge_rate, _ = controller.compute_rates_for_period(84, -4.96)
        assert grid_charge is False
        assert discharge_rate == 99  # 4.96 kW of 5 kW max — action-scaled
        assert controller.mode_for_period(84) == "grid_first"

    def test_no_period_data_preserves_legacy_grid_first(self, controller):
        """Without planned flow data (older schedules, temp controllers), the
        materiality gate cannot judge the period and must preserve existing
        behavior."""
        schedule = make_schedule({84: make_export_energy(0.3, 0.15)})
        schedule.period_data = []
        controller.create_schedule(schedule)

        grid_charge, discharge_rate, _ = controller.compute_rates_for_period(84, -1.8)
        assert grid_charge is False
        assert discharge_rate == 36  # 1.8 kW of 5 kW max — action-scaled
        assert controller.mode_for_period(84) == "grid_first"

    def test_non_load_following_platform_never_demotes(self, battery_settings):
        """On platforms where discharge_rate is a forced power command (VPP
        style), rate 100 would force a full-power discharge (#324) — the gate
        must stay closed there."""

        class ForcedRateController(GrowattMinController):
            discharge_rate_is_load_following = False

        controller = ForcedRateController(battery_settings)
        schedule = make_schedule({84: make_export_energy(0.3, 0.15)})
        controller.create_schedule(schedule)

        grid_charge, discharge_rate, _ = controller.compute_rates_for_period(84, -1.8)
        assert (grid_charge, discharge_rate) == (False, 36)
        assert controller.mode_for_period(84) == "grid_first"


class TestIntentModeDecoupling:
    """The intent label stays BATTERY_EXPORT while hardware settings demote."""

    def test_period_settings_keep_intent_label_but_demote_hardware(self, controller):
        schedule = make_schedule({84: make_export_energy(0.3, 0.15)})
        controller.create_schedule(schedule)

        settings = controller.get_period_settings(84)
        assert settings["strategic_intent"] == "BATTERY_EXPORT"
        assert settings["batt_mode"] == "load_first"
        assert settings["discharge_rate"] == 100

    def test_detailed_period_groups_reflect_demotion(self, controller):
        """Display groups show the real hardware mode/rate, splitting demoted
        and material periods, with the intent label untouched."""
        export_periods = {
            80: make_export_energy(0.3, 0.15),  # demoted
            81: make_export_energy(0.3, 0.15),  # demoted
            82: make_export_energy(0.21, 2.29),  # material
        }
        schedule = make_schedule(export_periods)
        controller.create_schedule(schedule)

        groups = {
            g["start_period"]: g
            for g in controller.get_detailed_period_groups()
            if g["intent"] == "BATTERY_EXPORT"
        }
        demoted = groups[80]
        assert demoted["end_period"] == 81
        assert demoted["mode"] == "load_first"
        assert demoted["discharge_rate"] == 100

        material = groups[82]
        assert material["mode"] == "grid_first"


class TestTouSegments:
    """Demoted periods must not produce grid_first TOU segments."""

    def _grid_first_segments(self, controller):
        return [
            seg for seg in controller.tou_intervals if seg["batt_mode"] == "grid_first"
        ]

    def test_demoted_periods_produce_no_grid_first_segment(self, controller):
        schedule = make_schedule(
            {p: make_export_energy(0.3, 0.15) for p in range(80, 88)}
        )
        controller.create_schedule(schedule)
        assert self._grid_first_segments(controller) == []

    def test_material_block_still_gets_grid_first_segment(self, controller):
        export_periods = {p: make_export_energy(0.3, 0.15) for p in range(80, 84)}
        export_periods.update(
            {p: make_export_energy(0.21, 2.29) for p in range(84, 88)}
        )
        schedule = make_schedule(export_periods)
        controller.create_schedule(schedule)

        segments = self._grid_first_segments(controller)
        assert len(segments) == 1
        assert segments[0]["start_time"] == "21:00"
        assert segments[0]["end_time"] == "21:59"
