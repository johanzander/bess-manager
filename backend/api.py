from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

# Import utilities
from utils import add_camel_case_keys

# Create API router
router = APIRouter()


@router.get("/status")
def get_status():
    """Get API status."""
    from app import INGRESS_PREFIX
    return {"status": "ok", "ingress_prefix": INGRESS_PREFIX}


@router.get("/api/settings/battery")
async def get_battery_settings():
    """Get current battery settings."""
    from app import bess_controller
    
    try:
        settings = bess_controller.system.get_settings()
        # Ensure estimatedConsumption is included from consumption settings
        battery_settings = settings["battery"]
        battery_settings["estimatedConsumption"] = settings["consumption"][
            "defaultHourly"
        ]
        return battery_settings
    except Exception as e:
        logger.error(f"Error getting battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/settings/battery")
async def update_battery_settings(settings: dict):
    """Update battery settings."""
    from app import bess_controller
    
    try:
        bess_controller.system.update_settings({"battery": settings})
        return {"message": "Battery settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/settings/electricity")
async def get_electricity_price_settings():
    """Get current electricity price settings."""
    from app import bess_controller
    
    try:
        settings = bess_controller.system.get_settings()
        # Convert to old format for API compatibility
        return {
            "area": settings["price"]["area"],
            "markupRate": settings["price"]["markupRate"],
            "vatMultiplier": settings["price"]["vatMultiplier"],
            "additionalCosts": settings["price"]["additionalCosts"],
            "taxReduction": settings["price"]["taxReduction"],
        }
    except Exception as e:
        logger.error(f"Error getting electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/settings/electricity")
async def update_electricity_price_settings(settings: dict):
    """Update electricity price settings."""
    from app import bess_controller
    
    try:
        # Convert from old format to new
        new_settings = {
            "price": {
                "area": settings["area"],
                "markupRate": settings["markupRate"],
                "vatMultiplier": settings["vatMultiplier"],
                "additionalCosts": settings["additionalCosts"],
                "taxReduction": settings["taxReduction"],
            }
        }

        bess_controller.system.update_settings(new_settings)
        return {"message": "Electricity settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/schedule")
async def get_battery_schedule(
    date: str = Query(None, description="Date in YYYY-MM-DD format"),
):
    """Get battery schedule data for dashboard with enhanced reporting."""
    from app import bess_controller
    
    try:
        target_date = (
            datetime.strptime(date, "%Y-%m-%d").date()
            if date
            else datetime.now().date()
        )
        logger.info(f"Generating schedule for {target_date}")

        # Create the optimized schedule
        schedule = bess_controller.system.create_schedule(price_date=target_date)

        # Get the enhanced schedule data with all three scenarios
        schedule_data = schedule.get_schedule_data()

        # Add camelCase keys for frontend compatibility
        enhanced_data = add_camel_case_keys(schedule_data)

        # Add hourlyData field directly for better frontend compatibility
        if "hourly_data" in enhanced_data:
            enhanced_data["hourlyData"] = enhanced_data["hourly_data"]

        logger.info(f"Schedule data generated successfully for {target_date}")

        return enhanced_data
    except Exception as e:
        logger.error(f"Error getting battery schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/schedule/detailed")
async def get_detailed_schedule():
    """Get detailed battery schedule data directly from the current schedule report."""
    from app import bess_controller
    
    try:
        # Get the current schedule
        current_schedule = bess_controller.system._current_schedule

        if not current_schedule:
            logger.info("No current schedule found, creating a new schedule")
            # Create a new schedule if one doesn't exist
            current_schedule = bess_controller.system.create_schedule()
            if not current_schedule:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to create a new schedule",
                )

        # Get the schedule data - this contains the hourly data and summary directly from the report
        schedule_data = current_schedule.get_schedule_data()

        # Add camelCase versions of all keys
        enhanced_data = add_camel_case_keys(schedule_data)

        # Add hourlyData field directly for better frontend compatibility
        if "hourly_data" in enhanced_data:
            enhanced_data["hourlyData"] = enhanced_data["hourly_data"]

        # Return the enhanced data with both snake_case and camelCase keys
        return enhanced_data
    except Exception as e:
        logger.error(f"Error getting detailed schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/schedule/current")
