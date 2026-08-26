"""Smoke tests for dashboard and system API endpoints.

Each endpoint gets two tests: 503 when unconfigured and 200 when started.
The hourly dashboard test is a regression guard for the observedIntent bug fixed
in _aggregate_quarterly_to_hourly.
"""

import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from api import _aggregate_quarterly_to_hourly, router
from api_dataclasses import APIDashboardHourlyData, APIDashboardSummary
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.daily_view_builder import DailyView
from core.bess.exceptions import SystemConfigurationError
from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)


def _make_period(period: int) -> PeriodData:
    energy = EnergyData(
        solar_production=0.5,
        home_consumption=0.5,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=15.0,
        battery_soe_end=15.0,
    )
    economic = EconomicData(
        buy_price=1.0,
        sell_price=0.5,
        hourly_cost=0.5,
        grid_only_cost=0.5,
        solar_only_cost=0.0,
        hourly_savings=0.0,
    )
    decision = DecisionData(strategic_intent="IDLE", observed_intent="IDLE")
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=datetime(
            2025, 7, 13, period // 4, (period % 4) * 15, tzinfo=time_utils.TIMEZONE
        ),
        data_source="predicted",
        economic=economic,
        decision=decision,
    )


def _make_period_with_costs(
    period: int, day: date, grid_cost: float, grid_only_cost: float
) -> PeriodData:
    energy = EnergyData(
        solar_production=0.5,
        home_consumption=0.5,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=15.0,
        battery_soe_end=15.0,
    )
    economic = EconomicData(
        buy_price=1.0,
        sell_price=0.5,
        hourly_cost=grid_cost,
        grid_cost=grid_cost,
        grid_only_cost=grid_only_cost,
        solar_only_cost=0.0,
        hourly_savings=0.0,
    )
    decision = DecisionData(strategic_intent="IDLE", observed_intent="IDLE")
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=datetime.combine(
            day,
            datetime.min.time().replace(hour=period // 4, minute=(period % 4) * 15),
            tzinfo=time_utils.TIMEZONE,
        ),
        data_source="predicted",
        economic=economic,
        decision=decision,
    )


def _wire_schedule_store(
    ctrl: MagicMock, period_data: list[PeriodData], optimization_period: int = 0
) -> None:
    """Stub schedule_store.get_latest_schedule + get_period_data_at consistently.

    api.py resolves periods by exact timestamp (get_period_data_at), not by
    positional index into optimization_result.period_data, so a bare
    MagicMock's auto-generated get_period_data_at return value (another
    MagicMock) would be treated as real data. Wire it to look up period_data
    by timestamp, matching the real ScheduleStore's behavior.
    """
    mock_schedule = MagicMock()
    mock_schedule.optimization_period = optimization_period
    mock_schedule.optimization_result.period_data = period_data
    ctrl.system.schedule_store.get_latest_schedule.return_value = mock_schedule
    by_timestamp = {p.timestamp: p for p in period_data}
    ctrl.system.schedule_store.get_period_data_at.side_effect = (
        lambda ts: by_timestamp.get(ts)
    )


def _make_daily_view() -> DailyView:
    return DailyView(
        date=date(2025, 7, 13),
        periods=[_make_period(i) for i in range(96)],
        total_savings=0.0,
        actual_count=0,
        predicted_count=96,
    )


