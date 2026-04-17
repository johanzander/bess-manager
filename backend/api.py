"""
API endpoints for battery and electricity settings, dashboard data, and decision intelligence.

"""

import dataclasses
import threading
from datetime import datetime, timedelta

from api_conversion import convert_keys_to_camel_case, convert_keys_to_snake_case
from api_dataclasses import (
    _ENTITY_ID_RE,
    APIDashboardHourlyData,
    APIDashboardResponse,
    APIPredictionSnapshot,
    APISetupCompletePayload,
    APISnapshotComparison,
    create_formatted_value,
)
from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, field_validator

from core.bess import time_utils
from core.bess.health_check import run_system_health_checks
from core.bess.settings import BatterySettings as _BatterySettings
from core.bess.time_utils import get_period_count

router = APIRouter()


def _deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge *updates* into *base*, preserving nested dict values.

    Nested dicts are merged key-by-key so that a partial update (e.g. only
    ``config_entry_id``) cannot erase sibling keys that already exist in the
    stored section.  All other value types are overwritten as normal.
    """
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _refresh_health(bess_controller) -> None:
    """Re-run the health check so the dashboard banner reflects the latest state.

    Called after any settings mutation that could affect sensor or component
    health (home, sensors, energy-provider, inverter, battery, electricity).
    Failures are non-fatal — the banner will self-correct on the next poll.
    """
    try:
        bess_controller.system._run_health_check()
    except Exception as exc:
        logger.warning("Could not refresh health state after settings update: %s", exc)


# ---------------------------------------------------------------------------
# Unified settings endpoints
# ---------------------------------------------------------------------------

# Maps camelCase section names (from the API) to snake_case store keys.
_SECTION_MAP: dict[str, str] = {
    "battery": "battery",
    "home": "home",
    "electricityPrice": "electricity_price",
    "energyProvider": "energy_provider",
    "growatt": "growatt",
    "sensors": "sensors",
}

# Derived from the BatterySettings dataclass — fields with init=True are the
# writable attributes; init=False fields (min_soe_kwh, max_soe_kwh,
# reserved_capacity) are computed and must not be sent to update_settings().
# temperature_derating is a nested dict handled separately below.
_BATTERY_MODEL_ATTRS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(_BatterySettings) if f.init
)


@router.get("/api/settings")
async def get_settings():
    """Return all settings enriched with computed battery fields.

    Sensor keys are system identifiers (snake_case) and are intentionally
    not converted to camelCase — all other sections use camelCase field names.
    """
    from copy import deepcopy

    from app import bess_controller

    try:
        data = deepcopy(bess_controller.settings_store.data)

        # Enrich battery section with computed kWh fields derived from SOC limits
        battery = data.get("battery", {})
        total = battery.get("total_capacity", 0.0)
        battery["min_soe_kwh"] = total * battery.get("min_soc", 0.0) / 100.0
        battery["max_soe_kwh"] = total * battery.get("max_soc", 0.0) / 100.0
        battery["reserved_capacity"] = battery["min_soe_kwh"]
        data["battery"] = battery

        # Sensor keys are system identifiers — return the live merged view from
        # ha_controller (which includes sensors loaded from options.json at startup
        # that may not have been re-persisted to the store).
        data.pop("sensors", None)
        result = convert_keys_to_camel_case(data)
        result["sensors"] = dict(bess_controller.ha_controller.sensors)
        return result
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/api/settings")
async def patch_settings(updates: dict):
    """Partial-update settings — only provided sections are touched.

    Each top-level key must be a known section name (camelCase).  Field values
    within each section are converted from camelCase to snake_case before being
    merged into the persistent store and applied to the running system.
    """
    from app import bess_controller

    try:
        for camel_key, section_data in updates.items():
            store_key = _SECTION_MAP.get(camel_key)
            if store_key is None:
                raise HTTPException(
                    status_code=400, detail=f"Unknown settings section: {camel_key!r}"
                )

            # Sensor keys are system identifiers — skip camelCase conversion
            if store_key == "sensors":
                snake_data = section_data
            else:
                snake_data = convert_keys_to_snake_case(section_data)

            # Validate before persisting — sensors need entity ID format checked first.
            if store_key == "sensors":
                for value in snake_data.values():
                    if value and not _ENTITY_ID_RE.match(value):
                        raise HTTPException(
                            status_code=422,
                            detail=f"Invalid entity ID format: {value!r}",
                        )

            # Read-modify-write: merge into the existing section.
            # Use deep merge so that partial updates to nested sub-dicts (e.g.
            # nordpool_official.config_entry_id) do not erase sibling keys.
            section = bess_controller.settings_store.get_section(store_key)
            section = _deep_merge(section, snake_data)
            bess_controller.settings_store.save_section(store_key, section)

            # Apply in-memory updates for sections that drive live behaviour
            if store_key == "battery":
                in_mem = {k: v for k, v in section.items() if k in _BATTERY_MODEL_ATTRS}
                if in_mem:
                    bess_controller.system.update_settings({"battery": in_mem})
                td = section.get("temperature_derating")
                if isinstance(td, dict):
                    obj = bess_controller.system.temperature_derating
                    if "enabled" in td:
                        obj.enabled = td["enabled"]
                    if "weather_entity" in td:
                        obj.weather_entity = td["weather_entity"]

            elif store_key == "home":
                bess_controller.system.update_settings({"home": section})

            elif store_key == "electricity_price":
                # PriceSettings attribute names match the store field names directly
                bess_controller.system.update_settings({"price": section})

            elif store_key == "energy_provider":
                # Apply the new provider live so a restart is not required when
                # switching between nordpool, nordpool_official, and octopus.
                bess_controller.system.update_settings({"energy_provider": section})

            elif store_key == "growatt":
                if "device_id" in section:
                    bess_controller.ha_controller.growatt_device_id = section["device_id"]

            elif store_key == "sensors":
                bess_controller.ha_controller.sensors.update(
                    {k: v for k, v in section.items() if v}
                )

        _refresh_health(bess_controller)
        return await get_settings()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


def _aggregate_quarterly_to_hourly(
    quarterly_periods: list[APIDashboardHourlyData],
    _battery_capacity: float,
    currency: str,
) -> list[APIDashboardHourlyData]:
    """Aggregate quarterly (15-min) periods into hourly periods.

    Args:
        quarterly_periods: List of quarterly period data (96 periods for normal day)
        battery_capacity: Battery capacity in kWh
        currency: Currency code

    Returns:
        List of hourly aggregated data (24 hours for normal day)
    """
    if not quarterly_periods:
        return []

    # Priority order for tie-breaking: prioritize action over inaction
    intent_priority = {
        "GRID_CHARGING": 5,
        "EXPORT_ARBITRAGE": 4,
        "LOAD_SUPPORT": 3,
        "SOLAR_STORAGE": 2,
        "IDLE": 1,
    }

    hourly_periods = []
    num_hours = (len(quarterly_periods) + 3) // 4  # Round up to handle DST

    for hour in range(num_hours):
        # Get the 4 quarterly periods for this hour
        start_idx = hour * 4
        end_idx = min(start_idx + 4, len(quarterly_periods))
        quarter_periods = quarterly_periods[start_idx:end_idx]

        if not quarter_periods:
            continue

        # Use the last period's values for state-based fields
        last_period = quarter_periods[-1]

        # Determine dominant strategic intent (most common in the 4 periods)
        # If there's a tie, prioritize action over inaction
        period_intents = [p.strategicIntent for p in quarter_periods]
        intent_counts = {}
        for intent_item in period_intents:
            intent_counts[intent_item] = intent_counts.get(intent_item, 0) + 1

        # Find max count, then use priority as tie-breaker
        max_count = max(intent_counts.values())
        candidates = [i for i, c in intent_counts.items() if c == max_count]
        dominant_intent = max(candidates, key=lambda x: intent_priority.get(x, 0))

        # Sum energy values across the 4 quarters
        hourly_period = APIDashboardHourlyData(
            period=hour,
            dataSource=last_period.dataSource,  # Use last period's data source
            timestamp=last_period.timestamp,
            # Sum energy flows
            solarProduction=create_formatted_value(
                sum(p.solarProduction.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            homeConsumption=create_formatted_value(
                sum(p.homeConsumption.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            gridImported=create_formatted_value(
                sum(p.gridImported.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            gridExported=create_formatted_value(
                sum(p.gridExported.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            batteryCharged=create_formatted_value(
                sum(p.batteryCharged.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            batteryDischarged=create_formatted_value(
                sum(p.batteryDischarged.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            batteryAction=create_formatted_value(
                sum(p.batteryAction.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            # Average prices
            buyPrice=create_formatted_value(
                sum(p.buyPrice.value for p in quarter_periods) / len(quarter_periods),
                "price",
                currency,
            ),
            sellPrice=create_formatted_value(
                sum(p.sellPrice.value for p in quarter_periods) / len(quarter_periods),
                "price",
                currency,
            ),
            # Use last period's SOC and SOE
            batterySocStart=last_period.batterySocStart,
            batterySocEnd=last_period.batterySocEnd,
            batterySoeStart=last_period.batterySoeStart,
            batterySoeEnd=last_period.batterySoeEnd,
            # Sum detailed energy flows
            solarToHome=create_formatted_value(
                sum(p.solarToHome.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            solarToBattery=create_formatted_value(
                sum(p.solarToBattery.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            solarToGrid=create_formatted_value(
                sum(p.solarToGrid.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            gridToHome=create_formatted_value(
                sum(p.gridToHome.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            gridToBattery=create_formatted_value(
                sum(p.gridToBattery.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            batteryToHome=create_formatted_value(
                sum(p.batteryToHome.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            batteryToGrid=create_formatted_value(
                sum(p.batteryToGrid.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            # Solar-only scenario fields
            gridImportNeeded=create_formatted_value(
                sum(p.gridImportNeeded.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            # Sum costs and savings
            hourlyCost=create_formatted_value(
                sum(p.hourlyCost.value for p in quarter_periods), "currency", currency
            ),
            hourlySavings=create_formatted_value(
                sum(p.hourlySavings.value for p in quarter_periods),
                "currency",
                currency,
            ),
            gridOnlyCost=create_formatted_value(
                sum(p.gridOnlyCost.value for p in quarter_periods), "currency", currency
            ),
            solarOnlyCost=create_formatted_value(
                sum(p.solarOnlyCost.value for p in quarter_periods),
                "currency",
                currency,
            ),
            solarExcess=create_formatted_value(
                sum(p.solarExcess.value for p in quarter_periods),
                "energy_kwh_only",
                currency,
            ),
            solarSavings=create_formatted_value(
                sum(p.solarSavings.value for p in quarter_periods), "currency", currency
            ),
            # Use dominant strategic intent with tie-breaking (same logic as Growatt schedule)
            strategicIntent=dominant_intent,
            directSolar=sum(p.directSolar for p in quarter_periods),
        )

        hourly_periods.append(hourly_period)

    return hourly_periods


@router.get("/api/dashboard")
async def get_dashboard_data(
    resolution: str = Query("quarter-hourly", pattern="^(hourly|quarter-hourly)$"),
):
    """Unified dashboard endpoint using dataclass-based implementation for type safety.

    Args:
        resolution: Data resolution - 'hourly' (24 periods) or 'quarter-hourly' (96 periods)
    """
    from app import bess_controller

    try:
        logger.debug(f"Starting dashboard data retrieval with resolution={resolution}")

        # Guard: if no schedule exists yet the system is still initializing.
        if not bess_controller.system.schedule_store.get_latest_schedule():
            logger.info("Dashboard requested before schedule is ready — returning initializing state")
            return {"error": "initializing", "message": "System is initializing. The optimization schedule will be ready shortly."}

        # Get daily view data (always quarterly internally)
        daily_view = bess_controller.system.get_current_daily_view()
        logger.debug(f"Daily view retrieved with {len(daily_view.periods)} periods")

        # Get system components
        controller = bess_controller.ha_controller
        settings = bess_controller.system.get_settings()
        battery_capacity = settings["battery"].total_capacity
        currency = bess_controller.system.home_settings.currency

        # Convert periods to API format (works for both hourly and quarterly)
        hourly_dataclass_instances = [
            APIDashboardHourlyData.from_internal(
                period_data, battery_capacity, currency
            )
            for period_data in daily_view.periods
        ]

        # Convert to hourly if requested
        if resolution == "hourly":
            logger.debug(
                f"Converting {len(hourly_dataclass_instances)} quarterly periods to hourly"
            )
            hourly_dataclass_instances = _aggregate_quarterly_to_hourly(
                hourly_dataclass_instances, battery_capacity, currency
            )
            logger.debug(
                f"Aggregated to {len(hourly_dataclass_instances)} hourly periods"
            )

        # Extract tomorrow's optimization data from ScheduleStore
        tomorrow_data: list[APIDashboardHourlyData] | None = None
        try:
            stored_schedule = (
                bess_controller.system.schedule_store.get_latest_schedule()
            )
            if stored_schedule:
                opt_result = stored_schedule.optimization_result
                opt_period = stored_schedule.optimization_period
                today_period_count = get_period_count(time_utils.today())
                tomorrow_period_count = get_period_count(
                    time_utils.today() + timedelta(days=1)
                )
                tomorrow_periods = []
                for period_idx in range(
                    today_period_count,
                    today_period_count + tomorrow_period_count,
                ):
                    data_idx = period_idx - opt_period
                    if 0 <= data_idx < len(opt_result.period_data):
                        tomorrow_periods.append(opt_result.period_data[data_idx])
                if tomorrow_periods:
                    tomorrow_data = [
                        APIDashboardHourlyData.from_internal(
                            p, battery_capacity, currency
                        )
                        for p in tomorrow_periods
                    ]
                    if resolution == "hourly":
                        tomorrow_data = _aggregate_quarterly_to_hourly(
                            tomorrow_data, battery_capacity, currency
                        )
                    else:
                        # Tomorrow's periods are indexed relative to the start of the
                        # optimization window (e.g. 96..191 for a 96-period day).
                        # The frontend maps period index to wall-clock time, so period 0
                        # must represent 00:00 of the displayed day.
                        tomorrow_data = [
                            dataclasses.replace(p, period=i)
                            for i, p in enumerate(tomorrow_data)
                        ]
        except (AttributeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to get tomorrow's optimization data: {e}")
            tomorrow_data = None

        # Calculate basic totals from dataclass fields directly (no dict access)
        basic_totals = {
            "totalSolarProduction": sum(
                h.solarProduction.value for h in hourly_dataclass_instances
            ),
            "totalHomeConsumption": sum(
                h.homeConsumption.value for h in hourly_dataclass_instances
            ),
            "totalBatteryCharged": sum(
                h.batteryCharged.value for h in hourly_dataclass_instances
            ),
            "totalBatteryDischarged": sum(
                h.batteryDischarged.value for h in hourly_dataclass_instances
            ),
            "totalGridImport": sum(
                h.gridImported.value for h in hourly_dataclass_instances
            ),
            "totalGridExport": sum(
                h.gridExported.value for h in hourly_dataclass_instances
            ),
            "avgBuyPrice": (
                sum(h.buyPrice.value for h in hourly_dataclass_instances)
                / len(hourly_dataclass_instances)
                if hourly_dataclass_instances
                else 0
            ),
        }

        # Calculate costs from dataclass fields directly - using ACTUAL backend calculations
        total_optimized_cost = sum(
            h.hourlyCost.value for h in hourly_dataclass_instances
        )
        total_grid_only_cost = sum(
            h.gridOnlyCost.value for h in hourly_dataclass_instances
        )
        total_solar_only_cost = sum(
            h.solarOnlyCost.value for h in hourly_dataclass_instances
        )

        costs = {
            "gridOnly": total_grid_only_cost,
            "solarOnly": total_solar_only_cost,
            "optimized": total_optimized_cost,
        }

        battery_soc: float = controller.get_battery_soc()

        # Strategic intent summary from actual schedule data
        try:
            schedule_manager = bess_controller.system._schedule_manager
            strategic_summary_data = schedule_manager.get_strategic_intent_summary()
            # Convert to count format expected by frontend
            strategic_summary = {
                intent: data.get("count", 0)
                for intent, data in strategic_summary_data.items()
            }
        except Exception as e:
            logger.error(f"Failed to get strategic intent summary: {e}")
            raise ValueError(
                f"Strategic intent summary is required but failed to load: {e}"
            ) from e

        # Create the dataclass response using pre-created hourly instances
        response = APIDashboardResponse.from_dashboard_data(
            daily_view=daily_view,
            controller=controller,
            totals=basic_totals,
            costs=costs,
            strategic_summary=strategic_summary,
            battery_soc=battery_soc,
            battery_capacity=battery_capacity,
            currency=currency,
            hourly_data_instances=hourly_dataclass_instances,
            resolution=resolution,
            tomorrow_data=tomorrow_data,
        )

        logger.debug("Dashboard response created successfully using dataclasses")

        # Return dataclass directly - already has camelCase fields
        return response.__dict__

    except Exception as e:
        logger.error(f"Error generating dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


############################################################################################
# API Endpoints for Decision Insights
############################################################################################


def convert_real_data_to_mock_format(period_data_list, current_period, currency):
    """
    Convert real PeriodData with enhanced DecisionData to proper FormattedValue format.

    Args:
        period_data_list: List of PeriodData from DailyView (quarterly or hourly resolution)
        current_period: Current period index for marking is_current_hour
        currency: Currency code for formatting

    Returns:
        Dictionary with FormattedValue objects for proper frontend display
    """
    patterns = []

    for period_data in period_data_list:
        # Convert quarterly period (0-95) to hour (0-23) for display
        period = period_data.period
        hour = period // 4  # Quarterly to hourly conversion

        energy = period_data.energy
        economic = period_data.economic
        decision = period_data.decision

        # Determine if this is current period and actual vs predicted
        is_current = period == current_period
        is_actual = period_data.data_source == "actual"

        # Create flows dictionary with FormattedValue objects
        flows = {
            "solar_to_home": create_formatted_value(
                energy.solar_to_home, "energy_kwh_only", currency
            ),
            "solar_to_battery": create_formatted_value(
                energy.solar_to_battery, "energy_kwh_only", currency
            ),
            "solar_to_grid": create_formatted_value(
                energy.solar_to_grid, "energy_kwh_only", currency
            ),
            "grid_to_home": create_formatted_value(
                energy.grid_to_home, "energy_kwh_only", currency
            ),
            "grid_to_battery": create_formatted_value(
                energy.grid_to_battery, "energy_kwh_only", currency
            ),
            "battery_to_home": create_formatted_value(
                energy.battery_to_home, "energy_kwh_only", currency
            ),
            "battery_to_grid": create_formatted_value(
                energy.battery_to_grid, "energy_kwh_only", currency
            ),
        }

        # Create immediate_flow_values using enhanced decision intelligence data
        immediate_flow_values = {}

        # Enhanced decision intelligence should always provide detailed flow values
        # For historical data, detailed_flow_values might not be populated yet
        if not decision.detailed_flow_values:
            # Detailed flow values are only available for predicted periods;
            # historical periods use an empty dict for now.
            decision.detailed_flow_values = {}

        # Use the advanced flow value calculations from decision intelligence
        for flow_name, flow_value in decision.detailed_flow_values.items():
            immediate_flow_values[flow_name] = create_formatted_value(
                flow_value, "currency", currency
            )

        # Calculate immediate_total_value as sum of all flow values (extract numeric values)
        total_value = sum(fv.value for fv in immediate_flow_values.values())
        immediate_total_value = create_formatted_value(
            total_value, "currency", currency
        )

        # Create future_opportunity with enhanced data
        future_opportunity = {
            "description": f"Future value realization from {decision.strategic_intent.lower().replace('_', ' ')} strategy",
            "target_hours": (
                decision.future_target_hours if decision.future_target_hours else []
            ),
            "expected_value": create_formatted_value(
                decision.future_value or 0.0, "currency", currency
            ),
            "dependencies": [
                "Price forecast accuracy",
                "Battery state management",
                "Solar production forecast",
            ],
        }

        # Create the pattern object with enhanced decision intelligence fields
        pattern = {
            "hour": hour,
            "pattern_name": decision.pattern_name
            or f"{decision.strategic_intent} Strategy",
            "flow_description": decision.description or "No significant energy flows",
            "economic_context_description": f"Strategic intent: {decision.strategic_intent} - {decision.pattern_name or 'Standard operation'}",
            "flows": flows,
            "immediate_flow_values": immediate_flow_values,
            "immediate_total_value": immediate_total_value,
            "future_opportunity": future_opportunity,
            "economic_chain": decision.economic_chain
            or f"Hour {hour:02d}: No enhanced economic reasoning available",
            "net_strategy_value": create_formatted_value(
                decision.net_strategy_value or 0.0, "currency", currency
            ),
            "electricity_price": create_formatted_value(
                economic.buy_price, "currency", currency
            ),
            "is_current_hour": is_current,
            "is_actual": is_actual,
            # Simple enhanced fields that actually work
            "advanced_flow_pattern": decision.advanced_flow_pattern
            or "NO_PATTERN_DETECTED",
        }

        patterns.append(pattern)

    # Calculate summary statistics matching mock format
    if patterns:
        # Extract numeric values from FormattedValue objects before summing
        total_net_value = sum(p["net_strategy_value"].value for p in patterns)
        actual_patterns = [p for p in patterns if p["is_actual"]]
        predicted_patterns = [p for p in patterns if not p["is_actual"]]
        best_decision = max(patterns, key=lambda p: p["net_strategy_value"].value)

        summary = {
            "total_net_value": create_formatted_value(
                total_net_value, "currency", currency
            ),
            "best_decision_hour": best_decision["hour"],
            "best_decision_value": best_decision["net_strategy_value"],
            "actual_hours_count": len(actual_patterns),
            "predicted_hours_count": len(predicted_patterns),
        }
    else:
        summary = {
            "total_net_value": create_formatted_value(0.0, "currency", currency),
            "best_decision_hour": 0,
            "best_decision_value": create_formatted_value(0.0, "currency", currency),
            "actual_hours_count": 0,
            "predicted_hours_count": 0,
        }

    # Create response matching exact mock format
    response = {"patterns": patterns, "summary": summary}

    # Process future_opportunity objects for camelCase conversion (matching mock logic)
    for pattern in patterns:
        opportunity = pattern.get("future_opportunity")
        if opportunity:
            pattern["future_opportunity"] = {
                "description": opportunity["description"],
                "targetHours": opportunity["target_hours"],
                "expectedValue": opportunity["expected_value"],
                "dependencies": opportunity["dependencies"],
            }

    return response


@router.get("/api/decision-intelligence")
async def get_decision_intelligence():
    """
    Get decision intelligence data using real optimization results.
    Converts real HourlyData to exact mock format for frontend compatibility.
    """
    from app import bess_controller

    try:
        # Get the daily view with real optimization data (same as dashboard)
        daily_view = bess_controller.system.get_current_daily_view()

        # Get currency from settings
        currency = bess_controller.system.home_settings.currency

        # Calculate current period index (for quarterly resolution)
        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        # Convert real PeriodData to mock format
        response = convert_real_data_to_mock_format(
            daily_view.periods, current_period, currency
        )

        # Convert snake_case to camelCase for frontend (matching mock behavior)
        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.warning(
            f"Decision intelligence not available yet (insights page under construction): {e}"
        )
        # Return minimal empty response instead of crashing - insights page is under construction
        return convert_keys_to_camel_case(
            {
                "hours": [],
                "summary": {
                    "total_battery_actions": 0,
                    "charging_hours": 0,
                    "discharging_hours": 0,
                    "idle_hours": 0,
                    "peak_charge_rate": 0.0,
                    "peak_discharge_rate": 0.0,
                },
                "message": "Decision intelligence data not yet available - insights page under construction",
            }
        )


# @router.get("/api/decision-intelligence")
async def get_decision_intelligence_mock():
    """
    Get decision intelligence data with detailed flow patterns and economic reasoning.

    Returns comprehensive energy flow analysis for each hour showing:
    - Battery actions (charge/discharge decisions)
    - Energy flow patterns between solar, grid, home, and battery
    - Economic context and future opportunities
    - Multi-hour strategy explanations
    """
    try:
        current_hour = time_utils.now().hour
        patterns = []

        # Real historical prices from 2024-08-16 (extreme volatility day)
        prices = [
            0.9827,
            0.8419,
            0.0321,
            0.0097,
            0.0098,
            0.9136,
            1.4433,
            1.5162,  # 00-07: High→Low→High
            1.4029,
            1.1346,
            0.8558,
            0.6485,
            0.2895,
            0.1363,
            0.1253,
            0.62,  # 08-15: Morning high, midday drop
            0.888,
            1.1662,
            1.5163,
            2.5908,
            2.7325,
            1.9312,
            1.5121,
            1.3056,  # 16-23: Evening extreme peak
        ]

        # Realistic solar pattern for summer day
        solar = [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.8,  # 00-07: No solar
            2.3,
            3.7,
            4.8,
            5.5,
            5.8,
            5.8,
            5.3,
            4.4,  # 08-15: Solar ramp up to peak
            3.3,
            1.9,
            0.9,
            0.1,
            0.0,
            0.0,
            0.0,
            0.0,  # 16-23: Solar declining
        ]

        home_consumption = 5.2  # Constant consumption from test data

        for hour in range(24):
            price = prices[hour]
            solar_production = solar[hour]
            is_actual = hour < current_hour
            is_current = hour == current_hour

            if hour >= 0 and hour <= 4:
                # Night/Early morning: Different strategies based on price extremes
                if price < 0.05:
                    # Ultra-cheap hours (03:00-04:00): Massive arbitrage opportunity
                    pattern = {
                        "hour": hour,
                        "pattern_name": "GRID_TO_HOME_AND_BATTERY",
                        "flow_description": "Grid 11.2kWh: 5.2kWh→Home, 6.0kWh→Battery",
                        "economic_context_description": "Ultra-cheap electricity at 0.01 SEK/kWh - maximum charging for extreme evening arbitrage",
                        "flows": {
                            "solar_to_home": 0,
                            "solar_to_battery": 0,
                            "solar_to_grid": 0,
                            "grid_to_home": home_consumption,
                            "grid_to_battery": 6.0,
                            "battery_to_home": 0,
                            "battery_to_grid": 0,
                        },
                        "immediate_flow_values": {
                            "grid_to_home": -home_consumption * price,
                            "grid_to_battery": -6.0 * price,
                        },
                        "immediate_total_value": -(home_consumption + 6.0) * price,
                        "future_opportunity": {
                            "description": "Peak arbitrage during extreme evening prices at 2.73 SEK/kWh",
                            "target_hours": [20, 21],
                            "expected_value": 6.0 * 2.73,
                            "dependencies": [
                                "Battery capacity available",
                                "Peak price realization",
                                "No grid export limits",
                            ],
                        },
                        "economic_chain": f"Hour {hour:02d}: Import 11.2kWh at ultra-cheap {price:.4f} SEK/kWh (-{((home_consumption + 6.0) * price):.2f} SEK) → Peak discharge 20:00-21:00 at 2.73 SEK/kWh (+{(6.0 * 2.73):.2f} SEK) → Net arbitrage profit: +{(6.0 * 2.73 - (home_consumption + 6.0) * price):.2f} SEK",
                        "net_strategy_value": 6.0 * 2.73
                        - (home_consumption + 6.0) * price,
                        "electricity_price": price,
                        "is_current_hour": is_current,
                        "is_actual": is_actual,
                    }
                else:
                    # Expensive night hours: Conservative operation
                    pattern = {
                        "hour": hour,
                        "pattern_name": "GRID_TO_HOME",
                        "flow_description": "Grid 5.2kWh→Home",
                        "economic_context_description": "High night prices prevent arbitrage charging - wait for cheaper periods",
                        "flows": {
                            "solar_to_home": 0,
                            "solar_to_battery": 0,
                            "solar_to_grid": 0,
                            "grid_to_home": home_consumption,
                            "grid_to_battery": 0,
                            "battery_to_home": 0,
                            "battery_to_grid": 0,
                        },
                        "immediate_flow_values": {
                            "grid_to_home": -home_consumption * price
                        },
                        "immediate_total_value": -home_consumption * price,
                        "future_opportunity": {
                            "description": "Wait for ultra-cheap periods at 03:00-04:00 for arbitrage charging",
                            "target_hours": [3, 4],
                            "expected_value": 0,
                            "dependencies": ["Price drop realization"],
                        },
                        "economic_chain": f"Hour {hour:02d}: Standard consumption at {price:.2f} SEK/kWh (-{(home_consumption * price):.2f} SEK) → Avoid charging until ultra-cheap 03:00-04:00 periods",
                        "net_strategy_value": -home_consumption * price,
                        "electricity_price": price,
                        "is_current_hour": is_current,
                        "is_actual": is_actual,
                    }
            elif hour >= 5 and hour <= 7:
                # Morning: Price rising, prepare for peak
                pattern = {
                    "hour": hour,
                    "pattern_name": "GRID_TO_HOME_AND_BATTERY",
                    "flow_description": "Grid 8.2kWh: 5.2kWh→Home, 3.0kWh→Battery",
                    "economic_context_description": "Rising morning prices but still profitable vs extreme evening peak - final charging window",
                    "flows": {
                        "solar_to_home": 0,
                        "solar_to_battery": 0,
                        "solar_to_grid": 0,
                        "grid_to_home": home_consumption,
                        "grid_to_battery": 3.0,
                        "battery_to_home": 0,
                        "battery_to_grid": 0,
                    },
                    "immediate_flow_values": {
                        "grid_to_home": -home_consumption * price,
                        "grid_to_battery": -3.0 * price,
                    },
                    "immediate_total_value": -(home_consumption + 3.0) * price,
                    "future_opportunity": {
                        "description": "Evening arbitrage at 2.59-2.73 SEK/kWh peak",
                        "target_hours": [19, 20, 21],
                        "expected_value": 3.0 * 2.6,
                        "dependencies": [
                            "Evening peak price accuracy",
                            "Battery availability",
                        ],
                    },
                    "economic_chain": f"Hour {hour:02d}: Import 8.2kWh at {price:.2f} SEK/kWh (-{((home_consumption + 3.0) * price):.2f} SEK) → Evening peak discharge at 2.60 SEK/kWh (+{(3.0 * 2.6):.2f} SEK) → Net profit: +{(3.0 * 2.6 - (home_consumption + 3.0) * price):.2f} SEK",
                    "net_strategy_value": 3.0 * 2.6 - (home_consumption + 3.0) * price,
                    "electricity_price": price,
                    "is_current_hour": is_current,
                    "is_actual": is_actual,
                }
            elif hour >= 8 and hour <= 15:
                # Daytime: Solar available, complex optimization
                if solar_production > home_consumption:
                    # Excess solar available
                    pattern = {
                        "hour": hour,
                        "pattern_name": "SOLAR_TO_HOME_AND_BATTERY_AND_GRID",
                        "flow_description": f"Solar {solar_production:.1f}kWh: {home_consumption:.1f}kWh→Home, {min(2.5, solar_production - home_consumption):.1f}kWh→Battery, {max(0, solar_production - home_consumption - 2.5):.1f}kWh→Grid",
                        "economic_context_description": "Peak solar optimally distributed - prioritize battery storage over immediate export for evening arbitrage",
                        "flows": {
                            "solar_to_home": home_consumption,
                            "solar_to_battery": min(
                                2.5, solar_production - home_consumption
                            ),
                            "solar_to_grid": max(
                                0, solar_production - home_consumption - 2.5
                            ),
                            "grid_to_home": 0,
                            "grid_to_battery": 0,
                            "battery_to_home": 0,
                            "battery_to_grid": 0,
                        },
                        "immediate_flow_values": {
                            "solar_to_home": home_consumption * price,
                            "solar_to_battery": 0,
                            "solar_to_grid": max(
                                0, solar_production - home_consumption - 2.5
                            )
                            * 0.08,
                        },
                        "immediate_total_value": home_consumption * price
                        + max(0, solar_production - home_consumption - 2.5) * 0.08,
                        "future_opportunity": {
                            "description": "Stored solar enables evening peak arbitrage worth 2.59 SEK/kWh",
                            "target_hours": [19, 20, 21],
                            "expected_value": min(
                                2.5, solar_production - home_consumption
                            )
                            * 2.59,
                            "dependencies": [
                                "Evening peak prices",
                                "Battery SOC management",
                                "Home consumption accuracy",
                            ],
                        },
                        "economic_chain": f"Hour {hour:02d}: Solar saves {(home_consumption * price):.2f} SEK + export {(max(0, solar_production - home_consumption - 2.5) * 0.08):.2f} SEK → Stored solar discharge 19:00-21:00 at 2.59 SEK/kWh (+{(min(2.5, solar_production - home_consumption) * 2.59):.2f} SEK) → Total value: +{(home_consumption * price + max(0, solar_production - home_consumption - 2.5) * 0.08 + min(2.5, solar_production - home_consumption) * 2.59):.2f} SEK",
                        "net_strategy_value": home_consumption * price
                        + max(0, solar_production - home_consumption - 2.5) * 0.08
                        + min(2.5, solar_production - home_consumption) * 2.59,
                        "electricity_price": price,
                        "is_current_hour": is_current,
                        "is_actual": is_actual,
                    }
                else:
                    # Insufficient solar
                    pattern = {
                        "hour": hour,
                        "pattern_name": "SOLAR_TO_HOME_PLUS_GRID_TO_HOME",
                        "flow_description": f"Solar {solar_production:.1f}kWh→Home, Grid {(home_consumption - solar_production):.1f}kWh→Home",
                        "economic_context_description": "Partial solar coverage - grid supplement needed but avoid charging during moderate prices",
                        "flows": {
                            "solar_to_home": solar_production,
                            "solar_to_battery": 0,
                            "solar_to_grid": 0,
                            "grid_to_home": home_consumption - solar_production,
                            "grid_to_battery": 0,
                            "battery_to_home": 0,
                            "battery_to_grid": 0,
                        },
                        "immediate_flow_values": {
                            "solar_to_home": solar_production * price,
                            "grid_to_home": -(home_consumption - solar_production)
                            * price,
                        },
                        "immediate_total_value": solar_production * price
                        - (home_consumption - solar_production) * price,
                        "future_opportunity": {
                            "description": "Wait for evening peak to discharge stored energy from night charging",
                            "target_hours": [19, 20, 21],
                            "expected_value": 0,
                            "dependencies": [
                                "Previously stored battery energy availability"
                            ],
                        },
                        "economic_chain": f"Hour {hour:02d}: Solar saves {(solar_production * price):.2f} SEK, Grid costs {((home_consumption - solar_production) * price):.2f} SEK → Net: {(solar_production * price - (home_consumption - solar_production) * price):.2f} SEK",
                        "net_strategy_value": solar_production * price
                        - (home_consumption - solar_production) * price,
                        "electricity_price": price,
                        "is_current_hour": is_current,
                        "is_actual": is_actual,
                    }
            elif hour >= 16 and hour <= 18:
                # Early evening: Price rising, transition strategy
                pattern = {
                    "hour": hour,
                    "pattern_name": "SOLAR_TO_HOME_PLUS_BATTERY_TO_HOME",
                    "flow_description": f"Solar {solar_production:.1f}kWh→Home, Battery {max(0, home_consumption - solar_production):.1f}kWh→Home",
                    "economic_context_description": "Rising prices trigger battery discharge - preserve remaining charge for extreme peak hours",
                    "flows": {
                        "solar_to_home": min(solar_production, home_consumption),
                        "solar_to_battery": 0,
                        "solar_to_grid": 0,
                        "grid_to_home": 0,
                        "grid_to_battery": 0,
                        "battery_to_home": max(0, home_consumption - solar_production),
                        "battery_to_grid": 0,
                    },
                    "immediate_flow_values": {
                        "solar_to_home": min(solar_production, home_consumption)
                        * price,
                        "battery_to_home": max(0, home_consumption - solar_production)
                        * price,
                    },
                    "immediate_total_value": home_consumption * price,
                    "future_opportunity": {
                        "description": "Preserve remaining battery charge for extreme peak at 2.73 SEK/kWh",
                        "target_hours": [20, 21],
                        "expected_value": 3.0 * 2.73,
                        "dependencies": [
                            "Peak price realization",
                            "Battery SOC sufficient",
                        ],
                    },
                    "economic_chain": f"Hour {hour:02d}: Avoid grid at {price:.2f} SEK/kWh (+{(home_consumption * price):.2f} SEK saved) → Reserve charge for 20:00-21:00 peak at 2.73 SEK/kWh (+{(3.0 * 2.73):.2f} SEK potential)",
                    "net_strategy_value": home_consumption * price + 3.0 * 2.73,
                    "electricity_price": price,
                    "is_current_hour": is_current,
                    "is_actual": is_actual,
                }
            elif hour >= 19 and hour <= 21:
                # Peak hours: Maximum arbitrage execution
                pattern = {
                    "hour": hour,
                    "pattern_name": "BATTERY_TO_HOME_AND_GRID",
                    "flow_description": "Battery 6.0kWh: 5.2kWh→Home, 0.8kWh→Grid",
                    "economic_context_description": "Extreme peak prices - full arbitrage execution with both home supply and grid export",
                    "flows": {
                        "solar_to_home": 0,
                        "solar_to_battery": 0,
                        "solar_to_grid": 0,
                        "grid_to_home": 0,
                        "grid_to_battery": 0,
                        "battery_to_home": home_consumption,
                        "battery_to_grid": 0.8,
                    },
                    "immediate_flow_values": {
                        "battery_to_home": home_consumption * price,
                        "battery_to_grid": 0.8 * 0.08,
                    },
                    "immediate_total_value": home_consumption * price + 0.8 * 0.08,
                    "future_opportunity": {
                        "description": "Peak arbitrage strategy execution - realizing value from night charging at 0.01 SEK/kWh",
                        "target_hours": [],
                        "expected_value": 0,
                        "dependencies": [],
                    },
                    "economic_chain": f"Hour {hour:02d}: Battery arbitrage execution (+{(home_consumption * price + 0.8 * 0.08):.2f} SEK) ← Sourced from ultra-cheap night charging at 0.01 SEK/kWh → Net arbitrage profit: +{((home_consumption + 0.8) * price - (home_consumption + 0.8) * 0.01):.2f} SEK",
                    "net_strategy_value": (home_consumption + 0.8) * price
                    - (home_consumption + 0.8) * 0.01,
                    "electricity_price": price,
                    "is_current_hour": is_current,
                    "is_actual": is_actual,
                }
            else:
                # Late evening: Post-peak wind down
                pattern = {
                    "hour": hour,
                    "pattern_name": "BATTERY_TO_HOME",
                    "flow_description": "Battery 5.2kWh→Home",
                    "economic_context_description": "Post-peak period - continue battery discharge while prices remain elevated above charging cost",
                    "flows": {
                        "solar_to_home": 0,
                        "solar_to_battery": 0,
                        "solar_to_grid": 0,
                        "grid_to_home": 0,
                        "grid_to_battery": 0,
                        "battery_to_home": home_consumption,
                        "battery_to_grid": 0,
                    },
                    "immediate_flow_values": {
                        "battery_to_home": home_consumption * price
                    },
                    "immediate_total_value": home_consumption * price,
                    "future_opportunity": {
                        "description": "Continue arbitrage until prices drop below charging costs - prepare for next cycle",
                        "target_hours": [],
                        "expected_value": 0,
                        "dependencies": [
                            "Next day price forecast",
                            "Battery SOC management",
                        ],
                    },
                    "economic_chain": f"Hour {hour:02d}: Continue discharge at {price:.2f} SEK/kWh (+{(home_consumption * price):.2f} SEK) ← Sourced from 0.01 SEK/kWh charging → Arbitrage profit: +{(home_consumption * (price - 0.01)):.2f} SEK",
                    "net_strategy_value": home_consumption * (price - 0.01),
                    "electricity_price": price,
                    "is_current_hour": is_current,
                    "is_actual": is_actual,
                }

            patterns.append(pattern)

        # Calculate summary statistics
        total_net_value = sum(p["net_strategy_value"] for p in patterns)
        actual_patterns = [p for p in patterns if p["is_actual"]]
        predicted_patterns = [p for p in patterns if not p["is_actual"]]
        best_decision = max(patterns, key=lambda p: p["net_strategy_value"])

        response = {
            "patterns": patterns,
            "summary": {
                "total_net_value": total_net_value,
                "best_decision_hour": best_decision["hour"],
                "best_decision_value": best_decision["net_strategy_value"],
                "actual_hours_count": len(actual_patterns),
                "predicted_hours_count": len(predicted_patterns),
            },
        }

        # Deep conversion for future_opportunity objects
        for pattern in patterns:
            opportunity = pattern.get("future_opportunity")
            if opportunity:
                pattern["future_opportunity"] = {
                    "description": opportunity["description"],
                    "targetHours": opportunity["target_hours"],
                    "expectedValue": opportunity["expected_value"],
                    "dependencies": opportunity["dependencies"],
                }

        # Convert all other snake_case to camelCase
        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error generating decision intelligence data: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Add growatt endpoints for inverter status and detailed schedule
@router.get("/api/growatt/inverter_status")
async def get_inverter_status():
    """Get comprehensive real-time inverter status data."""
    from app import bess_controller

    try:
        # Safety checks to avoid None references
        if bess_controller.system is None:
            logger.error("Battery system not initialized")
            raise HTTPException(
                status_code=503, detail="Battery system not initialized"
            )

        controller = bess_controller.system._controller
        if controller is None:
            logger.error("Battery controller not initialized")
            raise HTTPException(
                status_code=503, detail="Battery controller not initialized"
            )

        battery_settings = bess_controller.system.battery_settings

        # Get current battery mode from schedule for current hour
        current_battery_mode = "load_first"  # Default
        try:
            current_hour = time_utils.now().hour
            schedule_manager = bess_controller.system._schedule_manager
            hourly_settings = schedule_manager.get_hourly_settings(current_hour)
            current_battery_mode = hourly_settings.get("batt_mode", "load_first")
        except Exception as e:
            logger.warning(f"Failed to get current battery mode: {e}")

        battery_soc = controller.get_battery_soc()
        battery_soe = (battery_soc / 100.0) * battery_settings.total_capacity
        grid_charge_enabled = controller.grid_charge_enabled()
        discharge_power_rate = controller.get_discharging_power_rate()
        battery_charge_power = controller.get_battery_charge_power()
        battery_discharge_power = controller.get_battery_discharge_power()

        response = {
            "battery_soc": battery_soc,
            "battery_soe": battery_soe,
            "battery_charge_power": battery_charge_power,
            "battery_discharge_power": battery_discharge_power,
            "battery_mode": current_battery_mode,
            "grid_charge_enabled": grid_charge_enabled,
            "charge_stop_soc": 100.0,
            "discharge_stop_soc": battery_settings.min_soc,
            "discharge_power_rate": discharge_power_rate,
            "timestamp": datetime.now().isoformat(),
        }

        # Convert to camelCase for API consistency
        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error getting inverter status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/detailed_schedule")
async def get_growatt_detailed_schedule():
    """Get detailed Growatt-specific schedule information with strategic intents."""
    from app import bess_controller

    try:
        schedule_manager = bess_controller.system._schedule_manager
        current_hour = time_utils.now().hour

        # Get TOU intervals directly from schedule manager
        try:
            tou_intervals = schedule_manager.get_all_tou_segments()
        except Exception as e:
            logger.error(f"Failed to get TOU intervals: {e}")
            tou_intervals = []

        # Get strategic intent summary
        intent_distribution = {}
        strategic_summary = {}
        try:
            strategic_summary = schedule_manager.get_strategic_intent_summary()
            for intent, data in strategic_summary.items():
                intent_distribution[intent] = data.get("count", 0)
        except Exception as e:
            logger.error(f"Failed to get strategic intent summary: {e}")

        # Build hourly schedule data
        schedule_data = []
        charge_hours = 0
        discharge_hours = 0
        idle_hours = 0
        mode_distribution = {}

        for hour in range(24):
            try:
                hourly_settings = schedule_manager.get_hourly_settings(hour)
                battery_mode = hourly_settings.get("batt_mode", "load_first")
                mode_distribution[battery_mode] = (
                    mode_distribution.get(battery_mode, 0) + 1
                )

                strategic_intent = hourly_settings.get("strategic_intent", "IDLE")

                # Determine action and color based on strategic intent
                if strategic_intent == "GRID_CHARGING":
                    action = "GRID_CHARGE"
                    action_color = "blue"
                    charge_hours += 1
                elif strategic_intent == "SOLAR_CHARGING":
                    action = "SOLAR_CHARGE"
                    action_color = "green"
                    charge_hours += 1
                elif strategic_intent == "IDLE":
                    action = "IDLE"
                    action_color = "gray"
                    idle_hours += 1
                else:
                    action = "EXPORT"
                    action_color = "red"
                    discharge_hours += 1

                # Get price for this hour
                price = 1.0
                try:
                    price_entries = (
                        bess_controller.system.price_manager.get_today_prices()
                    )
                    if hour < len(price_entries):
                        price = price_entries[hour]
                except Exception as e:
                    logger.warning(f"Failed to get price for hour {hour}: {e}")

                # Calculate or default battery-related values
                battery_action = hourly_settings.get("battery_action", 0.0)
                battery_charged = max(0, battery_action) if battery_action > 0 else 0
                battery_discharged = (
                    abs(min(0, battery_action)) if battery_action < 0 else 0
                )
                schedule_data.append(
                    {
                        "hour": hour,
                        "mode": hourly_settings.get("state", "idle"),
                        "batt_mode": battery_mode,
                        "batteryMode": battery_mode,
                        "grid_charge": hourly_settings.get("grid_charge", False),
                        "discharge_rate": hourly_settings.get("discharge_rate", 100),
                        "dischargePowerRate": hourly_settings.get("discharge_rate", 100),
                        "chargePowerRate": 100,
                        "strategic_intent": strategic_intent,
                        "intent_description": schedule_manager._get_intent_description(
                            strategic_intent
                        ),
                        "action": action,
                        "action_color": action_color,
                        "battery_action": battery_action,
                        "battery_action_kw": hourly_settings.get("battery_action_kw", 0.0),
                        "batteryCharged": battery_charged,
                        "batteryDischarged": battery_discharged,
                        "price": price,
                        "electricity_price": price,
                        "grid_power": 0,
                        "is_current": hour == current_hour,
                    }
                )

            except Exception as e:
                logger.error(f"Error processing hour {hour}: {e}")
                schedule_data.append(
                    {
                        "hour": hour,
                        "mode": "idle",
                        "batt_mode": "load_first",
                        "batteryMode": "load_first",  # Add alias for frontend compatibility
                        "grid_charge": False,
                        "discharge_rate": 100,
                        "dischargePowerRate": 100,  # Add alias
                        "chargePowerRate": 100,  # Default charge power rate
                        "strategic_intent": "IDLE",
                        "intent_description": "",
                        "action": "IDLE",
                        "action_color": "gray",
                        "battery_action": 0.0,
                        "batteryCharged": 0.0,  # Add for frontend compatibility
                        "batteryDischarged": 0.0,  # Add for frontend compatibility
                        "soc": 50.0,
                        "batterySocEnd": 50.0,  # Add for frontend compatibility
                        "price": 1.0,
                        "electricity_price": 1.0,
                        "grid_power": 0,
                        "is_current": hour == current_hour,
                    }
                )
                idle_hours += 1

        # Get period groups from schedule manager (15-minute resolution)
        period_groups = []
        try:
            raw_groups = schedule_manager.get_detailed_period_groups()
            for group in raw_groups:
                period_groups.append(
                    {
                        "start_time": group["start_time"],
                        "end_time": group["end_time"],
                        "mode": group["mode"],
                        "dominant_intent": group["intent"],
                        "intent_counts": {group["intent"]: group["period_count"]},
                        "period_count": group["period_count"],
                        "duration_minutes": group["duration_minutes"],
                        "charge_power_rate": group["charge_rate"],
                        "discharge_power_rate": group["discharge_rate"],
                        "grid_charge": group["grid_charge"],
                    }
                )
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to get period groups: {e}")

        # Extract tomorrow's period groups from ScheduleStore (same source as dashboard)
        tomorrow_period_groups: list[dict] | None = None
        try:
            stored_schedule = (
                bess_controller.system.schedule_store.get_latest_schedule()
            )
            if stored_schedule:
                opt_result = stored_schedule.optimization_result
                opt_period = stored_schedule.optimization_period
                today_period_count = get_period_count(time_utils.today())
                tomorrow_period_count = get_period_count(
                    time_utils.today() + timedelta(days=1)
                )
                tomorrow_intents = []
                for period_idx in range(
                    today_period_count,
                    today_period_count + tomorrow_period_count,
                ):
                    data_idx = period_idx - opt_period
                    if 0 <= data_idx < len(opt_result.period_data):
                        tomorrow_intents.append(
                            opt_result.period_data[data_idx].decision.strategic_intent
                        )
                if tomorrow_intents:
                    raw_tomorrow_groups = schedule_manager.get_detailed_period_groups(
                        intents=tomorrow_intents
                    )
                    tomorrow_period_groups = []
                    for group in raw_tomorrow_groups:
                        tomorrow_period_groups.append(
                            {
                                "start_time": group["start_time"],
                                "end_time": group["end_time"],
                                "mode": group["mode"],
                                "dominant_intent": group["intent"],
                                "intent_counts": {
                                    group["intent"]: group["period_count"]
                                },
                                "period_count": group["period_count"],
                                "duration_minutes": group["duration_minutes"],
                                "charge_power_rate": group["charge_rate"],
                                "discharge_power_rate": group["discharge_rate"],
                                "grid_charge": group["grid_charge"],
                            }
                        )
        except (AttributeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to get tomorrow's period groups: {e}")
            tomorrow_period_groups = None

        response = {
            "current_hour": current_hour,
            "tou_intervals": tou_intervals,
            "schedule_data": schedule_data,
            "period_groups": period_groups,
            "tomorrow_period_groups": tomorrow_period_groups,
            "mode_distribution": mode_distribution,
            "intent_distribution": intent_distribution,
            "hour_distribution": {
                "charge": charge_hours,
                "discharge": discharge_hours,
                "idle": idle_hours,
            },
            "strategic_intent_summary": strategic_summary,
        }

        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error in get_growatt_detailed_schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/tou_settings")
async def get_tou_settings():
    """Get current TOU (Time of Use) settings with strategic intent information."""
    from app import bess_controller

    logger.info("/api/growatt/tou_settings")

    try:
        # Safety checks
        if bess_controller.system is None:
            logger.error("Battery system not initialized")
            raise HTTPException(
                status_code=503, detail="Battery system not initialized"
            )

        if bess_controller.system._schedule_manager is None:
            logger.error("Schedule manager not initialized")
            raise HTTPException(
                status_code=503, detail="Schedule manager not initialized"
            )

        schedule_manager = bess_controller.system._schedule_manager
        tou_intervals = schedule_manager.get_all_tou_segments()
        current_hour = time_utils.now().hour

        # Enhanced TOU intervals with hourly settings and strategic intents
        enhanced_tou_intervals = []
        for interval in tou_intervals:
            enhanced_interval = interval.copy()
            start_hour = int(interval["start_time"].split(":")[0])
            try:
                settings = schedule_manager.get_hourly_settings(start_hour)
                enhanced_interval["grid_charge"] = settings.get("grid_charge", False)
                enhanced_interval["discharge_rate"] = settings.get(
                    "discharge_rate", 100
                )
                enhanced_interval["strategic_intent"] = settings.get(
                    "strategic_intent", "IDLE"
                )
            except Exception as e:
                logger.error(
                    f"Error getting hourly settings for hour {start_hour}: {e}"
                )
                enhanced_interval["grid_charge"] = False
                enhanced_interval["discharge_rate"] = 100
                enhanced_interval["strategic_intent"] = "IDLE"

            # Calculate interval hours to help frontend
            start_hour = int(interval["start_time"].split(":")[0])
            end_hour = int(interval["end_time"].split(":")[0])
            if end_hour < start_hour:  # Handle overnight intervals
                end_hour += 24
            enhanced_interval["hours"] = end_hour - start_hour + 1
            enhanced_interval["is_active"] = (
                start_hour <= current_hour % 24 <= end_hour % 24 and interval["enabled"]
            )

            enhanced_tou_intervals.append(enhanced_interval)

        return convert_keys_to_camel_case({"tou_settings": enhanced_tou_intervals})

    except Exception as e:
        logger.error(f"Error getting TOU settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/strategic_intents")
async def get_strategic_intents():
    """Get strategic intent information for the current schedule."""
    from app import bess_controller

    try:
        # Safety checks
        if bess_controller.system is None:
            logger.error("Battery system not initialized")
            raise HTTPException(
                status_code=503, detail="Battery system not initialized"
            )

        if bess_controller.system._schedule_manager is None:
            logger.error("Schedule manager not initialized")
            raise HTTPException(
                status_code=503, detail="Schedule manager not initialized"
            )

        schedule_manager = bess_controller.system._schedule_manager

        # Get strategic intent summary
        strategic_summary = schedule_manager.get_strategic_intent_summary()

        # Get hourly strategic intents
        hourly_intents = []
        for hour in range(24):
            try:
                settings = schedule_manager.get_hourly_settings(hour)
                intent = settings.get("strategic_intent", "IDLE")
                description = schedule_manager._get_intent_description(intent)

                hourly_intents.append(
                    {
                        "hour": hour,
                        "intent": intent,
                        "description": description,
                        "battery_action": settings.get("battery_action", 0.0),
                        "grid_charge": settings.get("grid_charge", False),
                        "discharge_rate": settings.get("discharge_rate", 100),
                        "is_current": hour == time_utils.now().hour,
                    }
                )
            except Exception as e:
                logger.error(f"Error getting hourly settings for hour {hour}: {e}")
                raise ValueError(
                    f"Hourly settings data is required for hour {hour} but failed to load: {e}"
                ) from e

        response = {
            "summary": strategic_summary,
            "hourly_intents": hourly_intents,
        }

        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error getting strategic intents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/system-health")
async def get_system_health():
    """Get comprehensive system health including detailed sensor diagnostics."""

    from app import bess_controller

    try:
        logger.debug("Starting system health check")

        # Run actual health checks
        health_results = run_system_health_checks(bess_controller.system)

        logger.debug(f"Health check completed: {health_results}")
        return convert_keys_to_camel_case(health_results)
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        # Return error state that frontend can handle

        error_result = {
            "timestamp": datetime.now().isoformat(),
            "system_mode": "unknown",
            "checks": [],
            "summary": {
                "total_components": 0,
                "ok_components": 0,
                "warning_components": 0,
                "error_components": 1,
                "overall_status": "ERROR",
            },
        }
        return convert_keys_to_camel_case(error_result)


@router.get("/api/dashboard-health-summary")
async def get_dashboard_health_summary():
    """Get lightweight health summary for dashboard alert banner - only critical issues."""

    from app import bess_controller

    try:
        logger.debug("Starting dashboard health summary check")

        # Check if system is in degraded mode first
        if bess_controller.system.has_critical_sensor_failures():
            # System is in degraded mode due to critical sensor failures
            critical_failures = bess_controller.system.get_critical_sensor_failures()
            critical_issues = []
            for failure in critical_failures:
                critical_issues.append(
                    {
                        "component": failure,
                        "description": "Critical sensor configuration issue detected",
                        "status": "ERROR",
                    }
                )

            summary = {
                "has_critical_errors": True,
                "has_warnings": False,
                "critical_issues": critical_issues,
                "total_critical_issues": len(critical_issues),
                "timestamp": datetime.now().isoformat(),
                "system_mode": "degraded",
            }
        else:
            # System is healthy, use cached health check from startup (fast!)
            health_results = bess_controller.system.get_cached_health_results()

            # If no cached results (shouldn't happen), return minimal response
            if not health_results:
                logger.warning(
                    "No cached health results available, returning minimal response"
                )
                return {
                    "has_critical_errors": False,
                    "has_warnings": False,
                    "critical_issues": [],
                    "total_critical_issues": 0,
                    "timestamp": datetime.now().isoformat(),
                    "system_mode": "unknown",
                }

            # Extract critical and warning information
            critical_issues = []
            has_critical_error = False

            for component in health_results.get("checks", []):
                status = component.get("status", "UNKNOWN")
                is_required = component.get("required", False)

                # Show required components with ERROR status as critical
                if is_required and status == "ERROR":
                    has_critical_error = True
                    critical_issues.append(
                        {
                            "component": component.get("name", "Unknown"),
                            "description": component.get("description", ""),
                            "status": status,
                        }
                    )
                # Show all components (required or not) with WARNING or ERROR status
                elif status in ["WARNING", "ERROR"]:
                    critical_issues.append(
                        {
                            "component": component.get("name", "Unknown"),
                            "description": component.get("description", ""),
                            "status": status,
                        }
                    )

            has_warnings = any(
                issue["status"] == "WARNING" for issue in critical_issues
            )
            summary = {
                "has_critical_errors": has_critical_error,
                "has_warnings": has_warnings,
                "critical_issues": critical_issues,
                "total_critical_issues": len(critical_issues),
                "timestamp": datetime.now().isoformat(),
                "system_mode": health_results.get("system_mode", "normal"),
            }

        logger.debug(f"Dashboard health summary: {summary}")
        return convert_keys_to_camel_case(summary)

    except Exception as e:
        logger.error(f"Error getting dashboard health summary: {e}")
        # Return safe error state
        error_summary = {
            "has_critical_errors": True,
            "has_warnings": False,
            "critical_issues": [
                {
                    "component": "System Health Check",
                    "description": "Unable to perform health check",
                    "status": "ERROR",
                }
            ],
            "total_critical_issues": 1,
            "timestamp": datetime.now().isoformat(),
            "system_mode": "unknown",
        }
        return convert_keys_to_camel_case(error_summary)


@router.get("/api/historical-data-status")
async def get_historical_data_status():
    """Check if historical data is incomplete and needs attention.

    Returns information about missing historical data that may affect
    dashboard accuracy and optimization quality.
    """

    from app import bess_controller

    try:
        # Get today's periods (quarterly resolution)
        periods = bess_controller.system.historical_store.get_today_periods()
        current_hour = time_utils.now().hour

        # Find missing periods up to current hour (periods = hour * 4)
        current_period = current_hour * 4
        missing_periods = [i for i in range(current_period) if periods[i] is None]
        completed_periods = [i for i in range(current_period) if periods[i] is not None]

        # Convert to hours for reporting (backwards compatibility)
        missing_hours = list({p // 4 for p in missing_periods})
        completed_hours = list({p // 4 for p in completed_periods})

        is_incomplete = len(missing_periods) > 0

        status = {
            "is_incomplete": is_incomplete,
            "missing_hours": missing_hours,
            "completed_hours": completed_hours,
            "total_missing": len(missing_hours),
            "total_completed": len(completed_hours),
            "message": (
                f"Missing historical data for {len(missing_hours)} hours. "
                f"Dashboard values may be inaccurate until data collection is complete."
                if is_incomplete
                else "Historical data is complete for today."
            ),
            "timestamp": datetime.now().isoformat(),
        }

        return convert_keys_to_camel_case(status)

    except Exception as e:
        logger.error(f"Error checking historical data status: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/prediction-analysis/snapshots")
async def get_prediction_snapshots():
    """Get all prediction snapshots for today."""
    from app import bess_controller

    try:
        snapshots = (
            bess_controller.system.prediction_snapshot_store.get_all_snapshots_today()
        )

        # Get currency from home settings
        currency = bess_controller.system.home_settings.currency

        # Convert to API format
        api_snapshots = [
            APIPredictionSnapshot.from_internal(snapshot, currency)
            for snapshot in snapshots
        ]

        response = {
            "snapshots": [s.__dict__ for s in api_snapshots],
            "count": len(api_snapshots),
        }

        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error fetching prediction snapshots: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/prediction-analysis/timeline")
async def get_prediction_timeline():
    """Get timeline showing how predicted savings evolved throughout the day."""
    from app import bess_controller

    try:
        snapshots = (
            bess_controller.system.prediction_snapshot_store.get_all_snapshots_today()
        )

        # Build timeline data
        timeline_data = {
            "timestamps": [s.snapshot_timestamp.isoformat() for s in snapshots],
            "optimization_periods": [s.optimization_period for s in snapshots],
            "predicted_savings": [s.predicted_daily_savings for s in snapshots],
            "growatt_schedule_counts": [len(s.growatt_schedule) for s in snapshots],
        }

        return convert_keys_to_camel_case(timeline_data)

    except Exception as e:
        logger.error(f"Error building prediction timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/prediction-analysis/comparison")
async def get_prediction_comparison(
    snapshot_period: int = Query(
        ..., ge=0, le=95, description="Period index for snapshot"
    )
):
    """Compare snapshot predictions vs what actually happened."""
    from app import bess_controller
    from core.bess.prediction_analyzer import PredictionAnalyzer

    try:
        # Get snapshot at specified period
        snapshot = (
            bess_controller.system.prediction_snapshot_store.get_snapshot_at_period(
                snapshot_period
            )
        )

        if not snapshot:
            raise HTTPException(
                status_code=404,
                detail=f"No snapshot found for period {snapshot_period}",
            )

        # Get current state

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        # Build current daily view
        current_daily_view = bess_controller.system.daily_view_builder.build_daily_view(
            current_period
        )

        # Get current Growatt schedule
        current_growatt_schedule = (
            bess_controller.system._schedule_manager.tou_intervals.copy()
        )

        # Analyze deviations
        analyzer = PredictionAnalyzer()
        comparison = analyzer.compare_snapshot_to_current(
            snapshot=snapshot,
            current_daily_view=current_daily_view,
            current_growatt_schedule=current_growatt_schedule,
        )

        # Get currency from home settings
        currency = bess_controller.system.home_settings.currency

        # Convert to API format
        api_comparison = APISnapshotComparison.from_internal(comparison, currency)

        return convert_keys_to_camel_case(api_comparison.__dict__)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/prediction-analysis/snapshot-comparison")
async def compare_two_snapshots(
    period_a: int = Query(..., description="First snapshot period to compare"),
    period_b: int = Query(..., description="Second snapshot period to compare"),
):
    """Compare two prediction snapshots to see how predictions evolved."""
    from app import bess_controller

    try:
        # Get both snapshots
        snapshot_a = (
            bess_controller.system.prediction_snapshot_store.get_snapshot_at_period(
                period_a
            )
        )
        snapshot_b = (
            bess_controller.system.prediction_snapshot_store.get_snapshot_at_period(
                period_b
            )
        )

        if not snapshot_a:
            raise HTTPException(
                status_code=404, detail=f"No snapshot found for period {period_a}"
            )
        if not snapshot_b:
            raise HTTPException(
                status_code=404, detail=f"No snapshot found for period {period_b}"
            )

        # Get currency
        currency = bess_controller.system.home_settings.currency

        # Build period maps for defensive lookup (handles edge cases where
        # DailyView might have fewer periods due to HA restart gaps)
        period_map_a = {p.period: p for p in snapshot_a.daily_view.periods}
        period_map_b = {p.period: p for p in snapshot_b.daily_view.periods}

        # Build comprehensive comparison for all 96 periods
        period_comparisons = []
        for period_idx in range(96):
            period_a_data = period_map_a.get(period_idx)
            period_b_data = period_map_b.get(period_idx)

            # Skip periods missing from either snapshot
            if period_a_data is None or period_b_data is None:
                logger.warning(
                    f"Skipping period {period_idx} in snapshot comparison - "
                    f"missing from {'A' if period_a_data is None else 'B'}"
                )
                continue

            # Calculate battery action (net charging/discharging)
            battery_action_a = (
                period_a_data.energy.battery_charged
                - period_a_data.energy.battery_discharged
            )
            battery_action_b = (
                period_b_data.energy.battery_charged
                - period_b_data.energy.battery_discharged
            )

            # Build comparison for this period
            comparison = {
                "period": period_idx,
                # Snapshot A data
                "snapshotA": {
                    "solar": create_formatted_value(
                        period_a_data.energy.solar_production,
                        "energy_kwh_only",
                        currency,
                    ),
                    "consumption": create_formatted_value(
                        period_a_data.energy.home_consumption,
                        "energy_kwh_only",
                        currency,
                    ),
                    "batteryAction": create_formatted_value(
                        battery_action_a, "energy_kwh_only", currency
                    ),
                    "batterySoe": create_formatted_value(
                        period_a_data.energy.battery_soe_end,
                        "energy_kwh_only",
                        currency,
                    ),
                    "gridImport": create_formatted_value(
                        period_a_data.energy.grid_imported, "energy_kwh_only", currency
                    ),
                    "gridExport": create_formatted_value(
                        period_a_data.energy.grid_exported, "energy_kwh_only", currency
                    ),
                    "cost": create_formatted_value(
                        period_a_data.economic.hourly_cost, "currency", currency
                    ),
                    "gridOnlyCost": create_formatted_value(
                        period_a_data.economic.grid_only_cost, "currency", currency
                    ),
                    "savings": create_formatted_value(
                        period_a_data.economic.hourly_savings, "currency", currency
                    ),
                    "dataSource": period_a_data.data_source,
                },
                # Snapshot B data
                "snapshotB": {
                    "solar": create_formatted_value(
                        period_b_data.energy.solar_production,
                        "energy_kwh_only",
                        currency,
                    ),
                    "consumption": create_formatted_value(
                        period_b_data.energy.home_consumption,
                        "energy_kwh_only",
                        currency,
                    ),
                    "batteryAction": create_formatted_value(
                        battery_action_b, "energy_kwh_only", currency
                    ),
                    "batterySoe": create_formatted_value(
                        period_b_data.energy.battery_soe_end,
                        "energy_kwh_only",
                        currency,
                    ),
                    "gridImport": create_formatted_value(
                        period_b_data.energy.grid_imported, "energy_kwh_only", currency
                    ),
                    "gridExport": create_formatted_value(
                        period_b_data.energy.grid_exported, "energy_kwh_only", currency
                    ),
                    "cost": create_formatted_value(
                        period_b_data.economic.hourly_cost, "currency", currency
                    ),
                    "gridOnlyCost": create_formatted_value(
                        period_b_data.economic.grid_only_cost, "currency", currency
                    ),
                    "savings": create_formatted_value(
                        period_b_data.economic.hourly_savings, "currency", currency
                    ),
                    "dataSource": period_b_data.data_source,
                },
                # Differences (B - A)
                "delta": {
                    "solar": create_formatted_value(
                        period_b_data.energy.solar_production
                        - period_a_data.energy.solar_production,
                        "energy_kwh_only",
                        currency,
                    ),
                    "consumption": create_formatted_value(
                        period_b_data.energy.home_consumption
                        - period_a_data.energy.home_consumption,
                        "energy_kwh_only",
                        currency,
                    ),
                    "batteryAction": create_formatted_value(
                        battery_action_b - battery_action_a, "energy_kwh_only", currency
                    ),
                    "batterySoe": create_formatted_value(
                        period_b_data.energy.battery_soe_end
                        - period_a_data.energy.battery_soe_end,
                        "energy_kwh_only",
                        currency,
                    ),
                    "gridImport": create_formatted_value(
                        period_b_data.energy.grid_imported
                        - period_a_data.energy.grid_imported,
                        "energy_kwh_only",
                        currency,
                    ),
                    "gridExport": create_formatted_value(
                        period_b_data.energy.grid_exported
                        - period_a_data.energy.grid_exported,
                        "energy_kwh_only",
                        currency,
                    ),
                    "cost": create_formatted_value(
                        period_b_data.economic.hourly_cost
                        - period_a_data.economic.hourly_cost,
                        "currency",
                        currency,
                    ),
                    "gridOnlyCost": create_formatted_value(
                        period_b_data.economic.grid_only_cost
                        - period_a_data.economic.grid_only_cost,
                        "currency",
                        currency,
                    ),
                    "savings": create_formatted_value(
                        period_b_data.economic.hourly_savings
                        - period_a_data.economic.hourly_savings,
                        "currency",
                        currency,
                    ),
                },
            }
            period_comparisons.append(comparison)

        # Build response
        response = {
            "snapshotAPeriod": period_a,
            "snapshotATimestamp": snapshot_a.snapshot_timestamp.isoformat(),
            "snapshotBPeriod": period_b,
            "snapshotBTimestamp": snapshot_b.snapshot_timestamp.isoformat(),
            "periodComparisons": period_comparisons,
            "growattScheduleA": [
                {
                    "segmentId": i + 1,
                    "battMode": interval["batt_mode"],
                    "startTime": interval["start_time"],
                    "endTime": interval["end_time"],
                    "enabled": interval.get("enabled", True),
                }
                for i, interval in enumerate(snapshot_a.growatt_schedule)
            ],
            "growattScheduleB": [
                {
                    "segmentId": i + 1,
                    "battMode": interval["batt_mode"],
                    "startTime": interval["start_time"],
                    "endTime": interval["end_time"],
                    "enabled": interval.get("enabled", True),
                }
                for i, interval in enumerate(snapshot_b.growatt_schedule)
            ],
        }

        return convert_keys_to_camel_case(response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing snapshots: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/export-debug-data")
async def export_debug_data(compact: bool = True):
    """Export comprehensive debug data as markdown report.

    Returns a markdown file containing all system state, logs, historical data,
    predictions, schedules, and settings for debugging purposes.

    Args:
        compact: If True (default), serves all three debug use cases —
            scenario replay, AI behaviour analysis, and prediction drift analysis.
            Logs are filtered to key events + last 50 lines (not the full log).
            Snapshots are rendered as a 5-field evolution table (not full JSON).
            Set to False only when a raw field not present in compact mode is needed
            (full log, all schedules, all snapshots as JSON). Expect 30–80 MB.

    Security:
    - Via HA ingress (browser): HA handles authentication
    - Via direct port 8080 (local network): Network access is the auth

    Returns:
        PlainTextResponse: Markdown file with complete debug data
    """
    from fastapi.responses import PlainTextResponse

    from app import bess_controller
    from core.bess.debug_data_exporter import DebugDataAggregator
    from core.bess.debug_report_formatter import DebugReportFormatter

    try:
        # Aggregate all system data
        aggregator = DebugDataAggregator(bess_controller.system)
        export_data = aggregator.aggregate_all_data(compact=compact)

        # Format as markdown report
        formatter = DebugReportFormatter()
        markdown_content = formatter.format_report(export_data)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"bess-debug-{timestamp}.md"

        return PlainTextResponse(
            content=markdown_content,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Error exporting debug data: {e}", exc_info=True)

        # Return minimal error report as markdown
        timestamp = datetime.now().isoformat()
        error_report = f"""# BESS Manager Debug Export (ERROR)