async def get_current_schedule():
    """Get the current active battery schedule."""
    from app import bess_controller
    
    try:
        if bess_controller.system._current_schedule is not None:
            current_hour = datetime.now().hour
            schedule_data = bess_controller.system._current_schedule.get_schedule_data()
            tou_intervals = (
                bess_controller.system._schedule_manager.get_daily_TOU_settings()
            )

            # Process the data to add camelCase keys
            enhanced_schedule = add_camel_case_keys(schedule_data)
            enhanced_tou = add_camel_case_keys(tou_intervals)

            # Add direct hourlyData reference for convenience
            if "hourly_data" in enhanced_schedule:
                enhanced_schedule["hourlyData"] = enhanced_schedule["hourly_data"]

            return {
                "current_hour": current_hour,
                "currentHour": current_hour,  # Also add camelCase for consistency
                "schedule": enhanced_schedule,
                "tou_intervals": enhanced_tou,
                "touIntervals": enhanced_tou,  # Also add camelCase for consistency
            }
        else:
            raise HTTPException(status_code=404, detail="No current schedule available")
    except Exception as e:
        logger.error(f"Error getting current schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/predictions/consumption")
async def get_consumption_predictions():
    """Get hourly consumption predictions for the next 24 hours."""
    from app import bess_controller
    
    try:
        predictions = (
            bess_controller.system._energy_manager.get_consumption_predictions()
        )
        return {"data": [float(val) for val in predictions]}
    except Exception as e:
        logger.error(f"Error getting consumption predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/report/daily_savings")
async def get_daily_savings_report():
    """Get the daily savings report with detailed energy analysis."""
    from app import bess_controller
    
    try:
        # Use the FIXED method with economic scenarios
        report = bess_controller.system.get_daily_savings_report()

        # Add camelCase keys for frontend compatibility
        enhanced_report = add_camel_case_keys(report)

        return enhanced_report
    except ValueError as e:
        logger.warning(f"No daily savings report available: {e}")
        raise HTTPException(
            status_code=404, detail="No current schedule available"
        ) from e
    except Exception as e:
        logger.error(f"Error generating daily savings report: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/energy/balance")
async def get_energy_balance():
    """Get energy balance for the day."""
    from app import bess_controller
    
    try:
        # Use the FIXED method
        hourly_data, totals = bess_controller.system.log_energy_flows_api()

        # Convert to serializable format and add camelCase
        hourly_data_serializable = []
        for data in hourly_data:
            serializable_item = {}
            for k, v in data.items():
                serializable_item[k] = float(v) if isinstance(v, float | int) else v
            hourly_data_serializable.append(serializable_item)

        totals_serializable = {}
        for k, v in totals.items():
            totals_serializable[k] = float(v) if isinstance(v, float | int) else v

        result = {"hourlyData": hourly_data_serializable, "totals": totals_serializable}

        # Add camelCase compatibility
        enhanced_result = add_camel_case_keys(result)

        return enhanced_result
    except Exception as e:
        logger.error(f"Error getting energy balance: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/energy/profile")
async def get_energy_profile(
    current_hour: int = Query(None, description="Current hour (0-23)")
):
    """Get the full energy profile combining historical and predicted data."""
    from app import bess_controller
    
    try:
        # Use current hour if not specified
        if current_hour is None:
            current_hour = datetime.now().hour

        profile = bess_controller.system.get_full_day_energy_profile(current_hour)

        # Convert numpy arrays to Python lists if needed
        for key in profile:
            if hasattr(profile[key], "tolist"):
                profile[key] = profile[key].tolist()

        return profile
    except Exception as e:
        logger.error(f"Error getting energy profile: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/system/health")
async def get_system_health():
    """Get system health check results."""
    from app import bess_controller
    from core.bess.health_check import run_system_health_checks
    
    try:
        health_results = run_system_health_checks(bess_controller.system)
        return health_results
    except Exception as e:
        logger.error(f"Error running health checks: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/v2/daily_view")