def _make_started_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.system.is_configured = True
    ctrl.startup_complete = True

    _wire_schedule_store(ctrl, period_data=[])

    ctrl.system.get_current_daily_view.return_value = _make_daily_view()
    ctrl.system.get_settings.return_value = {"battery": MagicMock(total_capacity=30.0)}
    ctrl.system.home_settings.currency = "SEK"

    sm = ctrl.system._inverter_controller
    sm.get_strategic_intent_summary.return_value = {}
    sm.strategic_intents = ["IDLE"] * 96
    sm.get_period_settings.return_value = {
        "batt_mode": "load_first",
        "strategic_intent": "IDLE",
        "grid_charge": False,
        "discharge_rate": 100,
    }
    sm._get_intent_description.return_value = ""
    sm.get_all_tou_segments.return_value = []
    sm.tou_intervals = []

    ctrl.ha_controller.get_device_maps.return_value = ({}, {})
    ctrl.ha_controller.get_battery_soc.return_value = 75.0
    ctrl.ha_controller.get_pv_power.return_value = 0.0
    ctrl.ha_controller.get_local_load_power.return_value = 0.0
    ctrl.ha_controller.get_import_power.return_value = 0.0
    ctrl.ha_controller.get_export_power.return_value = 0.0
    ctrl.ha_controller.get_battery_charge_power.return_value = 0.0
    ctrl.ha_controller.get_battery_discharge_power.return_value = 0.0
    ctrl.ha_controller.get_net_battery_power.return_value = 0.0
    ctrl.ha_controller.test_mode = False

    ctrl.system.historical_store.get_today_periods.return_value = [None] * 96
    ctrl.system.prediction_snapshot_store.get_all_snapshots_today.return_value = []
    ctrl.system.prediction_snapshot_store.get_snapshot_at_period.return_value = None
    ctrl.system.get_runtime_failures.return_value = []
    ctrl.system.dismiss_runtime_failure.return_value = None
    ctrl.system.dismiss_all_runtime_failures.return_value = 0
    ctrl.system.get_health_recoveries.return_value = []
    ctrl.system.acknowledge_health_recoveries.return_value = 0
    ctrl.system.has_critical_sensor_failures.return_value = False
    ctrl.system.get_cached_health_results.return_value = {
        "checks": [],
        "system_mode": "normal",
    }
    ctrl.system.get_consumption_forecast_comparison.return_value = {
        "actual_hourly": [None] * 24,
        "strategies": [],
        "active_strategy": "none",
        "actual_hours_available": 0,
    }
    ctrl.settings_store.data = {}

    return ctrl


def _unconfigured_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.system.is_configured = False
    ctrl.startup_complete = True
    return ctrl


# ===========================================================================
# GET /api/dashboard
# ===========================================================================