**Export Date**: {timestamp}

## Error During Export

Failed to generate debug export:

```
{e!s}
```

Please check the BESS Manager logs for details.
"""

        filename = f"bess-debug-error-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"
        return PlainTextResponse(
            content=error_report,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


@router.get("/api/runtime-failures")
async def get_runtime_failures():
    """Get all active runtime failures.

    Returns a list of runtime failures that have occurred during system operation.
    Failures are tracked when API calls to Home Assistant fail after all retry attempts.

    Returns:
        list[dict]: List of active runtime failures with details
    """
    from app import bess_controller

    try:
        failures = bess_controller.system.get_runtime_failures()
        # Convert to dict format for API response
        return [failure.__dict__ for failure in failures]
    except Exception as e:
        logger.error(f"Error getting runtime failures: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/runtime-failures/{failure_id}/dismiss")
async def dismiss_runtime_failure(failure_id: str):
    """Dismiss a specific runtime failure.

    Marks the failure as acknowledged, removing it from the active failures list.
    The failure will no longer appear in the UI.

    Args:
        failure_id: Unique identifier of the failure to dismiss

    Returns:
        dict: Success confirmation
    """
    from app import bess_controller

    try:
        bess_controller.system.dismiss_runtime_failure(failure_id)
        return {"success": True, "message": f"Failure {failure_id} dismissed"}
    except ValueError:
        raise HTTPException(
            status_code=404, detail=f"Failure with id {failure_id} not found"
        ) from None
    except Exception as e:
        logger.error(f"Error dismissing runtime failure {failure_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/runtime-failures/dismiss-all")
async def dismiss_all_runtime_failures():
    """Dismiss all active runtime failures.

    Marks all failures as acknowledged, clearing the active failures list.
    No failures will appear in the UI until new failures occur.

    Returns:
        dict: Success confirmation with count of dismissed failures
    """
    from app import bess_controller

    try:
        count = bess_controller.system.dismiss_all_runtime_failures()
        return {"success": True, "message": f"Dismissed {count} runtime failures"}
    except Exception as e:
        logger.error(f"Error dismissing all runtime failures: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/setup/status")
async def get_setup_status():
    """Return whether the setup wizard is needed.

    A wizard is needed when no sensor entity IDs are configured. Existing users
    with a full sensor configuration are unaffected and will receive wizard_needed=false.

    Returns:
        dict: wizard_needed, configured_sensors count, total_sensors count
    """
    from app import bess_controller

    sensors = bess_controller.ha_controller.sensors
    total = len(sensors)
    configured = sum(1 for v in sensors.values() if v)
    return convert_keys_to_camel_case(
        {
            "wizard_needed": configured == 0,
            "configured_sensors": configured,
            "total_sensors": total,
        }
    )


@router.post("/api/setup/discover")
async def run_setup_discovery():
    """Run auto-discovery of Growatt and Nordpool integrations.

    Queries the HA entity registry and config entries to deterministically map
    all Growatt MIN sensor entity IDs to BESS sensor keys. Also detects the
    Nordpool Official config entry ID and price area.

    Returns:
        dict: Discovery results including found sensors, missing sensors, and
              integration metadata (device_sn, nordpool_area)
    """
    from app import bess_controller

    try:
        ha = bess_controller.ha_controller

        integrations, states = ha.discover_integrations()

        sensors: dict[str, str] = {}
        missing_sensors: list[str] = []

        if integrations["growatt_found"] and integrations["device_sn"]:
            sensors = ha.discover_growatt_sensors(integrations["device_sn"], states)
            # Identify which BESS sensor keys were not discovered
            all_bess_keys = list(ha.ENTITY_SUFFIX_MAP.values())
            missing_sensors = [k for k in all_bess_keys if k not in sensors]
        else:
            logger.warning("Growatt integration not found during setup discovery")

        current_sensors = ha.discover_current_sensors(states)
        for phase_key, entity_id in current_sensors.items():
            if phase_key not in sensors:
                sensors[phase_key] = entity_id

        # Discover optional integration sensors (Solcast, Weather, EV, etc.)
        optional_sensors = ha.discover_optional_sensors(states)
        for key, entity_id in optional_sensors.items():
            if key not in sensors:
                sensors[key] = entity_id

        # Convert top-level keys to camelCase but preserve sensor keys as
        # snake_case since they are BESS config keys, not API field names.
        detected_phase_count = (
            sum(1 for k in ("current_l1", "current_l2", "current_l3") if k in sensors)
            or None
        )
        result = convert_keys_to_camel_case(
            {
                "growatt_found": integrations["growatt_found"],
                "device_sn": integrations["device_sn"],
                "growatt_device_id": integrations["growatt_device_id"],
                "nordpool_found": integrations["nordpool_found"],
                "nordpool_area": integrations["nordpool_area"],
                "nordpool_config_entry_id": integrations["nordpool_config_entry_id"],
                "missing_sensors": missing_sensors,
                # Auto-detected hints
                "inverter_type": integrations["inverter_type"],
                "detected_phase_count": detected_phase_count,
                "currency": integrations["currency"],
                "vat_multiplier": integrations["vat_multiplier"],
            }
        )
        # Attach sensors dict without key conversion
        result["sensors"] = sensors
        return result
    except Exception as e:
        logger.error(f"Error during setup discovery: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


class ConfirmSetupPayload(BaseModel):
    """Request body for POST /api/setup/confirm."""

    sensors: dict[str, str] = {}
    nordpool_area: str | None = None
    nordpool_config_entry_id: str | None = None
    growatt_device_id: str | None = None

    @field_validator("sensors")
    @classmethod
    def validate_entity_ids(cls, sensors: dict[str, str]) -> dict[str, str]:
        for value in sensors.values():
            if value and not _ENTITY_ID_RE.match(value):
                raise ValueError(f"Invalid entity ID format: {value}")
        return sensors


@router.post("/api/setup/confirm")
async def confirm_setup(payload: ConfirmSetupPayload):
    """Persist and apply discovered sensor configuration.

    Saves the confirmed sensor mapping to /data/bess_discovered_config.json and
    applies the configuration to the running ha_controller so BESS operations
    can start immediately without a restart.

    Args:
        payload: ConfirmSetupPayload with sensors (bess_key → entity_id) and
                 optional nordpool_area, nordpool_config_entry_id, growatt_device_id

    Returns:
        dict: success confirmation
    """
    from app import bess_controller

    try:
        bess_controller.apply_discovered_config(
            sensor_map=payload.sensors,
            nordpool_area=payload.nordpool_area,
            nordpool_config_entry_id=payload.nordpool_config_entry_id,
            growatt_device_id=payload.growatt_device_id,
        )

        logger.info(f"Setup confirmed: applied {len(payload.sensors)} sensor mappings")
        return {"success": True, "applied_sensors": len(payload.sensors)}
    except Exception as e:
        logger.error(f"Error confirming setup: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/setup/complete")
async def setup_complete(payload: APISetupCompletePayload):
    """Atomic wizard completion: persist all sections and apply live.

    Called when the user finishes the 6-step setup wizard. Saves all
    sections to bess_settings.json atomically and then applies changes to the
    running system so BESS can start without a restart.
    """
    from app import bess_controller

    try:
        sections: dict = {}

        # --- sensors & discovery ---
        # Sensors go directly into sections; discovery fields (nordpool area,
        # config_entry_id, growatt device_id) are merged additively via
        # apply_discovered_config which handles its own persistence.
        if payload.sensors:
            sections["sensors"] = payload.sensors
        if (
            payload.nordpoolArea
            or payload.nordpoolConfigEntryId
            or payload.growattDeviceId
        ):
            bess_controller.apply_discovered_config(
                sensor_map={},  # sensors already in sections — avoid double-write
                nordpool_area=payload.nordpoolArea,
                nordpool_config_entry_id=payload.nordpoolConfigEntryId,
                growatt_device_id=payload.growattDeviceId,
            )

        # All sections use read-modify-write so that keys not managed by the wizard
        # (e.g. temperature_derating in battery, config_entry_id in energy_provider)
        # are preserved when save_all replaces the section.

        # --- battery ---
        if payload.totalCapacity is not None:
            battery = bess_controller.settings_store.get_section("battery")
            battery["total_capacity"] = payload.totalCapacity
            if payload.minSoc is not None:
                battery["min_soc"] = payload.minSoc
            if payload.maxSoc is not None:
                battery["max_soc"] = payload.maxSoc
            if payload.maxChargeDischargePower is not None:
                battery["max_charge_power_kw"] = payload.maxChargeDischargePower
                battery["max_discharge_power_kw"] = payload.maxChargeDischargePower
            if payload.cycleCost is not None:
                battery["cycle_cost_per_kwh"] = payload.cycleCost
            if payload.minActionProfitThreshold is not None:
                battery["min_action_profit_threshold"] = payload.minActionProfitThreshold
            sections["battery"] = battery

        # --- home ---
        if payload.currency is not None or payload.consumption is not None:
            home = bess_controller.settings_store.get_section("home")
            if payload.consumption is not None:
                home["default_hourly"] = payload.consumption
            if payload.currency is not None:
                home["currency"] = payload.currency
            if payload.consumptionStrategy is not None:
                home["consumption_strategy"] = payload.consumptionStrategy
            if payload.maxFuseCurrent is not None:
                home["max_fuse_current"] = payload.maxFuseCurrent
            if payload.voltage is not None:
                home["voltage"] = payload.voltage
            if payload.safetyMarginFactor is not None:
                home["safety_margin"] = payload.safetyMarginFactor
            if payload.phaseCount is not None:
                home["phase_count"] = payload.phaseCount
            if payload.powerMonitoringEnabled is not None:
                home["power_monitoring_enabled"] = payload.powerMonitoringEnabled
            sections["home"] = home

        # --- electricity price ---
        if payload.markupRate is not None or payload.vatMultiplier is not None:
            elec = bess_controller.settings_store.get_section("electricity_price")
            area = payload.area or payload.nordpoolArea
            if area:
                elec["area"] = area
            if payload.markupRate is not None:
                elec["markup_rate"] = payload.markupRate
            if payload.vatMultiplier is not None:
                elec["vat_multiplier"] = payload.vatMultiplier
            if payload.additionalCosts is not None:
                elec["additional_costs"] = payload.additionalCosts
            if payload.taxReduction is not None:
                elec["tax_reduction"] = payload.taxReduction
            sections["electricity_price"] = elec

        # --- energy provider ---
        if payload.provider is not None:
            ep = bess_controller.settings_store.get_section("energy_provider")
            ep["provider"] = payload.provider
            sections["energy_provider"] = ep

        # --- inverter ---
        if payload.inverterType is not None:
            inv = bess_controller.settings_store.get_section("growatt")
            inv["inverter_type"] = payload.inverterType
            if payload.growattDeviceId:
                inv["device_id"] = payload.growattDeviceId
            sections["growatt"] = inv

        # Persist all sections atomically
        bess_controller.settings_store.save_all(sections)

        # Apply settings to live system so BESS starts immediately
        # without requiring a restart.
        if payload.sensors:
            bess_controller.ha_controller.sensors.update(
                {k: v for k, v in payload.sensors.items() if v}
            )
        if payload.growattDeviceId:
            bess_controller.ha_controller.growatt_device_id = payload.growattDeviceId

        def _nn(d: dict) -> dict:
            """Strip None values so update() only overwrites explicitly provided fields."""
            return {k: v for k, v in d.items() if v is not None}

        live_updates: dict = {}
        if "battery" in sections:
            live_updates["battery"] = _nn({
                "totalCapacity": payload.totalCapacity,
                "minSoc": payload.minSoc,
                "maxSoc": payload.maxSoc,
                "maxChargePowerKw": payload.maxChargeDischargePower,
                "maxDischargePowerKw": payload.maxChargeDischargePower,
                "cycleCostPerKwh": payload.cycleCost,
                "minActionProfitThreshold": payload.minActionProfitThreshold,
            })
        if "home" in sections:
            live_updates["home"] = _nn({
                "defaultHourly": payload.consumption,
                "currency": payload.currency,
                "consumptionStrategy": payload.consumptionStrategy,
                "maxFuseCurrent": payload.maxFuseCurrent,
                "voltage": payload.voltage,
                "safetyMargin": payload.safetyMarginFactor,
                "phaseCount": payload.phaseCount,
                "powerMonitoringEnabled": payload.powerMonitoringEnabled,
            })
        if "electricity_price" in sections:
            live_updates["price"] = _nn({
                "area": sections["electricity_price"].get("area"),
                "markupRate": payload.markupRate,
                "vatMultiplier": payload.vatMultiplier,
                "additionalCosts": payload.additionalCosts,
                "taxReduction": payload.taxReduction,
            })
        if live_updates:
            bess_controller.system.update_settings(live_updates)

        # Backfill historical data in the background (may take many seconds for 20+
        # InfluxDB queries), then build the schedule with correct historical context.
        # The dashboard returns an 'initializing' response until the schedule is ready.
        def _backfill_then_schedule() -> None:
            try:
                bess_controller.system.reinitialize_historical_data()
                logger.info("Historical backfill complete after wizard setup")
            except Exception as backfill_err:
                logger.warning("Historical backfill failed after setup: %s", backfill_err)
            try:
                now = time_utils.now()
                current_period = now.hour * 4 + now.minute // 15
                bess_controller.system.update_battery_schedule(current_period=current_period)
                logger.info("Schedule built with historical data after wizard setup")
            except Exception as sched_err:
                logger.warning("Could not build schedule after backfill: %s", sched_err)

        threading.Thread(target=_backfill_then_schedule, daemon=True).start()

        # Re-run health check so the dashboard banner reflects the new configuration
        # instead of the stale failures recorded at startup (before sensors were set).
        try:
            bess_controller.system._run_health_check()
        except Exception as health_err:
            logger.warning("Could not re-run health check after setup: %s", health_err)

        logger.info(f"Setup complete: saved sections {list(sections.keys())}")
        return {"success": True, "saved_sections": list(sections.keys())}
    except Exception as e:
        logger.error(f"Error completing setup: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