async def get_daily_view_v2():
    """FIXED: Ensure historical data is properly included."""
    from app import bess_controller
    
    try:
        daily_view = bess_controller.system.get_current_daily_view()

        # ADDED: Log what we're returning for debugging
        actual_count = len(
            [h for h in daily_view.hourly_data if h.data_source == "actual"]
        )
        predicted_count = len(
            [h for h in daily_view.hourly_data if h.data_source == "predicted"]
        )
        logger.info(
            f"/api/v2/daily_view/ returning {actual_count} actual + {predicted_count} predicted hours"
        )

        # Convert DailyView to JSON-serializable format
        result = {
            "date": daily_view.date.isoformat(),
            "current_hour": daily_view.current_hour,
            "total_daily_savings": daily_view.total_daily_savings,
            "actual_savings_so_far": daily_view.actual_savings_so_far,
            "predicted_remaining_savings": daily_view.predicted_remaining_savings,
            "actual_hours_count": daily_view.actual_hours_count,
            "predicted_hours_count": daily_view.predicted_hours_count,
            "data_sources": daily_view.data_sources,
            "hourly_data": [
                {
                    "hour": h.hour,
                    "data_source": h.data_source,
                    "solar_generated": h.solar_generated,
                    "home_consumed": h.home_consumed,
                    "grid_imported": h.grid_imported,
                    "grid_exported": h.grid_exported,
                    "battery_charged": h.battery_charged,
                    "battery_discharged": h.battery_discharged,
                    "battery_soc_start": h.battery_soc_start,
                    "battery_soc_end": h.battery_soc_end,
                    "electricity_price": h.buy_price, #TODO: REMOVE
                    "buy_price": h.buy_price,
                    "sell_price": h.sell_price,
                    "price": h.buy_price, # TODO: REMOVE
                    "hourly_cost": h.hourly_cost,
                    "hourly_savings": h.hourly_savings,
                    "battery_action": h.battery_action,
                    # ADDED: Explicit indicators for frontend
                    "is_actual": h.data_source == "actual",
                    "is_predicted": h.data_source == "predicted",
                }
                for h in daily_view.hourly_data
            ],
        }

        # Add camelCase compatibility
        enhanced_result = add_camel_case_keys(result)

        return enhanced_result

    except Exception as e:
        logger.error(f"Error getting daily view v2: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/tou_settings")
async def get_tou_settings():
    """Get current TOU (Time of Use) settings with strategic intent information."""
    from app import bess_controller
    
    logger.info("/api/growatt/tou_settings")

    try:
        schedule_manager = bess_controller.system._schedule_manager
        tou_intervals = schedule_manager.get_daily_TOU_settings()
        current_hour = datetime.now().hour

        # Enhanced TOU intervals with hourly settings and strategic intents
        enhanced_tou_intervals = []
        for interval in tou_intervals:
            enhanced_interval = interval.copy()
            start_hour = int(interval["start_time"].split(":")[0])
            settings = schedule_manager.get_hourly_settings(start_hour)
            enhanced_interval["grid_charge"] = settings["grid_charge"]
            enhanced_interval["discharge_rate"] = settings["discharge_rate"]
            enhanced_interval["strategic_intent"] = settings.get(
                "strategic_intent", "IDLE"
            )

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

        # Build hourly settings for complete day with strategic intents
        hourly_settings = []
        for hour in range(24):
            settings = schedule_manager.get_hourly_settings(hour)
            # Find battery mode for this hour
            battery_mode = "load-first"  # Default
            for interval in tou_intervals:
                start_hour = int(interval["start_time"].split(":")[0])
                end_hour = int(interval["end_time"].split(":")[0])
                if start_hour <= hour <= end_hour and interval["enabled"]:
                    battery_mode = interval["batt_mode"]
                    break

            # Add to hourly settings
            hourly_settings.append(
                {
                    "hour": hour,
                    "battery_mode": battery_mode,
                    "grid_charge": settings["grid_charge"],
                    "discharge_rate": settings["discharge_rate"],
                    "state": settings["state"],
                    "strategic_intent": settings.get("strategic_intent", "IDLE"),
                    "battery_action": settings.get("battery_action", 0.0),
                    "is_current": hour == current_hour,
                }
            )

        # Get strategic intent summary if available
        strategic_summary = schedule_manager.get_strategic_intent_summary()

        response = {
            "status": "ok",
            "tou_intervals": enhanced_tou_intervals,
            "hourly_settings": hourly_settings,
            "current_hour": current_hour,
            "strategic_summary": strategic_summary,
            "timestamp": datetime.now().isoformat(),
        }

        return response

    except Exception as e:
        logger.error("Error getting TOU settings: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/inverter_status")
