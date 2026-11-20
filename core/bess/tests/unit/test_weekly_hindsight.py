"""Retrospective economics use observations, never the live controller."""

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.bess import time_utils
from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.execution_model import DEFAULT_CAPABILITIES, PlatformCapabilities
from core.bess.huawei_controller import HuaweiController
from core.bess.models import EconomicData, EnergyData, PeriodData
from core.bess.settings import BatterySettings, HomeSettings
from core.bess.simulation.inverter_simulator import simulate_physical_plan
from core.bess.weekly_hindsight import (
    analyze_week,
    economic_comparison,
    historical_context,
    solve_hindsight,
)


def synthetic_week(
    store: DailyViewStore,
    start: date = date(2026, 9, 7),
    settings: BatterySettings | None = None,
) -> BatterySettings:
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
    context = historical_context(
        settings,
        HomeSettings(currency="EUR"),
        replace(
            DEFAULT_CAPABILITIES,
            discharge_resolution_kw=DEFAULT_CAPABILITIES.discharge_rate_step_kw(
                settings
            ),
        ),
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
                observation_verified=True,
            )
            periods.append(
                PeriodData(
                    index,
                    energy,
                    ts,
                    "actual",
                    EconomicData.from_energy_data(energy, buy, 0.08),
                    historical_inputs=context,
                )
            )
        store.save_day(DailyView(day, periods, 0, len(periods), 0))
    return settings


