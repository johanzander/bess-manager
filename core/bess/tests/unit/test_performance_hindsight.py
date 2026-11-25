"""Retrospective economics use observations, never the live controller."""

import json
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.bess import time_utils
from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.execution_model import DEFAULT_CAPABILITIES, PlatformCapabilities
from core.bess.huawei_controller import HuaweiController
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.performance_hindsight import (
    ESTIMATE_LABEL,
    HindsightModel,
    analyze_period,
    calibrate_capacity,
    calibrate_efficiency,
    economic_comparison,
    solve_hindsight,
)
from core.bess.settings import BatterySettings, HomeSettings
from core.bess.simulation.inverter_simulator import simulate_physical_plan

WEEK = date(2026, 9, 7)
# Energy lattice of the production DP; a closing state can miss by one step.
DP_STEP = 0.1


def model_for(
    settings: BatterySettings, home: HomeSettings | None = None
) -> HindsightModel:
    return HindsightModel(
        settings,
        home or HomeSettings(currency="EUR"),
        replace(
            DEFAULT_CAPABILITIES,
            discharge_resolution_kw=DEFAULT_CAPABILITIES.discharge_rate_step_kw(
                settings
            ),
        ),
    )


def synthetic_week(
    store: DailyViewStore,
    start: date = WEEK,
    settings: BatterySettings | None = None,
) -> HindsightModel:
    settings = settings or BatterySettings(
        total_capacity=2,
        min_soc=0,
        max_soc=100,
        max_charge_power_kw=1,
        max_discharge_power_kw=1,
        efficiency_charge=1,
        efficiency_discharge=1,
        cycle_cost_per_kwh=0.02,
    )
    for day_index in range(7):
        day = start + timedelta(days=day_index)
        periods = []
        for index in range(time_utils.get_period_count(day)):
            ts = time_utils.period_start(day, index)
            solar = 0.6 if 10 <= ts.hour < 14 else 0.0
            demand = 0.2
            buy = -0.05 if 2 <= ts.hour < 4 else (0.6 if 18 <= ts.hour < 22 else 0.3)
            energy = EnergyData(
                solar,
                demand,
                0,
                0,
                max(0, demand - solar),
                max(0, solar - demand),
                settings.min_soe_kwh,
                settings.min_soe_kwh,
            )
            periods.append(
                PeriodData(
                    index,
                    energy,
                    ts,
                    "actual",
                    EconomicData.from_energy_data(energy, buy, 0.08),
                )
            )
        store.save_day(DailyView(day, periods, 0, len(periods), 0))
    return model_for(settings)


def _rewrite_week(
    store: DailyViewStore, change: Callable[[int, PeriodData], None]
) -> None:
    for day_index in range(7):
        day = WEEK + timedelta(days=day_index)
        view = store.load_day(day)
        assert view is not None
        for p in view.periods:
            change(day_index, p)
        store.save_day(view)