async def get_inverter_status():
    """Get comprehensive real-time inverter status data."""
    from app import bess_controller

    try:
        controller = bess_controller.system._controller
        battery_settings = bess_controller.system.battery_settings

        # Get core data
        battery_soc = controller.get_battery_soc()
        battery_soe = (battery_soc / 100.0) * battery_settings.total_capacity
        grid_charge_enabled = controller.grid_charge_enabled()
        discharge_power_rate = controller.get_discharging_power_rate()

        logger.info(
            f"Current battery status: SOC={battery_soc:.1f}%, SOE={battery_soe:.1f} kWh, GridCharge={grid_charge_enabled}, DischargeRate={discharge_power_rate}%"
        )

        # Get power values with error handling
        battery_charge_power = controller.get_battery_charge_power()
        battery_discharge_power = controller.get_battery_discharge_power()

        response = {
            "battery_soc": battery_soc,
            "battery_soe": battery_soe,
            "battery_charge_power": battery_charge_power,
            "battery_discharge_power": battery_discharge_power,
            "grid_charge_enabled": grid_charge_enabled,
            "charge_stop_soc": 100.0,
            "discharge_stop_soc": battery_settings.min_soc,
            "discharge_power_rate": discharge_power_rate,
            "max_charging_power": battery_settings.max_charge_power_kw * 1000,
            "max_discharging_power": battery_settings.max_discharge_power_kw * 1000,
            "timestamp": datetime.now().isoformat(),
        }

        return response

    except Exception as e:
        logger.error("Error getting inverter status: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/detailed_schedule")
