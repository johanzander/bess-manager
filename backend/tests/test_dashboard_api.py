"""Smoke tests for dashboard and system API endpoints.

Each endpoint gets two tests: 503 when unconfigured and 200 when started.
The hourly dashboard test is a regression guard for the observedIntent bug fixed
in _aggregate_quarterly_to_hourly.
"""

import sys
from datetime import date, datetime
from unittest.mock import MagicMock

from api import router
from api_dataclasses import APIDashboardHourlyData, APIDashboardSummary
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.daily_view_builder import DailyView
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
        timestamp=datetime(2025, 7, 13, period // 4, (period % 4) * 15),
        data_source="predicted",
        economic=economic,
        decision=decision,
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

    mock_schedule = MagicMock()
    mock_schedule.optimization_period = 0
    mock_schedule.optimization_result.period_data = []
    ctrl.system.schedule_store.get_latest_schedule.return_value = mock_schedule

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
# GET /api/decision-intelligence
# ===========================================================================


class TestDecisionIntelligence:
    def test_returns_200(self):
        sys.modules["app"].bess_controller = _make_started_controller()
        resp = _client.get("/api/decision-intelligence")
        assert resp.status_code == 200

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()
        resp = _client.get("/api/decision-intelligence")
        assert resp.status_code == 503


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

    def test_critical_issue_names_the_failing_sensor(self):
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
        assert issue["detail"] == (
            "Battery Charging Power Rate (number.growatt_battery_charging_power_rate)"
        )


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
