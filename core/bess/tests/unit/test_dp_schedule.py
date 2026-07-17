"""Tests for DPSchedule (core/bess/dp_schedule.py)."""

from core.bess.dp_schedule import DPSchedule
from core.bess.models import DecisionData, EnergyData, PeriodData


def _make_period_data(period: int, intent: str, grid_exported: float) -> PeriodData:
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=1.0,
            battery_charged=0.0,
            battery_discharged=1.0,
            grid_imported=0.0,
            grid_exported=grid_exported,
            battery_soe_start=10.0,
            battery_soe_end=9.0,
        ),
        decision=DecisionData(strategic_intent=intent),
    )


def test_period_data_extracted_from_original_dp_results():
    """#320: DPSchedule must expose original_dp_results['period_data'] as
    self.period_data, mirroring how strategic_intents is already extracted,
    so controllers can access grid_exported per period for debouncing."""
    pd_list = [
        _make_period_data(0, "LOAD_SUPPORT", 0.0),
        _make_period_data(1, "BATTERY_EXPORT", 0.02),
    ]
    schedule = DPSchedule(
        actions=[0.0, 0.0],
        state_of_energy=[10.0, 9.0],
        prices=[0.3, 0.3],
        original_dp_results={
            "strategic_intent": ["LOAD_SUPPORT", "BATTERY_EXPORT"],
            "period_data": pd_list,
        },
    )
    assert schedule.period_data == pd_list


def test_period_data_defaults_to_empty_list():
    schedule = DPSchedule(
        actions=[0.0],
        state_of_energy=[10.0],
        prices=[0.3],
        original_dp_results={"strategic_intent": ["IDLE"]},
    )
    assert schedule.period_data == []
