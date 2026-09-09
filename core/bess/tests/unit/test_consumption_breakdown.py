"""Home-load forecast breakdown — residual / planned / total (issue #749).

Managed Loads (#706) subtracts a managed sensor's own history from the
ha_statistics baseline; Planned Consumption Changes (#428) then overlays
declared blocks. Both fold into a single ``consumption_predictions`` array
before the optimizer runs, so the dashboard can only ever draw one combined
Home Load curve.

These tests pin the split being carried alongside that array — from
``_gather_optimization_data`` where it is first known, through the stored
schedule's ``PeriodData``, into the daily view (including elapsed periods,
where the plan is looked up so actual-vs-planned is possible), and out to the
dashboard API.
"""

from datetime import datetime

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.consumption_overlay import OverlayBlock
from core.bess.models import (
    ConsumptionBreakdown,
    DecisionData,
    EconomicData,
    EnergyData,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController


@pytest.fixture
def system_fixed_1kwh(
    mock_controller: MockHomeAssistantController,
) -> BatterySystemManager:
    """A system on the 'fixed' strategy: 1.0 kWh/h → 0.25 kWh per period."""
    system = BatterySystemManager(
        controller=mock_controller,
        price_source=MockSource([1.0] * 96),
    )
    system.home_settings.consumption_strategy = "fixed"
    system.home_settings.default_hourly = 1.0
    return system


# --- The split at the point it is first known ------------------------------


def test_breakdown_splits_residual_from_planned_for_each_period(
    system_fixed_1kwh: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An EV block adds to `planned`, leaving `residual` at the base forecast."""
    system = system_fixed_1kwh
    period_count = time_utils.get_period_count(time_utils.today())

    block = OverlayBlock(
        start=time_utils.period_index_to_timestamp(88),
        end=time_utils.period_index_to_timestamp(92),
        energy_kwh=4.0,
        mode="add",
    )
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: [block]
    )

    result = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result is not None
    _, data = result

    breakdown = data["full_consumption_breakdown"]
    assert len(breakdown) == period_count

    # Covered periods: residual stays at the flat base, planned carries the block.
    for i in range(88, 92):
        assert breakdown[i].residual == pytest.approx(0.25)
        assert breakdown[i].planned == pytest.approx(1.0)
        assert breakdown[i].total == pytest.approx(1.25)

    # Uncovered period: nothing planned.
    assert breakdown[87].residual == pytest.approx(0.25)
    assert breakdown[87].planned == pytest.approx(0.0)
    assert breakdown[87].total == pytest.approx(0.25)


def test_breakdown_total_always_equals_residual_plus_planned(
    system_fixed_1kwh: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant the stacked chart relies on holds for every period."""
    system = system_fixed_1kwh
    period_count = time_utils.get_period_count(time_utils.today())

    block = OverlayBlock(
        start=time_utils.period_index_to_timestamp(40),
        end=time_utils.period_index_to_timestamp(48),
        energy_kwh=6.0,
        mode="add",
    )
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: [block]
    )

    result = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result is not None
    _, data = result

    breakdown = data["full_consumption_breakdown"]
    full_consumption = data["full_consumption"]
    for i, part in enumerate(breakdown):
        assert part.residual + part.planned == pytest.approx(part.total)
        assert part.total == pytest.approx(full_consumption[i])


def test_breakdown_has_zero_planned_when_no_overlay_configured(
    system_fixed_1kwh: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No overlay entity is a normal state: residual == total, planned == 0."""
    system = system_fixed_1kwh
    period_count = time_utils.get_period_count(time_utils.today())
    monkeypatch.setattr(system.controller, "get_consumption_overlay_blocks", lambda: [])

    result = system._gather_optimization_data(
        period=0, current_soc=50.0, prepare_next_day=False, period_count=period_count
    )
    assert result is not None
    _, data = result

    breakdown = data["full_consumption_breakdown"]
    assert all(part.planned == 0.0 for part in breakdown)
    assert all(part.residual == pytest.approx(part.total) for part in breakdown)


# --- Carried into the stored schedule -------------------------------------


def test_stored_schedule_period_data_carries_the_breakdown(
    quarterly_battery_system: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The split survives into schedule_store, which the daily view reads."""
    system = quarterly_battery_system
    block = OverlayBlock(
        start=time_utils.period_index_to_timestamp(80),
        end=time_utils.period_index_to_timestamp(84),
        energy_kwh=4.0,
        mode="add",
    )
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: [block]
    )

    assert system.update_battery_schedule(current_period=0, prepare_next_day=False)

    stored = system.schedule_store.get_latest_schedule()
    assert stored is not None
    by_period = {p.period: p for p in stored.optimization_result.period_data}

    covered = by_period[80].consumption_breakdown
    assert covered is not None
    assert covered.planned == pytest.approx(1.0)
    assert covered.residual + covered.planned == pytest.approx(covered.total)

    uncovered = by_period[10].consumption_breakdown
    assert uncovered is not None
    assert uncovered.planned == pytest.approx(0.0)


def test_daily_view_attaches_planned_breakdown_to_elapsed_periods(
    quarterly_battery_system: BatterySystemManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An elapsed period keeps its measured load but gains the planned split.

    The dashboard needs both to draw actual-vs-planned for the past.
    """
    system = quarterly_battery_system
    block = OverlayBlock(
        start=time_utils.period_index_to_timestamp(4),
        end=time_utils.period_index_to_timestamp(8),
        energy_kwh=4.0,
        mode="add",
    )
    monkeypatch.setattr(
        system.controller, "get_consumption_overlay_blocks", lambda: [block]
    )

    # Plan the whole day from period 0, so periods 4..7 are planned with the block.
    assert system.update_battery_schedule(current_period=0, prepare_next_day=False)

    # Period 5 has now elapsed: record real sensor data for it.
    measured = EnergyData(
        solar_production=0.0,
        home_consumption=2.5,  # deliberately not the 1.25 that was planned
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=2.5,
        grid_exported=0.0,
        battery_soe_start=15.0,
        battery_soe_end=15.0,
    )
    system.historical_store.record_period(
        period_index=5,
        period_data=PeriodData(
            period=5,
            energy=measured,
            timestamp=time_utils.period_index_to_timestamp(5),
            data_source="actual",
        ),
    )

    view = system.daily_view_builder.build_daily_view(current_period=10)
    elapsed = view.periods[5]

    assert elapsed.data_source == "actual"
    assert elapsed.energy.home_consumption == pytest.approx(2.5)  # measured, untouched
    assert elapsed.consumption_breakdown is not None
    # The split describes what was PLANNED, not what was measured.
    assert elapsed.consumption_breakdown.planned == pytest.approx(
        1.0
    )  # block over 4..7
    assert (
        elapsed.consumption_breakdown.residual + elapsed.consumption_breakdown.planned
        == pytest.approx(elapsed.consumption_breakdown.total)
    )
    assert elapsed.consumption_breakdown.total != pytest.approx(2.5)


# --- Out to the dashboard API -------------------------------------------------


def _period_with_breakdown(breakdown: ConsumptionBreakdown | None) -> PeriodData:
    return PeriodData(
        period=0,
        energy=EnergyData(
            solar_production=0.0,
            home_consumption=1.25,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=1.25,
            grid_exported=0.0,
            battery_soe_start=10.0,
            battery_soe_end=10.0,
        ),
        timestamp=datetime(2026, 9, 9, 0, 0),
        data_source="predicted",
        economic=EconomicData(),
        decision=DecisionData(),
        consumption_breakdown=breakdown,
    )


def test_api_hourly_data_exposes_the_three_load_series() -> None:
    from backend.api_dataclasses import APIDashboardHourlyData

    period = _period_with_breakdown(
        ConsumptionBreakdown(residual=0.25, planned=1.0, total=1.25)
    )
    api = APIDashboardHourlyData.from_internal(
        period, battery_capacity=30.0, currency="SEK"
    )

    assert api.predictedResidualLoad.value == pytest.approx(0.25)
    assert api.plannedManagedLoad.value == pytest.approx(1.0)
    assert api.predictedTotalLoad.value == pytest.approx(1.25)


def test_api_hourly_data_falls_back_to_total_when_no_breakdown() -> None:
    """A period with no split (overlay-free install, missing plan) still yields
    a valid stacked series: everything is residual, nothing is planned."""
    from backend.api_dataclasses import APIDashboardHourlyData

    period = _period_with_breakdown(None)
    api = APIDashboardHourlyData.from_internal(
        period, battery_capacity=30.0, currency="SEK"
    )

    assert api.predictedResidualLoad.value == pytest.approx(1.25)
    assert api.plannedManagedLoad.value == pytest.approx(0.0)
    assert api.predictedTotalLoad.value == pytest.approx(1.25)
