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
from core.bess.performance_hindsight import (
    analyze_period,
    calibrate_capacity,
    calibrate_efficiency,
    economic_comparison,
    historical_context,
    huawei_tou_replay,
    solve_hindsight,
)
from core.bess.settings import BatterySettings, HomeSettings
from core.bess.simulation.inverter_simulator import simulate_physical_plan


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
                    EconomicData.from_energy_data(
                        energy, buy, 0.08, prices_verified=True
                    ),
                    historical_inputs=context,
                )
            )
        store.save_day(DailyView(day, periods, 0, len(periods), 0))
    return settings


@pytest.mark.slow
def test_week_economics_constraints_and_realized_flows(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    settings = synthetic_week(store)
    result = analyze_period(store, date(2026, 9, 7))
    assert result["status"] == "complete"
    assert result["missed_savings"] > 0
    assert result["captured_percent"] == pytest.approx(0)
    # 56 ordinary, 8 negative-price, 16 peak and 16 PV-surplus quarters/day.
    expected = 7 * (56 * 0.2 * 0.3 + 8 * 0.2 * -0.05 + 16 * 0.2 * 0.6 - 16 * 0.4 * 0.08)
    assert result["actual"]["total_economic_cost"] == pytest.approx(expected)
    assert result["grid_only"]["total_economic_cost"] == pytest.approx(
        7 * 0.2 * (72 * 0.3 + 8 * -0.05 + 16 * 0.6)
    )
    assert sum(d["grid_only_cost"] for d in result["daily"]) == pytest.approx(
        result["grid_only"]["total_economic_cost"]
    )
    assert sum(d["optimal_wear_cost"] for d in result["daily"]) == pytest.approx(
        result["optimal"]["wear_cost"]
    )
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
    first = analyze_period(store, date(2026, 9, 7))
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
                p.energy,
                p.economic.buy_price,
                p.economic.sell_price,
                prices_verified=True,
            )
        store.save_day(view)
    result = analyze_period(store, date(2026, 9, 7))
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
    result = analyze_period(store, date(2026, 9, 7))
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
    result = analyze_period(store, date(2026, 9, 7))
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
    result = analyze_period(store, start, today=start + timedelta(days=8))
    assert result["status"] == "complete"
    assert result["expected_periods"] == expected
    assert len({r["timestamp"] for r in result["periods"]}) == expected
    assert sum(d["actual_grid_cost"] for d in result["daily"]) == pytest.approx(
        result["actual"]["net_grid_cost"]
    )