class TestDashboard:
    def test_quarter_hourly_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/dashboard")
        assert resp.status_code == 200

    def test_hourly_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/dashboard?resolution=hourly")
        assert resp.status_code == 200

    def test_hourly_periods_have_strategic_and_observed_intent(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/dashboard?resolution=hourly")
        assert resp.status_code == 200
        periods = resp.json()["hourlyData"]
        assert len(periods) > 0
        assert "strategicIntent" in periods[0]
        assert "observedIntent" in periods[0]

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/dashboard")
        assert resp.status_code == 503

    def test_unavailable_battery_soc_sensor_returns_clear_error(self):
        """battery_soc sensor going 'unavailable' must not surface as an
        opaque TypeError from dividing None by a float."""
        ctrl = _make_started_controller()
        ctrl.ha_controller.get_battery_soc.return_value = None
        sys.modules["app"].bess_controller = ctrl

        resp = _client.get("/api/dashboard")

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "NoneType" not in detail
        assert "battery_soc" in detail.lower() or "battery soc" in detail.lower()

    def test_historical_date_returns_persisted_daily_view(self):
        ctrl = _make_started_controller()
        historical_date = date(2020, 1, 1)
        ctrl.system.daily_view_store.load_day.return_value = DailyView(
            date=historical_date,
            periods=[_make_period(i) for i in range(96)],
            total_savings=0.0,
            actual_count=96,
            predicted_count=0,
        )
        sys.modules["app"].bess_controller = ctrl

        resp = _client.get(f"/api/dashboard?date={historical_date.isoformat()}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["date"] == historical_date.isoformat()
        # No row should be flagged as "current" for a past day.
        assert body["currentPeriod"] == -1
        assert body["tomorrowData"] is None
        ctrl.system.daily_view_store.load_day.assert_called_once_with(historical_date)
        # Historical path must not touch live sensors.
        ctrl.ha_controller.get_battery_soc.assert_not_called()

    def test_historical_date_with_no_snapshot_returns_404(self):
        ctrl = _make_started_controller()
        ctrl.system.daily_view_store.load_day.return_value = None
        sys.modules["app"].bess_controller = ctrl

        resp = _client.get("/api/dashboard?date=2020-01-01")

        assert resp.status_code == 404


class TestDashboardFullHorizonCost:
    """Issue #287: when a 2-day (192-period) DP plan is active, Net Grid Cost /
    Net Savings must also expose the full-horizon total, not just today's slice.
    """

    def test_full_horizon_fields_absent_for_single_day_schedule(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/dashboard")
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["horizonDays"] == 1
        assert summary["netGridCostFullHorizon"] is None
        assert summary["netSavingsFullHorizon"] is None

    def test_full_horizon_fields_present_for_two_day_schedule(self):
        ctrl = _make_started_controller()

        today = time_utils.today()
        period_data = [
            _make_period_with_costs(i, today, grid_cost=0.0, grid_only_cost=0.5)
            for i in range(96)
        ] + [
            _make_period_with_costs(
                i - 96, today + timedelta(days=1), grid_cost=0.1, grid_only_cost=0.2
            )
            for i in range(96, 192)
        ]
        _wire_schedule_store(ctrl, period_data)

        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/dashboard")

        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["horizonDays"] == 2
        # today: 96 periods * (grid_cost=0.0, grid_only_cost=0.5) -> netGrid=0.0, gridOnly=48.0
        # tomorrow: 96 periods * (grid_cost=0.1, grid_only_cost=0.2) -> netGrid=9.6, gridOnly=19.2
        assert summary["netGridCostFullHorizon"]["value"] == pytest.approx(9.6)
        assert summary["netSavingsFullHorizon"]["value"] == pytest.approx(57.6)


class TestDashboardAvailableDates:
    def test_returns_persisted_dates_plus_today(self):
        ctrl = _make_started_controller()
        ctrl.system.daily_view_store.list_available_dates.return_value = [
            "2020-01-01",
            "2020-01-03",
        ]
        sys.modules["app"].bess_controller = ctrl

        resp = _client.get("/api/dashboard/available-dates")

        assert resp.status_code == 200
        dates = resp.json()["dates"]
        assert "2020-01-01" in dates
        assert "2020-01-03" in dates
        # The endpoint appends time_utils.today() (HA-configured timezone),
        # not the stdlib UTC date.today() — comparing against the same
        # clock the endpoint uses avoids a flaky off-by-one near the
        # UTC/local-day boundary.
        assert time_utils.today().isoformat() in dates

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/dashboard/available-dates")
        assert resp.status_code == 503


def test_aggregate_hourly_uses_observed_intent_from_all_quarters_not_just_last():
    """Regression test for #486.

    The per-quarter observedIntent captures real execution, but the old
    aggregation only forwarded the *last* quarter's observedIntent, so if
    the last quarter's observed execution disagreed with the other 3
    (all genuinely recorded as "actual"), the majority's real outcome was
    silently discarded in favor of that one quarter's value.
    """
    quarters = []
    for i in range(4):
        period = _make_period(i)
        # All 4 quarters genuinely executed and were recorded as actual;
        # 3 of them ran LOAD_SUPPORT, only the last ran BATTERY_EXPORT.
        period = replace(
            period,
            data_source="actual",
            decision=DecisionData(
                strategic_intent="BATTERY_EXPORT",
                observed_intent="BATTERY_EXPORT" if i == 3 else "LOAD_SUPPORT",
            ),
        )
        quarters.append(
            APIDashboardHourlyData.from_internal(
                period, battery_capacity=15.0, currency="SEK"
            )
        )

    [hourly] = _aggregate_quarterly_to_hourly(quarters, 15.0, "SEK")

    # dataSource stays tied to the last quarter (unchanged) — it feeds
    # actualSavingsSoFar/predictedRemainingSavings bucketing and must not
    # be widened to "any quarter actual", or a still-predicted quarter's
    # cost gets counted as realized.
    assert hourly.dataSource == "actual"
    assert hourly.observedIntent == "LOAD_SUPPORT"


def test_aggregate_hourly_data_source_stays_last_quarter_even_if_earlier_quarters_are_actual():
    """dataSource must not flip to "actual" just because SOME quarter is —
    only the last quarter's value counts, matching the pre-existing contract
    that api_dataclasses.py's actual/predicted savings split relies on.
    """
    quarters = []
    for i in range(4):
        period = _make_period(i)
        period = replace(
            period,
            data_source="actual" if i < 3 else "predicted",
            decision=DecisionData(
                strategic_intent="LOAD_SUPPORT",
                observed_intent="LOAD_SUPPORT" if i < 3 else None,
            ),
        )
        quarters.append(
            APIDashboardHourlyData.from_internal(
                period, battery_capacity=15.0, currency="SEK"
            )
        )

    [hourly] = _aggregate_quarterly_to_hourly(quarters, 15.0, "SEK")

    assert hourly.dataSource == "predicted"


def test_aggregate_hourly_curtailed_not_filtered_by_dominant_intent():
    """Curtailment (#501) is intent-independent: a curtailed quarter can
    classify as SOLAR_STORAGE (battery charging at rate limit, surplus above
    it curtailed). An hour whose curtailed quarters lose the dominant-intent
    vote must still report curtailed=True.
    """
    quarters = []
    for i in range(4):
        period = _make_period(i)
        # 2 GRID_CHARGING + 2 curtailed SOLAR_STORAGE quarters: the 2-2 tie
        # resolves to GRID_CHARGING on priority, so any intent-filtered
        # aggregation would look only at the un-curtailed quarters.
        period = replace(
            period,
            decision=DecisionData(
                strategic_intent="GRID_CHARGING" if i < 2 else "SOLAR_STORAGE",
                curtailed=i >= 2,
            ),
        )
        quarters.append(
            APIDashboardHourlyData.from_internal(
                period, battery_capacity=15.0, currency="SEK"
            )
        )

    [hourly] = _aggregate_quarterly_to_hourly(quarters, 15.0, "SEK")

    assert hourly.strategicIntent == "GRID_CHARGING"
    assert hourly.curtailed is True


def test_net_grid_cost_excludes_battery_wear():
    def _hour(grid_cost, cycle_cost):
        return APIDashboardHourlyData.from_internal(
            PeriodData(
                period=0,
                energy=EnergyData(
                    solar_production=0.0,
                    home_consumption=1.0,
                    battery_charged=0.0,
                    battery_discharged=0.0,
                    grid_imported=1.0,
                    grid_exported=0.0,
                    battery_soe_start=5.0,
                    battery_soe_end=5.0,
                ),
                economic=EconomicData(
                    buy_price=1.0,
                    sell_price=1.0,
                    grid_cost=grid_cost,
                    battery_cycle_cost=cycle_cost,
                    hourly_cost=grid_cost + cycle_cost,
                ),
                decision=DecisionData(strategic_intent="IDLE"),
            ),
            battery_capacity=10.0,
            currency="EUR",
        )

    hours = [_hour(1.0, 0.5), _hour(2.0, 0.5)]
    net_grid_cost = sum(h.gridCost.value for h in hours)

    assert net_grid_cost == 3.0  # 1.0 + 2.0, wear excluded


def test_from_totals_wires_net_grid_cost_from_costs_dict():
    """APIDashboardSummary.from_totals must source netGridCost from
    costs["netGrid"], not any other cost key.

    Regression guard: a copy-paste bug (e.g. wiring netGridCost from
    costs["optimized"]) would silently make it equal the wear-inclusive
    bundled cost instead of the wear-exclusive net grid cost. Distinct
    values for each cost key ensure such a mistake produces a wrong
    number here rather than passing unnoticed.
    """
    totals = {
        "totalSolarProduction": 0.0,
        "totalHomeConsumption": 0.0,
        "totalBatteryCharged": 0.0,
        "totalBatteryDischarged": 0.0,
        "totalGridImport": 0.0,
        "totalGridExport": 0.0,
        "totalSolarToHome": 0.0,
        "totalSolarToBattery": 0.0,
        "totalSolarToGrid": 0.0,
        "totalGridToHome": 0.0,
        "totalGridToBattery": 0.0,
        "totalBatteryToHome": 0.0,
        "totalBatteryToGrid": 0.0,
    }
    costs = {"gridOnly": 10.0, "solarOnly": 8.0, "optimized": 5.0, "netGrid": 3.0}

    summary = APIDashboardSummary.from_totals(
        totals, costs, battery_capacity=10.0, currency="EUR"
    )

    assert summary.netGridCost.value == 3.0
    # Confirm netGridCost isn't accidentally aliased to the wear-inclusive
    # optimized cost, and totalSavings math is untouched by the new field.
    assert summary.optimizedCost.value == 5.0
    assert summary.totalSavings.value == 5.0  # gridOnly(10) - optimized(5)


def test_from_totals_computes_net_savings_as_grid_only_minus_net_grid():
    from api_dataclasses import APIDashboardSummary

    totals = {
        "totalSolarProduction": 0.0,
        "totalHomeConsumption": 0.0,
        "totalBatteryCharged": 0.0,
        "totalBatteryDischarged": 0.0,
        "totalGridImport": 0.0,
        "totalGridExport": 0.0,
        "totalSolarToHome": 0.0,
        "totalSolarToBattery": 0.0,
        "totalSolarToGrid": 0.0,
        "totalGridToHome": 0.0,
        "totalGridToBattery": 0.0,
        "totalBatteryToHome": 0.0,
        "totalBatteryToGrid": 0.0,
    }
    costs = {"gridOnly": 10.0, "solarOnly": 8.0, "optimized": 5.0, "netGrid": 3.0}

    summary = APIDashboardSummary.from_totals(
        totals, costs, battery_capacity=10.0, currency="EUR"
    )

    assert summary.netSavings.value == 7.0  # gridOnly(10) - netGrid(3)
    # Unchanged: still wear-inclusive, still independent of the new field
    assert summary.totalSavings.value == 5.0  # gridOnly(10) - optimized(5)


# ===========================================================================
# GET /api/growatt/tou_settings
# ===========================================================================


class TestTouSettings:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/growatt/tou_settings")
        assert resp.status_code == 200

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/growatt/tou_settings")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/growatt/strategic_intents
# ===========================================================================


class TestStrategicIntents:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/growatt/strategic_intents")
        assert resp.status_code == 200

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/growatt/strategic_intents")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/system-health
# ===========================================================================


class TestSystemHealth:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/system-health")
        assert resp.status_code == 200

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/system-health")
        assert resp.status_code == 503


# ===========================================================================
# POST /api/system-health/recheck
# ===========================================================================


class TestSystemHealthRecheck:
    def test_returns_200_and_calls_refresh_health_check(self):
        ctrl = _make_started_controller()
        ctrl.system.refresh_health_check.return_value = {
            "checks": [],
            "system_mode": "normal",
        }
        sys.modules["app"].bess_controller = ctrl

        resp = _client.post("/api/system-health/recheck")

        assert resp.status_code == 200
        ctrl.system.refresh_health_check.assert_called_once()

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.post("/api/system-health/recheck")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/dashboard-health-summary
# ===========================================================================


class TestDashboardHealthSummary:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/dashboard-health-summary")
        assert resp.status_code == 200

    def test_response_contains_has_critical_errors(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/dashboard-health-summary")
        assert "hasCriticalErrors" in resp.json()

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/dashboard-health-summary")
        assert resp.status_code == 503

    def test_critical_issue_names_the_failing_component(self):
        ctrl = _make_started_controller()
        ctrl.system.has_critical_sensor_failures.return_value = True
        ctrl.system.get_critical_sensor_failures.return_value = ["Battery Control"]
        ctrl.system.get_cached_health_results.return_value = {
            "checks": [
                {
                    "name": "Battery Control",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Battery Charging Power Rate",
                            "entity_id": "number.growatt_battery_charging_power_rate",
                            "status": "WARNING",
                            "error": "Entity state is 'unavailable'",
                        }
                    ],
                }
            ],
            "system_mode": "degraded",
        }
        sys.modules["app"].bess_controller = ctrl

        resp = _client.get("/api/dashboard-health-summary")

        issue = resp.json()["criticalIssues"][0]
        # Without a resolvable device the component name is the group key,
        # and detail names the component rather than its individual sensors.
        assert issue["detail"] == "Battery Control"

    def test_critical_issues_grouped_by_device(self) -> None:
        """A single-device outage (three components, two devices) shows one
        banner line per device, not one per component."""
        ctrl = _make_started_controller()
        ctrl.system.has_critical_sensor_failures.return_value = True
        ctrl.system.get_critical_sensor_failures.return_value = [
            "Battery Control",
            "Battery Monitoring",
            "Energy Monitoring",
        ]
        ctrl.system.get_cached_health_results.return_value = {
            "checks": [
                {
                    "name": "Battery Control",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Power Setpoint",
                            "entity_id": "sensor.device_a_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
                {
                    "name": "Battery Monitoring",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Battery SOC",
                            "entity_id": "sensor.device_b_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
                {
                    "name": "Energy Monitoring",
                    "status": "ERROR",
                    "required": True,
                    "checks": [
                        {
                            "name": "Energy Today",
                            "entity_id": "sensor.device_c_sensor",
                            "status": "ERROR",
                        }
                    ],
                },
            ],
            "system_mode": "degraded",
        }
        ctrl.ha_controller.get_device_maps.return_value = (
            {
                "sensor.device_a_sensor": "device-a",
                "sensor.device_b_sensor": "device-a",
                "sensor.device_c_sensor": "device-b",
            },
            {"device-a": "Power Inverter", "device-b": "Energy Meter"},
        )
        # Direct assignment matches the rest of this file; the mypy
        # attr-defined is pre-existing ratchet debt, so suppress it here
        # rather than add another occurrence.
        sys.modules["app"].bess_controller = ctrl  # type: ignore[attr-defined]

        resp = _client.get("/api/dashboard-health-summary")

        issues = resp.json()["criticalIssues"]
        assert len(issues) == 2
        assert issues[0]["component"] == "Power Inverter"
        assert issues[0]["detail"] == "Battery Control, Battery Monitoring"
        assert issues[1]["component"] == "Energy Meter"
        assert issues[1]["detail"] == "Energy Monitoring"
        assert resp.json()["totalCriticalIssues"] == 2

    def test_critical_issues_group_by_component_when_registry_unavailable(
        self,
    ) -> None:
        """A registry query failure must not drop the critical banner — it
        degrades to component-name grouping, one line per failing component."""
        ctrl = _make_started_controller()
        ctrl.system.has_critical_sensor_failures.return_value = True
        ctrl.system.get_critical_sensor_failures.return_value = [
            "Battery Control",
            "Battery Monitoring",
        ]
        ctrl.system.get_cached_health_results.return_value = {
            "checks": [
                {
                    "name": "Battery Control",
                    "status": "ERROR",
                    "required": True,
                    "checks": [],
                },
                {
                    "name": "Battery Monitoring",
                    "status": "ERROR",
                    "required": True,
                    "checks": [],
                },
            ]
        }
        ctrl.ha_controller.get_device_maps.side_effect = SystemConfigurationError(
            "registry down"
        )
        sys.modules["app"].bess_controller = ctrl  # type: ignore[attr-defined]

        resp = _client.get("/api/dashboard-health-summary")

        issues = resp.json()["criticalIssues"]
        assert len(issues) == 2
        assert {i["component"] for i in issues} == {
            "Battery Control",
            "Battery Monitoring",
        }
        assert resp.json()["totalCriticalIssues"] == 2


# ===========================================================================
# GET /api/historical-data-status
# ===========================================================================


class TestHistoricalDataStatus:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/historical-data-status")
        assert resp.status_code == 200

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/historical-data-status")
        assert resp.status_code == 503

    def test_dismiss_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.post("/api/historical-data-status/dismiss")
        assert resp.status_code == 200

    def test_dismiss_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.post("/api/historical-data-status/dismiss")
        assert resp.status_code == 503

    def test_dismiss_persists_across_requests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dismissal for today's missing hours suppresses the banner on
        the next GET, matching the runtime-failures/health-recoveries
        dismiss-then-refetch pattern the frontend relies on."""
        # Freeze the clock to a non-boundary hour. The endpoint only expects
        # periods before the current hour (current_period = hour * 4), so at
        # 00:xx current_period == 0 and is_incomplete is False — the dismissal
        # can never show as active, and the test would deterministically fail
        # for one wall-clock hour each day.

        def _fixed_now() -> datetime:
            return datetime(2026, 1, 15, 14, 30, tzinfo=time_utils.TIMEZONE)

        monkeypatch.setattr(time_utils, "now", _fixed_now)
        ctrl = _make_started_controller()
        system = BatterySystemManager.__new__(BatterySystemManager)
        system._dismissed_historical_warning_signature = None
        ctrl.system.is_historical_data_warning_dismissed = (
            system.is_historical_data_warning_dismissed
        )
        ctrl.system.dismiss_historical_data_warning = (
            system.dismiss_historical_data_warning
        )
        sys.modules["app"].bess_controller = ctrl

        before = _client.get("/api/historical-data-status").json()
        assert before["dismissed"] is False

        _client.post("/api/historical-data-status/dismiss")

        after = _client.get("/api/historical-data-status").json()
        assert after["dismissed"] is True


# ===========================================================================
# GET /api/prediction-analysis/snapshots
# ===========================================================================


class TestPredictionSnapshots:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/prediction-analysis/snapshots")
        assert resp.status_code == 200

    def test_response_contains_count(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/prediction-analysis/snapshots")
        assert "count" in resp.json()

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/prediction-analysis/snapshots")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/prediction-analysis/timeline
# ===========================================================================


class TestPredictionTimeline:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/prediction-analysis/timeline")
        assert resp.status_code == 200

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/prediction-analysis/timeline")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/prediction-analysis/comparison
# ===========================================================================


class TestPredictionComparison:
    def test_missing_snapshot_returns_404(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/prediction-analysis/comparison?snapshot_period=0")
        assert resp.status_code == 404

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/prediction-analysis/comparison?snapshot_period=0")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/prediction-analysis/snapshot-comparison
# ===========================================================================


class TestSnapshotComparison:
    def test_missing_snapshot_returns_404(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get(
            "/api/prediction-analysis/snapshot-comparison?period_a=0&period_b=10"
        )
        assert resp.status_code == 404

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get(
            "/api/prediction-analysis/snapshot-comparison?period_a=0&period_b=10"
        )
        assert resp.status_code == 503

    def test_handles_vpp_schedule_without_batt_mode(self):
        """Task 6-8 controllers may emit growatt_schedule intervals that carry
        vpp_power_pct/vpp_remote_control instead of batt_mode. The endpoint
        must not KeyError on interval["batt_mode"] for those intervals.
        """
        ctrl = _make_started_controller()

        vpp_interval = {
            "start_time": "00:00",
            "end_time": "01:00",
            "vpp_power_pct": 0,
            "vpp_remote_control": True,
        }

        def make_snapshot(period: int):
            snapshot = MagicMock()
            snapshot.snapshot_timestamp = datetime(
                2025, 7, 13, 0, 0, tzinfo=time_utils.TIMEZONE
            )
            snapshot.daily_view = _make_daily_view()
            snapshot.growatt_schedule = [vpp_interval]
            return snapshot

        ctrl.system.prediction_snapshot_store.get_snapshot_at_period.side_effect = (
            lambda period: make_snapshot(period)
        )

        sys.modules["app"].bess_controller = ctrl
        resp = _client.get(
            "/api/prediction-analysis/snapshot-comparison?period_a=0&period_b=10"
        )
        assert resp.status_code == 200  # must not 500/KeyError
        schedule_a = resp.json()["growattScheduleA"]
        assert schedule_a
        assert "vppPowerPct" in schedule_a[0] or "battMode" in schedule_a[0]
        assert "battMode" not in schedule_a[0]


# ===========================================================================
# GET /api/consumption-forecast-comparison
# ===========================================================================


class TestConsumptionForecastComparison:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/consumption-forecast-comparison")
        assert resp.status_code == 200

    def test_response_contains_active_strategy(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/consumption-forecast-comparison")
        assert "activeStrategy" in resp.json()


# ===========================================================================
# GET /api/export-debug-data
# ===========================================================================


class TestExportDebugData:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/export-debug-data")
        assert resp.status_code == 200


# ===========================================================================
# GET /api/runtime-failures
# POST /api/runtime-failures/{failure_id}/dismiss
# POST /api/runtime-failures/dismiss-all
# ===========================================================================


class TestRuntimeFailures:
    def test_get_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/runtime-failures")
        assert resp.status_code == 200

    def test_get_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/runtime-failures")
        assert resp.status_code == 503

    def test_dismiss_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.post("/api/runtime-failures/abc123/dismiss")
        assert resp.status_code == 200

    def test_dismiss_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.post("/api/runtime-failures/abc123/dismiss")
        assert resp.status_code == 503

    def test_dismiss_all_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.post("/api/runtime-failures/dismiss-all")
        assert resp.status_code == 200

    def test_dismiss_all_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.post("/api/runtime-failures/dismiss-all")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/health-recoveries
# POST /api/health-recoveries/acknowledge
# ===========================================================================


class TestHealthRecoveries:
    def test_get_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/health-recoveries")
        assert resp.status_code == 200

    def test_get_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/health-recoveries")
        assert resp.status_code == 503

    def test_acknowledge_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.post("/api/health-recoveries/acknowledge")
        assert resp.status_code == 200

    def test_acknowledge_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.post("/api/health-recoveries/acknowledge")
        assert resp.status_code == 503


# ===========================================================================
# APIDashboardHourlyData unit tests
# ===========================================================================


def test_hourly_data_exposes_grid_cost_and_battery_cycle_cost():
    hourly = PeriodData(
        period=0,
        energy=EnergyData(
            solar_production=1.0,
            home_consumption=1.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=1.0,
            grid_exported=0.0,
            battery_soe_start=5.0,
            battery_soe_end=5.0,
        ),
        economic=EconomicData(
            buy_price=2.0,
            sell_price=1.0,
            grid_cost=2.0,
            battery_cycle_cost=0.1,
            hourly_cost=2.1,
        ),
        decision=DecisionData(strategic_intent="IDLE"),
    )

    api_hourly = APIDashboardHourlyData.from_internal(
        hourly, battery_capacity=10.0, currency="EUR"
    )

    assert api_hourly.gridCost.value == 2.0
    assert api_hourly.batteryCycleCost.value == 0.1


def test_hourly_data_exposes_wear_free_net_and_battery_savings():
    hourly = PeriodData(
        period=0,
        energy=EnergyData(
            solar_production=1.0,
            home_consumption=1.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=1.0,
            grid_exported=0.0,
            battery_soe_start=5.0,
            battery_soe_end=5.0,
        ),
        economic=EconomicData(
            buy_price=2.0,
            sell_price=1.0,
            grid_cost=2.0,
            grid_only_cost=10.0,
            solar_only_cost=6.0,
            battery_cycle_cost=0.1,
            hourly_cost=2.1,
        ),
        decision=DecisionData(strategic_intent="IDLE"),
    )

    api_hourly = APIDashboardHourlyData.from_internal(
        hourly, battery_capacity=10.0, currency="EUR"
    )

    # netSavings = gridOnlyCost - gridCost = 10.0 - 2.0
    assert api_hourly.netSavings.value == 8.0
    # batterySavings = solarOnlyCost - gridCost = 6.0 - 2.0 = 4.0 (wear-free:
    # subtracts grid_cost, NOT hourly_cost, which folds in
    # battery_cycle_cost=0.1 — if wear were included this would instead be
    # solar_only_cost - hourly_cost = 6.0 - 2.1 = 3.9).
    assert api_hourly.batterySavings.value == 4.0