@pytest.mark.slow
def test_week_economics_constraints_and_realized_flows(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    result = analyze_period(store, WEEK, model)
    assert result.status == "estimated"
    c = result.comparison
    assert c is not None
    assert c.missed_savings > 0
    assert c.captured_percent == pytest.approx(0)
    # 56 ordinary, 8 negative-price, 16 peak and 16 PV-surplus quarters/day.
    expected = 7 * (56 * 0.2 * 0.3 + 8 * 0.2 * -0.05 + 16 * 0.2 * 0.6 - 16 * 0.4 * 0.08)
    assert c.actual.total_economic_cost == pytest.approx(expected)
    assert c.grid_only.total_economic_cost == pytest.approx(
        7 * 0.2 * (72 * 0.3 + 8 * -0.05 + 16 * 0.6)
    )
    assert sum(d.grid_only_cost for d in result.daily) == pytest.approx(
        c.grid_only.total_economic_cost
    )
    assert sum(d.optimal_wear_cost for d in result.daily) == pytest.approx(
        c.optimal.wear_cost
    )
    assert c.optimal.total_economic_cost < c.actual.total_economic_cost
    assert sum(d.optimal_grid_cost for d in result.daily) == pytest.approx(
        c.optimal.net_grid_cost
    )
    assert c.terminal_difference_kwh == pytest.approx(0, abs=1e-6)
    assert c.solver.simulation_cost_difference == pytest.approx(0, abs=0.01)
    for row in result.periods:
        e = row.optimal_energy
        assert 0 <= e.battery_soe_end <= model.battery.total_capacity + 1e-8
        assert e.battery_charged <= 0.25 + 1e-8
        assert e.battery_discharged <= 0.25 + 1e-8
        assert e.solar_to_home + e.battery_to_home + e.grid_to_home == pytest.approx(
            e.home_consumption
        )
        assert e.solar_production + e.grid_imported + e.battery_discharged == (
            pytest.approx(
                e.home_consumption
                + e.grid_exported
                + e.battery_charged
                + e.clipped_solar
            )
        )
        assert e.grid_to_home + e.grid_to_battery == pytest.approx(e.grid_imported)
    assert c.optimal.wear_cost == pytest.approx(
        c.optimal.charged_kwh * model.battery.cycle_cost_per_kwh
    )


def test_the_result_is_labelled_as_an_estimate_on_current_settings(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    result = analyze_period(store, WEEK, model, today=WEEK)
    assert ESTIMATE_LABEL in result.warnings
    assert result.currency == "EUR"


@pytest.mark.slow
def test_already_optimal_has_no_missed_opportunity(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    first = analyze_period(store, WEEK, model)
    by_timestamp = {row.timestamp: row.optimal_energy for row in first.periods}

    def follow_hindsight(_: int, p: PeriodData) -> None:
        assert p.timestamp is not None
        optimal = by_timestamp[p.timestamp.isoformat()]
        p.energy = EnergyData(
            **{
                f: optimal.__dict__[f]
                for f, spec in EnergyData.__dataclass_fields__.items()
                if spec.init
            }
        )
        p.economic = EconomicData.from_energy_data(
            p.energy, p.economic.buy_price, p.economic.sell_price
        )

    _rewrite_week(store, follow_hindsight)
    result = analyze_period(store, WEEK, model)
    assert result.comparison is not None
    assert result.comparison.missed_savings == pytest.approx(0, abs=0.01)
    assert result.comparison.captured_percent == pytest.approx(100, abs=0.1)


@pytest.mark.slow
@pytest.mark.parametrize("problem", ["missing", "predicted", "price"])
def test_unknown_quarters_are_left_out_not_zero_filled(
    tmp_path: Path, problem: str
) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    view = store.load_day(date(2026, 9, 9))
    assert view is not None
    if problem == "missing":
        view.periods.pop(30)
    elif problem == "predicted":
        view.periods[30].data_source = "predicted"
    store.save_day(view)
    if problem == "price":
        path = tmp_path / "2026-09-09.json"
        payload = json.loads(path.read_text())
        payload["periods"][30]["economic"]["buy_price"] = None
        path.write_text(json.dumps(payload))
    result = analyze_period(store, WEEK, model)
    assert result.status == "estimated_partial"
    assert [(e.date, e.period) for e in result.coverage.excluded_intervals] == [
        ("2026-09-09", 30)
    ]
    assert result.coverage.analyzed_periods == 7 * 96 - 1
    assert len(result.periods) == 7 * 96 - 1


@pytest.mark.parametrize("problem", ["soc", "meter"])
def test_inconsistent_history_is_reported(tmp_path: Path, problem: str) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    view = store.load_day(date(2026, 9, 9))
    assert view is not None
    p = view.periods[30]
    if problem == "soc":
        p.energy.battery_soe_start = 1
    else:
        p.energy.grid_imported += 1
    store.save_day(view)
    result = analyze_period(store, WEEK, model, today=date(2026, 9, 10))
    expected = (
        "Battery SOC has gaps between quarters or days."
        if problem == "soc"
        else "Energy meters or detailed household/export flows do not reconcile."
    )
    assert expected in result.warnings


def test_a_period_without_observations_has_no_comparison(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    result = analyze_period(store, WEEK, model_for(BatterySettings()))
    assert result.status == "insufficient_data"
    assert result.comparison is None
    assert result.issues


@pytest.mark.slow
@pytest.mark.parametrize(
    "start,expected", [(date(2026, 3, 23), 668), (date(2026, 10, 19), 676)]
)
def test_dst_weeks_use_elapsed_quarters_and_reconcile_totals(
    tmp_path: Path, start: date, expected: int
) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store, start)
    result = analyze_period(store, start, model, today=start + timedelta(days=8))
    assert result.status == "estimated"
    assert result.coverage.expected_periods == expected
    assert len({r.timestamp for r in result.periods}) == expected
    assert result.comparison is not None
    assert sum(d.actual_grid_cost for d in result.daily) == pytest.approx(
        result.comparison.actual.net_grid_cost
    )


@pytest.mark.slow
def test_week_in_progress_is_analyzed_to_date(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    result = analyze_period(store, WEEK, model, today=date(2026, 9, 13))
    assert result.in_progress is True
    assert result.coverage.expected_periods == 6 * 96
    assert len(result.periods) == 6 * 96
    assert result.coverage.excluded_intervals == []
    assert result.comparison is not None


@pytest.mark.parametrize(
    "actual,optimal,captured", [(12, 5, -40), (3, 5, 140), (10, 10, None)]
)
def test_capture_is_not_clamped(
    actual: float, optimal: float, captured: float | None
) -> None:
    missed, percent = economic_comparison(10, actual, optimal)
    assert missed == actual - optimal
    assert percent == captured


@pytest.mark.slow
def test_no_achievable_saving_is_na(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)

    def free(_: int, p: PeriodData) -> None:
        p.economic = EconomicData.from_energy_data(p.energy, 0, 0)

    _rewrite_week(store, free)
    result = analyze_period(store, WEEK, model)
    assert result.comparison is not None
    assert result.comparison.captured_percent is None


@pytest.mark.slow
def test_known_cross_midnight_arbitrage_cost(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)

    def arbitrage(day_index: int, p: PeriodData) -> None:
        demand = 0.25 if day_index == 1 and p.period == 0 else 0
        buy = 0.1 if day_index == 0 and p.period == 95 else 1.0
        p.energy = EnergyData(0, demand, 0, 0, demand, 0, 0, 0)
        p.economic = EconomicData.from_energy_data(p.energy, buy, 0)

    _rewrite_week(store, arbitrage)
    result = analyze_period(store, WEEK, model)
    assert result.status == "estimated"
    c = result.comparison
    assert c is not None
    assert c.actual.total_economic_cost == pytest.approx(0.25)
    assert c.optimal.total_economic_cost == pytest.approx(0.025 + 0.005)
    assert c.missed_savings == pytest.approx(0.22)
    assert result.periods[95].optimal_energy.battery_soe_end == pytest.approx(0.25)
    assert result.periods[96].optimal_energy.battery_soe_start == pytest.approx(0.25)


@pytest.mark.slow
def test_nonzero_historical_energy_is_not_given_away(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)

    def charged(_: int, p: PeriodData) -> None:
        p.energy.battery_soe_start = 0.83
        p.energy.battery_soe_end = 0.83

    _rewrite_week(store, charged)
    result = analyze_period(store, WEEK, model)
    if result.comparison is not None:
        assert result.comparison.initial_energy_kwh == pytest.approx(0.83)
        assert result.comparison.terminal_difference_kwh >= -DP_STEP
    else:
        assert result.status == "unsupported_model"


@pytest.mark.slow
def test_export_revenue_can_make_daily_net_grid_cost_negative(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)

    def export_price(_: int, p: PeriodData) -> None:
        p.economic = EconomicData.from_energy_data(
            p.energy,
            p.economic.buy_price,
            0.9 if p.energy.solar_production > 0 else 0.08,
        )

    _rewrite_week(store, export_price)
    result = analyze_period(store, WEEK, model)
    assert result.comparison is not None
    assert result.comparison.actual.net_grid_cost == pytest.approx(
        7 * (56 * 0.2 * 0.3 + 8 * 0.2 * -0.05 + 16 * 0.2 * 0.6 - 16 * 0.4 * 0.9)
    )
    assert all(day.actual_grid_cost < 0 for day in result.daily)


@pytest.mark.slow
def test_grid_charging_respects_the_house_import_limit(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    home = HomeSettings(
        currency="EUR",
        power_monitoring_enabled=True,
        phase_count=1,
        voltage=230,
        max_fuse_current=4,
        safety_margin=1,
    )
    result = analyze_period(store, WEEK, replace(model, home=home))
    assert result.comparison is not None
    assert max(p.optimal_energy.grid_imported for p in result.periods) <= 0.23 + 1e-6


def test_physical_replay_does_not_invent_energy_from_an_idle_state_drift() -> None:
    settings = BatterySettings(total_capacity=2, min_soc=0, max_soc=100)
    energy = EnergyData(0, 0, 0, 0, 0, 0, 1, 0.99)
    row = PeriodData(0, energy)
    row.decision.battery_action = 0
    replay = simulate_physical_plan(
        [row], [0], [0], [0.1], [0], 1, settings, 0.25, "EUR"
    )
    assert replay.period_data[0].energy.battery_soe_end == 1
    assert replay.realized_cost == 0


@pytest.mark.slow
def test_hindsight_prices_input_charge_throughput_before_selecting_actions() -> None:
    settings = BatterySettings(
        total_capacity=1,
        min_soc=0,
        max_soc=100,
        max_charge_power_kw=1,
        max_discharge_power_kw=1,
        efficiency_charge=0.5,
        efficiency_discharge=1,
        cycle_cost_per_kwh=0.4,
    )
    model = HindsightModel(
        settings,
        HomeSettings(currency="EUR"),
        PlatformCapabilities.from_controller(HuaweiController(settings), settings),
    )
    # Charging .25 input kWh stores .125. Its .10 wear cost exceeds .0875
    # avoided import, even though the stored-energy fee (.05) would not.
    rows = []
    for index, (home, price) in enumerate(zip([0, 0.125], [0, 0.7], strict=True)):
        energy = EnergyData(0, home, 0, 0, home, 0, 0, 0)
        rows.append(
            PeriodData(
                index, energy, economic=EconomicData.from_energy_data(energy, price, 0)
            )
        )
    solved, _ = solve_hindsight(rows, model, 0)
    assert sum(p.energy.battery_charged for p in solved) == 0
    assert sum(p.economic.hourly_cost for p in solved) == pytest.approx(0.0875)


def _reserve_week(store: DailyViewStore) -> HindsightModel:
    return synthetic_week(
        store,
        settings=BatterySettings(
            total_capacity=2,
            min_soc=10,
            max_soc=100,
            max_charge_power_kw=1,
            max_discharge_power_kw=1,
            efficiency_charge=1,
            efficiency_discharge=1,
            cycle_cost_per_kwh=0.02,
        ),
    )


@pytest.mark.slow
def test_restart_placeholders_and_zero_soc_readings_are_unknown(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    model = _reserve_week(store)
    day = date(2026, 9, 10)
    view = store.load_day(day)
    assert view is not None
    reserve = view.periods[0].energy.battery_soe_start
    for p in view.periods[40:45]:
        p.energy = EnergyData(0, 0, 0, 0, 0, 0, reserve, reserve)
        p.timestamp = time_utils.period_start(day, 50)
    for p in view.periods[50:53]:
        p.energy.battery_soe_start = 0.0
        p.energy.battery_soe_end = 0.0
    store.save_day(view)
    result = analyze_period(store, WEEK, model)
    assert result.coverage.restart_placeholders == 5
    assert result.coverage.soc_dropouts == 3
    assert [(e.date, e.period) for e in result.coverage.excluded_intervals] == [
        (day.isoformat(), index) for index in range(40, 45)
    ]
    dropouts = [
        row
        for row in result.periods
        if row.date == day.isoformat() and row.actual_soc is None
    ]
    assert len(dropouts) == 3
    assert result.comparison is not None
    assert result.comparison.actual_validation.minimum_energy_kwh == pytest.approx(
        reserve
    )


@pytest.mark.slow
def test_backup_use_below_the_reserve_is_left_out_and_never_used_by_hindsight(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    model = _reserve_week(store)
    reserve = model.battery.min_soe_kwh
    day = date(2026, 9, 9)
    view = store.load_day(day)
    assert view is not None
    # An outage drew on the backup reserve for two hours...
    for p in view.periods[40:48]:
        p.energy.battery_soe_start = reserve / 2
        p.energy.battery_soe_end = reserve / 2
        p.energy.battery_discharged = 0.1
    # ...while idle readings under the reserve are only standby drift.
    for p in view.periods[60:64]:
        p.energy.battery_soe_start = reserve / 2
        p.energy.battery_soe_end = reserve / 2
    store.save_day(view)
    result = analyze_period(store, WEEK, model)
    assert result.coverage.below_reserve_periods == 8
    assert [(e.period, e.reason) for e in result.coverage.excluded_intervals] == [
        (i, "battery below the configured reserve (backup use)") for i in range(40, 48)
    ]
    assert result.comparison is not None
    assert result.comparison.model_validation.minimum_energy_kwh >= reserve - 1e-6
    assert len(result.periods) == 7 * 96 - 8


@pytest.mark.slow
def test_a_disagreeing_consumption_meter_does_not_bill_only_hindsight(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    model = _reserve_week(store)
    consistent = analyze_period(store, WEEK, model).comparison

    def inflate(_: int, p: PeriodData) -> None:
        p.energy.home_consumption += 0.05

    _rewrite_week(store, inflate)
    result = analyze_period(store, WEEK, model)
    inflated = result.comparison
    assert consistent is not None and inflated is not None
    for scenario in ("actual", "optimal", "solar_only", "grid_only"):
        assert asdict(inflated)[scenario]["total_economic_cost"] == pytest.approx(
            asdict(consistent)[scenario]["total_economic_cost"]
        )
    assert any("consumption meter differs" in w for w in result.warnings)


def test_efficiency_is_calibrated_from_measured_battery_history() -> None:
    settings = BatterySettings(
        total_capacity=10,
        min_soc=10,
        max_soc=100,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
    )
    true_efficiency = 0.9
    day = date(2026, 11, 9)
    soe = 2.0
    periods = []
    # Charge 2 kWh per quarter for 8 quarters, then discharge 1 kWh for 13,
    # with one unknown quarter between two runs that leaves energy unchanged.
    plan = [(2.0, 0.0)] * 8 + [(0.0, 1.0)] * 13
    for index, (charge, discharge) in enumerate(plan):
        end = soe + charge * true_efficiency - discharge / true_efficiency
        energy = EnergyData(0, 1, charge, discharge, 1 + charge, 0, soe, end)
        if index != 10:
            periods.append(
                PeriodData(index, energy, time_utils.period_start(day, index), "actual")
            )
        soe = end
    result = calibrate_efficiency(periods, settings)
    assert result.applied is True
    assert result.charge == pytest.approx(true_efficiency, abs=1e-6)
    assert result.discharge == pytest.approx(true_efficiency, abs=1e-6)
    assert calibrate_efficiency(periods[:2], settings).applied is False


@pytest.mark.slow
def test_a_month_is_one_continuous_comparison_over_its_observed_days(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    model = _reserve_week(store)
    result = analyze_period(
        store, date(2026, 9, 20), model, period="month", today=date(2026, 10, 5)
    )
    assert (result.start_date, result.end_date) == ("2026-09-01", "2026-09-30")
    assert result.coverage.expected_periods == 30 * 96
    assert len(result.periods) == 7 * 96
    assert len(result.daily) == 30
    assert result.status == "estimated_partial"
    assert result.available_periods == ["2026-09-01"]


@pytest.mark.slow
def test_calibration_names_the_history_it_used(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    model = synthetic_week(store)
    result = analyze_period(
        store, WEEK, model, battery_history_source="the battery meters"
    )
    assert result.battery_model is not None
    assert result.battery_model.history_source == "the battery meters"
    assert result.battery_model.efficiency_calibration is not None
    # The synthetic week never moves the battery, so nothing is calibrated.
    assert result.battery_model.efficiency_calibration.applied is False
    assert result.battery_model.capacity_kwh == model.battery.total_capacity


def test_usable_capacity_is_calibrated_from_one_way_battery_runs() -> None:
    configured = BatterySettings(
        total_capacity=10,
        min_soc=0,
        max_soc=100,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
    )
    true_capacity, true_efficiency = 12.0, 0.9
    day = date(2026, 11, 9)
    stored = 2.0
    periods = []
    # Alternating charge and discharge runs of different lengths.
    plan = []
    for length in (4, 5, 6, 3, 5, 4):
        plan += (
            [(1.0, 0.0)] * length + [(0.0, 0.0)] + [(0.0, 0.8)] * length + [(0.0, 0.0)]
        )
    for index, (charge, discharge) in enumerate(plan):
        end = stored + charge * true_efficiency - discharge / true_efficiency
        # The history records SOC % times the configured capacity.
        energy = EnergyData(
            0,
            0.5,
            charge,
            discharge,
            0.5 + charge,
            0,
            stored / true_capacity * configured.total_capacity,
            end / true_capacity * configured.total_capacity,
        )
        periods.append(
            PeriodData(index, energy, time_utils.period_start(day, index), "actual")
        )
        stored = end
    result = calibrate_capacity(periods, configured)
    assert result.applied is True
    assert result.capacity_kwh == pytest.approx(true_capacity, rel=0.01)
    assert result.charge == pytest.approx(true_efficiency, abs=0.002)
    assert result.discharge == pytest.approx(true_efficiency, abs=0.002)