@pytest.mark.slow
def test_week_in_progress_is_analyzed_to_date_without_full_week_claims(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    synthetic_week(store)
    result = analyze_period(store, date(2026, 9, 7), today=date(2026, 9, 13))
    assert result["in_progress"] is True
    assert result["expected_periods"] == 6 * 96
    assert len(result["periods"]) == 6 * 96
    assert result["excluded_intervals"] == []
    assert result["optimal"] is not None
    assert result["captured_percent"] is None
    assert result["missed_savings"] is None
    assert result["conditional_captured_percent"] is not None


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
            p.economic = EconomicData.from_energy_data(
                p.energy, 0, 0, prices_verified=True
            )
        store.save_day(view)
    result = analyze_period(store, date(2026, 9, 7))
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
            p.economic = EconomicData.from_energy_data(
                p.energy, buy, 0, prices_verified=True
            )
        store.save_day(view)
    result = analyze_period(store, date(2026, 9, 7))
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
    result = analyze_period(store, date(2026, 9, 7))
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
                prices_verified=True,
            )
        store.save_day(view)
    result = analyze_period(store, date(2026, 9, 7))
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
    result = analyze_period(store, date(2026, 9, 7))
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
    strict = analyze_period(store, date(2026, 9, 7))
    assert strict["diagnostics"]["actual_periods"] == 665
    assert strict["diagnostics"]["prices_available"] == 672
    assert strict["diagnostics"]["soc_available"] == 665
    assert strict["diagnostics"]["configuration_recorded"] == 0
    assert strict["optimal"] is None
    estimated = analyze_period(
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
        analyze_period(DailyViewStore(tmp_path), date(2026, 9, 7), mode="estimated")


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


def test_a_finite_price_is_not_evidence_of_its_provenance() -> None:
    energy = EnergyData(0, 0.2, 0, 0, 0.2, 0, 1, 1)
    assert EconomicData.from_energy_data(energy, 0.3, 0.1).prices_verified is None


def _legacy_week(store: DailyViewStore) -> dict:
    settings = synthetic_week(
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
    for offset in range(7):
        view = store.load_day(date(2026, 9, 7) + timedelta(days=offset))
        assert view is not None
        for p in view.periods:
            p.historical_inputs = None
            p.energy.observation_verified = None
            p.economic.prices_verified = None
        store.save_day(view)
    assumptions = historical_context(
        settings, HomeSettings(currency="EUR"), DEFAULT_CAPABILITIES
    )
    assumptions["assumption_source"] = "user-approved test backup"
    return assumptions


@pytest.mark.slow
def test_restart_placeholders_and_zero_soc_readings_are_unknown(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    assumptions = _legacy_week(store)
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
    result = analyze_period(
        store,
        date(2026, 9, 7),
        mode="estimated",
        assumed_context=assumptions,
        allow_partial=True,
    )
    assert result["diagnostics"]["restart_placeholders"] == 5
    assert result["diagnostics"]["soc_dropouts"] == 3
    assert [(e["date"], e["period"]) for e in result["excluded_intervals"]] == [
        (day.isoformat(), index) for index in range(40, 45)
    ]
    assert result["missed_savings"] is None
    dropouts = [
        row
        for row in result["periods"]
        if row["date"] == day.isoformat() and row["actual_soc"] is None
    ]
    assert len(dropouts) == 3
    assert result["actual_validation"]["minimum_energy_kwh"] == pytest.approx(reserve)


@pytest.mark.slow
def test_published_reference_reprices_estimates_and_blocks_verified_claims(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    assumptions = _legacy_week(store)
    stored: dict[str, tuple[float, float]] = {}
    imported_on_changed_day = 0.0
    for offset in range(7):
        day = date(2026, 9, 7) + timedelta(days=offset)
        view = store.load_day(day)
        assert view is not None
        for p in view.periods:
            shift = 0.1 if offset == 2 else 0.0
            imported_on_changed_day += p.energy.grid_imported if shift else 0
            stored[time_utils.period_start(day, p.period).isoformat()] = (
                p.economic.buy_price + shift,
                p.economic.sell_price,
            )
    reference = {"source": "test publication", "prices": stored}
    plain = analyze_period(
        store, date(2026, 9, 7), mode="estimated", assumed_context=assumptions
    )
    repriced = analyze_period(
        store,
        date(2026, 9, 7),
        mode="estimated",
        assumed_context=assumptions,
        price_reference=reference,
    )
    assert repriced["diagnostics"]["prices_reference_mismatched"] == 96
    assert repriced["diagnostics"]["prices_reference_confirmed"] == 672 - 96
    assert repriced["actual"]["import_cost"] - plain["actual"][
        "import_cost"
    ] == pytest.approx(0.1 * imported_on_changed_day)
    verified = analyze_period(store, date(2026, 9, 7), price_reference=reference)
    assert verified["optimal"] is None
    assert any("published reference" in issue for issue in verified["issues"])


def test_huawei_replay_executes_period_list_semantics() -> None:
    settings = BatterySettings(
        total_capacity=4,
        min_soc=10,
        max_soc=90,
        max_charge_power_kw=2,
        max_discharge_power_kw=2,
        efficiency_charge=1,
        efficiency_discharge=1,
    )
    context = historical_context(
        settings,
        HomeSettings(currency="EUR"),
        PlatformCapabilities.from_controller(HuaweiController(settings), settings),
    )
    day = date(2026, 11, 9)
    intents = ["GRID_CHARGING"] * 8 + ["BATTERY_EXPORT"] * 8 + ["IDLE"] * 80
    actual = []
    optimal = []
    for index, intent in enumerate(intents):
        energy = EnergyData(0, 0.2, 0, 0, 0.2, 0, 0.4, 0.4)
        row = PeriodData(
            index,
            energy,
            time_utils.period_start(day, index),
            "actual",
            EconomicData.from_energy_data(energy, 0.1, 0.05),
        )
        actual.append(row)
        planned = replace(row, decision=replace(row.decision, strategic_intent=intent))
        optimal.append(planned)
    replay, blocks = huawei_tou_replay(optimal, actual, context)
    assert blocks == {day.isoformat(): 2}
    assert all(p.energy.battery_to_grid == pytest.approx(0) for p in replay)
    assert replay[7].energy.battery_soe_end == pytest.approx(settings.max_soe_kwh)
    for p in replay[8:16]:
        assert p.energy.battery_discharged == pytest.approx(0.2)
    assert all(p.energy.battery_discharged == 0 for p in replay[16:])


@pytest.mark.slow
def test_backup_use_below_the_reserve_is_left_out_and_never_used_by_hindsight(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    assumptions = _legacy_week(store)
    reserve = BatterySettings(**assumptions["battery"]).min_soe_kwh
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
    result = analyze_period(
        store,
        date(2026, 9, 7),
        mode="estimated",
        assumed_context=assumptions,
        allow_partial=True,
    )
    assert result["diagnostics"]["below_reserve_periods"] == 8
    assert [(e["period"], e["reason"]) for e in result["excluded_intervals"]] == [
        (i, "battery below the configured reserve (backup use)") for i in range(40, 48)
    ]
    assert (
        result["assumptions"]["battery"]["min_soc"] == assumptions["battery"]["min_soc"]
    )
    assert result["model_validation"]["minimum_energy_kwh"] >= reserve - 1e-6
    assert len(result["periods"]) == 7 * 96 - 8


@pytest.mark.slow
def test_a_disagreeing_consumption_meter_does_not_bill_only_hindsight(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    assumptions = _legacy_week(store)
    consistent = analyze_period(
        store, date(2026, 9, 7), mode="estimated", assumed_context=assumptions
    )
    for offset in range(7):
        view = store.load_day(date(2026, 9, 7) + timedelta(days=offset))
        assert view is not None
        for p in view.periods:
            p.energy.home_consumption += 0.05
        store.save_day(view)
    inflated = analyze_period(
        store, date(2026, 9, 7), mode="estimated", assumed_context=assumptions
    )
    for scenario in ("actual", "optimal", "solar_only", "grid_only"):
        assert inflated[scenario]["total_economic_cost"] == pytest.approx(
            consistent[scenario]["total_economic_cost"]
        )
    assert any("consumption meter differs" in w for w in inflated["warnings"])


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
    assert result["applied"] is True
    assert result["charge"] == pytest.approx(true_efficiency, abs=1e-6)
    assert result["discharge"] == pytest.approx(true_efficiency, abs=1e-6)
    too_little = calibrate_efficiency(periods[:2], settings)
    assert too_little["applied"] is False


@pytest.mark.slow
def test_a_month_is_one_continuous_comparison_over_its_observed_days(
    tmp_path: Path,
) -> None:
    store = DailyViewStore(tmp_path)
    assumptions = _legacy_week(store)
    result = analyze_period(
        store,
        date(2026, 9, 20),
        period="month",
        mode="estimated",
        assumed_context=assumptions,
        allow_partial=True,
        today=date(2026, 10, 5),
    )
    assert (result["start_date"], result["end_date"]) == ("2026-09-01", "2026-09-30")
    assert result["expected_periods"] == 30 * 96
    assert len(result["periods"]) == 7 * 96
    assert len(result["daily"]) == 30
    assert result["missed_savings"] is None
    assert result["available_periods"] == ["2026-09-01"]


@pytest.mark.slow
def test_huawei_replay_only_for_huawei_installations(tmp_path: Path) -> None:
    store = DailyViewStore(tmp_path)
    assumptions = _legacy_week(store)
    settings = BatterySettings(**assumptions["battery"])
    period_list = PlatformCapabilities.from_controller(
        HuaweiController(settings), settings
    )
    results = {}
    for platform in ("solis_modbus", "huawei_solar_luna2000"):
        context = {
            **historical_context(
                settings,
                HomeSettings(currency="EUR"),
                period_list,
                platform=platform,
            ),
            "assumption_source": "test",
        }
        results[platform] = analyze_period(
            store, date(2026, 9, 7), mode="estimated", assumed_context=context
        )
    assert "huawei_feasible" not in results["solis_modbus"]
    assert results["huawei_solar_luna2000"]["huawei_feasible"] is not None


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
    assert result["applied"] is True
    assert result["capacity_kwh"] == pytest.approx(true_capacity, rel=0.01)
    assert result["charge"] == pytest.approx(true_efficiency, abs=0.002)
    assert result["discharge"] == pytest.approx(true_efficiency, abs=0.002)