async def get_growatt_detailed_schedule():
    """Get detailed Growatt-specific schedule information with strategic intents."""
    from app import bess_controller

    try:
        schedule_manager = bess_controller.system._schedule_manager
        current_hour = datetime.now().hour

        # Get TOU intervals directly from schedule manager
        try:
            tou_intervals = schedule_manager.get_daily_TOU_settings()
        except Exception as e:
            logger.error(f"Failed to get TOU intervals: {e}")
            tou_intervals = []

        # Get strategic intent summary directly from the schedule manager
        intent_distribution = {}
        try:
            strategic_summary = schedule_manager.get_strategic_intent_summary()
            for intent, data in strategic_summary.items():
                intent_distribution[intent] = data.get("count", 0)
        except Exception as e:
            logger.error(f"Failed to get strategic intent summary: {e}")

        # Build hourly schedule data using the schedule manager's existing data
        schedule_data = []
        charge_hours = 0
        discharge_hours = 0
        idle_hours = 0
        mode_distribution = {}

        for hour in range(24):
            try:
                # Get hourly settings directly from schedule manager
                hourly_settings = schedule_manager.get_hourly_settings(hour)
                
                # Find battery mode for this hour
                battery_mode = hourly_settings.get("batt_mode", "load-first")
                
                # Track mode distribution
                mode_distribution[battery_mode] = mode_distribution.get(battery_mode, 0) + 1
                
                # Get strategic intent
                strategic_intent = hourly_settings.get("strategic_intent", "IDLE")
                
                # Determine action and color based on strategic intent
                if strategic_intent == "GRID_CHARGING":
                    action = "GRID_CHARGE"
                    action_color = "blue"
                    charge_hours += 1
                elif strategic_intent == "SOLAR_STORAGE":
                    action = "SOLAR_CHARGE"
                    action_color = "green"
                    charge_hours += 1
                elif strategic_intent == "LOAD_SUPPORT":
                    action = "DISCHARGE"
                    action_color = "orange"
                    discharge_hours += 1
                elif strategic_intent == "EXPORT_ARBITRAGE":
                    action = "EXPORT"
                    action_color = "red"
                    discharge_hours += 1
                else:  # IDLE
                    action = "IDLE"
                    action_color = "gray"
                    idle_hours += 1

                # Get price for this hour
                price = 1.0  # Default fallback
                try:
                    if hasattr(bess_controller.system, "price_manager"):
                        price_entries = bess_controller.system.price_manager.get_today_prices()
                        if price_entries and hour < len(price_entries):
                            price = price_entries[hour].get("buyPrice", 1.0)
                except Exception as e:
                    logger.warning(f"Failed to get price for hour {hour}: {e}")

                # Add hour data to response
                schedule_data.append({
                    "hour": hour,
                    "mode": hourly_settings.get("state", "idle"),
                    "battery_mode": battery_mode,
                    "grid_charge": hourly_settings.get("grid_charge", False),
                    "discharge_rate": hourly_settings.get("discharge_rate", 0),
                    "charge_rate": hourly_settings.get("charge_rate", 0),
                    "state": hourly_settings.get("state", "idle"),
                    "strategic_intent": strategic_intent,
                    "action": action,
                    "action_color": action_color,
                    "battery_action": hourly_settings.get("battery_action", 0.0),
                    "battery_action_kw": hourly_settings.get("battery_action_kw", 0.0),
                    "soc": 50.0,  # Placeholder, could get from daily view if needed
                    "price": price,
                    "grid_power": 0,
                    "is_current": hour == current_hour
                })

            except Exception as e:
                logger.error(f"Error processing hour {hour}: {e}")
                # Add minimal data for this hour to avoid breaking the frontend
                schedule_data.append({
                    "hour": hour,
                    "mode": "idle",
                    "battery_mode": "load-first",
                    "grid_charge": False,
                    "discharge_rate": 0,
                    "state": "idle",
                    "strategic_intent": "IDLE",
                    "action": "IDLE",
                    "action_color": "gray",
                    "battery_action": 0.0,
                    "soc": 50.0,
                    "price": 1.0,
                    "grid_power": 0,
                    "is_current": hour == current_hour
                })
                idle_hours += 1

        # Enhanced TOU intervals with strategic intent information
        enhanced_tou_intervals = []
        for interval in tou_intervals:
            try:
                enhanced_interval = interval.copy()
                start_hour = int(interval["start_time"].split(":")[0])
                settings = schedule_manager.get_hourly_settings(start_hour)
                
                enhanced_interval["grid_charge"] = settings.get("grid_charge", False)
                enhanced_interval["discharge_rate"] = settings.get("discharge_rate", 0)
                enhanced_interval["strategic_intent"] = settings.get("strategic_intent", "IDLE")
                enhanced_tou_intervals.append(enhanced_interval)
            except Exception as e:
                logger.error(f"Error processing TOU interval: {e}")
                continue

        # Build final response
        response = {
            "current_hour": current_hour,
            "tou_intervals": enhanced_tou_intervals,
            "schedule_data": schedule_data,
            "last_updated": datetime.now().isoformat(),
            "summary": {
                "charge_hours": charge_hours,
                "discharge_hours": discharge_hours,
                "idle_hours": idle_hours,
                "active_hours": charge_hours + discharge_hours,
                "mode_distribution": mode_distribution,
                "intent_distribution": intent_distribution,
                "efficiency_metrics": {
                    "utilization_rate": (charge_hours + discharge_hours) / 24 * 100,
                    "charge_discharge_ratio": charge_hours / max(discharge_hours, 1),
                },
            },
        }

        return response

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(
            f"Unexpected error in get_growatt_detailed_schedule: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {e!s}"
        ) from e


@router.get("/api/growatt/strategic_intents")
async def get_strategic_intents():
    """Get strategic intent information for the current schedule."""
    from app import bess_controller
    
    try:
        schedule_manager = bess_controller.system._schedule_manager

        # Get strategic intent summary
        strategic_summary = {}
        if hasattr(schedule_manager, "get_strategic_intent_summary"):
            strategic_summary = schedule_manager.get_strategic_intent_summary()

        # Get hourly strategic intents
        hourly_intents = []
        for hour in range(24):
            settings = schedule_manager.get_hourly_settings(hour)
            intent = settings.get("strategic_intent", "IDLE")
            description = (
                schedule_manager._get_intent_description(intent)
                if hasattr(schedule_manager, "_get_intent_description")
                else "No description available"
            )

            hourly_intents.append(
                {
                    "hour": hour,
                    "intent": intent,
                    "description": description,
                    "battery_action": settings.get("battery_action", 0.0),
                    "grid_charge": settings["grid_charge"],
                    "discharge_rate": settings["discharge_rate"],
                }
            )

        return {
            "strategic_summary": strategic_summary,
            "hourly_intents": hourly_intents,
            "current_hour": datetime.now().hour,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting strategic intents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