@pytest.mark.slow
def test_week_economics_constraints_and_realized_flows(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    settings = synthetic_week(store)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["status"] == "complete"
    assert result["missed_savings"] > 0
    assert result["captured_percent"] == pytest.approx(0)
    # 56 ordinary, 8 negative-price, 16 peak and 16 PV-surplus quarters/day.
    expected = 7 * (56 * 0.2 * 0.3 + 8 * 0.2 * -0.05 + 16 * 0.2 * 0.6 - 16 * 0.4 * 0.08)
    assert result["actual"]["total_economic_cost"] == pytest.approx(expected)
    assert (
        result["optimal"]["total_economic_cost"]
        < result["actual"]["total_economic_cost"]
    )
    assert sum(d["optimal_grid_cost"] for d in result["daily"]) == pytest.approx(
        result["optimal"]["net_grid_cost"]
    )
    assert result["terminal_difference_kwh"] == pytest.approx(0, abs=1e-6)
    assert result["simulation_cost_difference"] == pytest.approx(0, abs=0.01)
    for row in result["periods"]:
        e = row["optimal_energy"]
        assert 0 <= e["battery_soe_end"] <= settings.total_capacity + 1e-8
        assert e["battery_charged"] <= 0.25 + 1e-8
        assert e["battery_discharged"] <= 0.25 + 1e-8
        assert e["solar_to_home"] + e["battery_to_home"] + e[
            "grid_to_home"
        ] == pytest.approx(e["home_consumption"])
        assert e["solar_production"] + e["grid_imported"] + e[
            "battery_discharged"
        ] == pytest.approx(
            e["home_consumption"]
            + e["grid_exported"]
            + e["battery_charged"]
            + e["clipped_solar"]
        )
        assert e["grid_to_home"] + e["grid_to_battery"] == pytest.approx(
            e["grid_imported"]
        )
    assert result["optimal"]["wear_cost"] == pytest.approx(
        result["optimal"]["charged_kwh"] * settings.cycle_cost_per_kwh
    )


@pytest.mark.slow
def test_already_optimal_has_no_missed_opportunity(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    first = analyze_week(store, date(2026, 9, 7))
    for day_index in range(7):
        day = date(2026, 9, 7) + timedelta(days=day_index)
        view = store.load_day(day)
        assert view is not None
        rows = [r for r in first["periods"] if r["date"] == day.isoformat()]
        for p, row in zip(view.periods, rows, strict=True):
            p.energy = EnergyData(
                **{
                    k: v
                    for k, v in row["optimal_energy"].items()
                    if k in EnergyData.__dataclass_fields__
                    and EnergyData.__dataclass_fields__[k].init
                }
            )
            p.energy.observation_verified = True
            p.economic = EconomicData.from_energy_data(
                p.energy, p.economic.buy_price, p.economic.sell_price
            )
        store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["missed_savings"] == pytest.approx(0, abs=0.01)
    assert result["captured_percent"] == pytest.approx(100, abs=0.1)


@pytest.mark.parametrize(
    "problem",
    ["missing", "predicted", "price", "soc", "meter", "configuration", "legacy"],
)
def test_bad_history_cannot_create_savings(tmp_path: Path, problem: str) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    view = store.load_day(date(2026, 9, 9))
    assert view is not None
    p = view.periods[30]
    if problem == "missing":
        view.periods.pop(30)
    elif problem == "predicted":
        p.data_source = "predicted"
    elif problem == "price":
        p.economic.prices_verified = None
    elif problem == "soc":
        p.energy.battery_soe_start = 1
    elif problem == "meter":
        p.energy.grid_imported += 1
    elif problem == "configuration":
        assert p.historical_inputs is not None
        p.historical_inputs = {**p.historical_inputs, "currency": "SEK"}
    else:
        p.historical_inputs = None
    store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["status"] == "insufficient_data"
    assert result["captured_percent"] is None
    assert result["optimal"] is None
    assert result["issues"]


@pytest.mark.parametrize(
    "section,key", [("economic", "buy_price"), ("energy", "battery_soe_start")]
)
def test_null_historical_values_are_data_gaps(
    tmp_path: Path, section: str, key: str
) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    path = tmp_path / "2026-09-07.json"
    payload = json.loads(path.read_text())
    payload["periods"][0][section][key] = None
    path.write_text(json.dumps(payload))
    result = analyze_week(store, date(2026, 9, 7))
    assert result["status"] == "insufficient_data"
    assert result["captured_percent"] is None
    assert result["optimal"] is None


@pytest.mark.slow
@pytest.mark.parametrize(
    "start,expected", [(date(2026, 3, 23), 668), (date(2026, 10, 19), 676)]
)
def test_dst_weeks_use_elapsed_quarters_and_reconcile_totals(
    tmp_path: Path, start: date, expected: int
) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store, start)
    result = analyze_week(store, start, today=start + timedelta(days=8))
    assert result["status"] == "complete"
    assert result["expected_periods"] == expected
    assert len({r["timestamp"] for r in result["periods"]}) == expected
    assert sum(d["actual_grid_cost"] for d in result["daily"]) == pytest.approx(
        result["actual"]["net_grid_cost"]
    )


def test_incomplete_week_is_not_analyzed(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    result = analyze_week(store, date(2026, 9, 7), today=date(2026, 9, 13))
    assert result["optimal"] is None
    assert result["captured_percent"] is None


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
    synthetic_week(store)
    for day_index in range(7):
        day = date(2026, 9, 7) + timedelta(days=day_index)
        view = store.load_day(day)
        assert view is not None
        for p in view.periods:
            p.economic = EconomicData.from_energy_data(p.energy, 0, 0)
        store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["captured_percent"] is None


@pytest.mark.slow
def test_known_cross_midnight_arbitrage_cost(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    for day_index in range(7):
        day = date(2026, 9, 7) + timedelta(days=day_index)
        view = store.load_day(day)
        assert view is not None
        for p in view.periods:
            demand = 0.25 if day_index == 1 and p.period == 0 else 0
            buy = 0.1 if day_index == 0 and p.period == 95 else 1.0
            p.energy = EnergyData(
                0, demand, 0, 0, demand, 0, 0, 0, observation_verified=True
            )
            p.economic = EconomicData.from_energy_data(p.energy, buy, 0)
        store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["status"] == "complete"
    assert result["actual"]["total_economic_cost"] == pytest.approx(0.25)
    assert result["optimal"]["total_economic_cost"] == pytest.approx(0.025 + 0.005)
    assert result["missed_savings"] == pytest.approx(0.22)
    assert result["periods"][95]["optimal_energy"]["battery_soe_end"] == pytest.approx(
        0.25
    )
    assert result["periods"][96]["optimal_energy"][
        "battery_soe_start"
    ] == pytest.approx(0.25)


@pytest.mark.slow
def test_nonzero_historical_energy_is_not_given_away(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    for day_index in range(7):
        day = date(2026, 9, 7) + timedelta(days=day_index)
        view = store.load_day(day)
        assert view is not None
        for p in view.periods:
            p.energy.battery_soe_start = 0.83
            p.energy.battery_soe_end = 0.83
        store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    if result["status"] == "complete":
        assert result["initial_energy_kwh"] == pytest.approx(0.83)
        assert result["terminal_difference_kwh"] >= -1e-6
    else:
        assert result["status"] == "unsupported_model"
        assert result["captured_percent"] is None
        assert result["missed_savings"] is None


@pytest.mark.slow
def test_export_revenue_can_make_daily_net_grid_cost_negative(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    for day_index in range(7):
        day = date(2026, 9, 7) + timedelta(days=day_index)
        view = store.load_day(day)
        assert view is not None
        for p in view.periods:
            p.economic = EconomicData.from_energy_data(
                p.energy,
                p.economic.buy_price,
                0.9 if p.energy.solar_production > 0 else 0.08,
            )
        store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["status"] == "complete"
    assert result["actual"]["net_grid_cost"] == pytest.approx(
        7 * (56 * 0.2 * 0.3 + 8 * 0.2 * -0.05 + 16 * 0.2 * 0.6 - 16 * 0.4 * 0.9)
    )
    assert all(day["actual_grid_cost"] < 0 for day in result["daily"])


@pytest.mark.slow
def test_grid_charging_respects_the_recorded_house_import_limit(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    settings = synthetic_week(store)
    home = HomeSettings(
        currency="EUR",
        power_monitoring_enabled=True,
        phase_count=1,
        voltage=230,
        max_fuse_current=4,
        safety_margin=1,
    )
    context = historical_context(settings, home, DEFAULT_CAPABILITIES)
    for day_index in range(7):
        view = store.load_day(date(2026, 9, 7) + timedelta(days=day_index))
        assert view is not None
        for p in view.periods:
            p.historical_inputs = context
        store.save_day(view)
    result = analyze_week(store, date(2026, 9, 7))
    assert result["status"] == "complete"
    assert (
        max(p["optimal_energy"]["grid_imported"] for p in result["periods"])
        <= 0.23 + 1e-6
    )


@pytest.mark.slow
def test_estimated_mode_separates_measurements_from_approved_configuration(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    settings = synthetic_week(store)
    assumptions = historical_context(
        settings, HomeSettings(currency="EUR"), DEFAULT_CAPABILITIES
    )
    assumptions["assumption_source"] = "user-approved test backup"
    for offset in range(7):
        view = store.load_day(date(2026, 9, 7) + timedelta(days=offset))
        assert view is not None
        for p in view.periods:
            p.historical_inputs = None
            p.energy.observation_verified = None
            p.economic.prices_verified = None
        view.periods[-1].data_source = "predicted"
        store.save_day(view)
    strict = analyze_week(store, date(2026, 9, 7))
    assert strict["diagnostics"]["actual_periods"] == 665
    assert strict["diagnostics"]["prices_available"] == 672
    assert strict["diagnostics"]["soc_available"] == 665
    assert strict["diagnostics"]["configuration_recorded"] == 0
    assert strict["optimal"] is None
    estimated = analyze_week(
        store,
        date(2026, 9, 7),
        mode="estimated",
        assumed_context=assumptions,
        allow_partial=True,
    )
    assert estimated["status"] == "estimated_partial"
    assert len(estimated["periods"]) == 665
    assert len(estimated["excluded_intervals"]) == 7
    assert estimated["captured_percent"] is None
    assert estimated["missed_savings"] is None
    assert estimated["model_cost_difference"] is not None
    assert estimated["assumptions"]["source"] == "user-approved test backup"


def test_estimated_mode_requires_an_explicit_assumption_context(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="assumption"):
        analyze_week(DailyViewStore(tmp_path), date(2026, 9, 7), mode="estimated")


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
    context = historical_context(
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
    solved, _ = solve_hindsight(rows, context, 0)
    assert sum(p.energy.battery_charged for p in solved) == 0
    assert sum(p.economic.hourly_cost for p in solved) == pytest.approx(0.0875)
