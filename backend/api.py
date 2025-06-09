from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

# Import centralized utilities
from utils import add_camel_case_keys, convert_keys_to_snake

# Create API router
router = APIRouter()


@router.get("/api/settings/battery")
async def get_battery_settings():
    """Get current battery settings."""
    from app import bess_controller

    try:
        settings = bess_controller.system.get_settings()
        battery_settings = settings["battery"].copy()
        battery_settings["estimated_consumption"] = settings["home"]["default_hourly"]
        
        # Apply camelCase conversion for API
        return add_camel_case_keys(battery_settings)
    except Exception as e:
        logger.error(f"Error getting battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/settings/battery")
async def update_battery_settings(settings: dict):
    """Update battery settings."""
    from app import bess_controller

    try:
        # Convert camelCase keys to snake_case
        snake_settings = convert_keys_to_snake(settings)
        bess_controller.system.update_settings({"battery": snake_settings})
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
        price_settings = settings["price"]
        
        # Apply camelCase conversion
        return add_camel_case_keys(price_settings)
    except Exception as e:
        logger.error(f"Error getting electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/settings/electricity")
async def update_electricity_price_settings(settings: dict):
    """Update electricity price settings."""
    from app import bess_controller

    try:
        # Convert camelCase keys to snake_case
        snake_settings = convert_keys_to_snake(settings)
        bess_controller.system.update_settings({"price": snake_settings})
        return {"message": "Electricity settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/schedule/detailed")
async def get_detailed_schedule():
    """Get detailed battery schedule data."""
    from app import bess_controller
    
    try:
        schedule_data = bess_controller.system.get_current_schedule()
        if not schedule_data:
            logger.info("No current schedule found, running optimization")
            success = bess_controller.system.update_battery_schedule(hour=datetime.now().hour)
            if success:
                schedule_data = bess_controller.system.get_current_schedule()
            
        if not schedule_data:
            raise HTTPException(status_code=500, detail="Failed to get schedule")

        return add_camel_case_keys(schedule_data)
    except Exception as e:
        logger.error(f"Error getting detailed schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/schedule")
async def get_battery_schedule(date: str = Query(None)):
    """Get battery schedule data for dashboard."""
    from app import bess_controller
    
    try:
        if date and date != datetime.now().date().isoformat():
            raise HTTPException(status_code=400, detail="Date-specific schedules not yet supported")
        
        schedule_data = bess_controller.system.get_current_schedule()
        if not schedule_data:
            logger.info("No current schedule found, running optimization")
            success = bess_controller.system.update_battery_schedule(hour=datetime.now().hour)
            if success:
                schedule_data = bess_controller.system.get_current_schedule()
                
        if not schedule_data:
            raise HTTPException(status_code=500, detail="Failed to get schedule")
            
        return add_camel_case_keys(schedule_data)
    except Exception as e:
        logger.error(f"Error getting battery schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
        

@router.get("/api/schedule/current")
async def get_current_schedule():
    """Get the current active battery schedule."""
    from app import bess_controller

    try:
        if bess_controller.system._current_schedule is not None:
            current_hour = datetime.now().hour
            schedule_data = bess_controller.system._current_schedule.get_schedule_data()
            tou_intervals = bess_controller.system._schedule_manager.get_daily_TOU_settings()

            response = {
                "current_hour": current_hour,
                "schedule": schedule_data,
                "tou_intervals": tou_intervals,
            }
            
            return add_camel_case_keys(response)
        else:
            raise HTTPException(status_code=404, detail="No current schedule available")
    except Exception as e:
        logger.error(f"Error getting current schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/energy/balance")
async def get_energy_balance():
    """Get energy balance for the day."""
    from app import bess_controller

    try:
        hourly_data, totals = bess_controller.system.log_energy_flows_api()

        # Convert to serializable format
        hourly_data_serializable = []
        for data in hourly_data:
            serializable_item = {}
            for k, v in data.items():
                serializable_item[k] = float(v) if isinstance(v, float | int) else v
            hourly_data_serializable.append(serializable_item)

        totals_serializable = {}
        for k, v in totals.items():
            totals_serializable[k] = float(v) if isinstance(v, float | int) else v

        result = {
            "hourly_data": hourly_data_serializable, 
            "totals": totals_serializable
        }

        return add_camel_case_keys(result)
    except Exception as e:
        logger.error(f"Error getting energy balance: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/energy/profile")
async def get_energy_profile(
    current_hour: int = Query(None, description="Current hour (0-23)")
):
    """Get the full energy profile."""
    from app import bess_controller

    try:
        if current_hour is None:
            current_hour = datetime.now().hour

        profile = bess_controller.system.get_full_day_energy_profile(current_hour)

        # Convert numpy arrays to Python lists if needed
        for key in profile:
            if hasattr(profile[key], "tolist"):
                profile[key] = profile[key].tolist()

        return add_camel_case_keys(profile)
    except Exception as e:
        logger.error(f"Error getting energy profile: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/v2/daily_view")
async def get_daily_view_v2():
    """Get daily view with historical data."""
    from app import bess_controller

    try:
        daily_view = bess_controller.system.get_current_daily_view()

        actual_count = len([h for h in daily_view.hourly_data if h.data_source == "actual"])
        predicted_count = len([h for h in daily_view.hourly_data if h.data_source == "predicted"])
        logger.info(f"Returning {actual_count} actual + {predicted_count} predicted hours")

        # Convert DailyView to dict
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
                    "buy_price": h.buy_price,
                    "sell_price": h.sell_price,
                    "electricity_price": h.buy_price,  # Add for frontend compatibility
                    "hourly_cost": h.hourly_cost,
                    "hourly_savings": h.hourly_savings,
                    "battery_action": h.battery_action,
                    "is_actual": h.data_source == "actual",
                    "is_predicted": h.data_source == "predicted",
                }
                for h in daily_view.hourly_data
            ],
        }

        return add_camel_case_keys(result)

    except Exception as e:
        logger.error(f"Error getting daily view v2: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/inverter_status")
async def get_inverter_status():
    """Get comprehensive real-time inverter status data."""
    from app import bess_controller

    try:
        controller = bess_controller.system._controller
        battery_settings = bess_controller.system.battery_settings

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
            "grid_charge_enabled": grid_charge_enabled,
            "charge_stop_soc": 100.0,
            "discharge_stop_soc": battery_settings.min_soc,
            "discharge_power_rate": discharge_power_rate,
            "max_charging_power": battery_settings.max_charge_power_kw * 1000,
            "max_discharging_power": battery_settings.max_discharge_power_kw * 1000,
            "timestamp": datetime.now().isoformat(),
        }

        return add_camel_case_keys(response)

    except Exception as e:
        logger.error("Error getting inverter status: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/detailed_schedule")
async def get_growatt_detailed_schedule():
    """Get detailed Growatt-specific schedule information."""
    from app import bess_controller
    
    try:
        schedule_manager = bess_controller.system._schedule_manager
        current_hour = datetime.now().hour

        tou_intervals = schedule_manager.get_daily_TOU_settings()

        # Get strategic intent summary
        intent_distribution = {}
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
                battery_mode = hourly_settings.get("batt_mode", "load-first")
                mode_distribution[battery_mode] = mode_distribution.get(battery_mode, 0) + 1
                
                strategic_intent = hourly_settings.get("strategic_intent", "IDLE")
                
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
                else:
                    action = "IDLE"
                    action_color = "gray"
                    idle_hours += 1

                # Get price for this hour
                price = 1.0
                try:
                    if hasattr(bess_controller.system, "price_manager"):
                        price_entries = bess_controller.system.price_manager.get_today_prices()
                        if price_entries and hour < len(price_entries):
                            price = price_entries[hour].get("buyPrice", 1.0)
                except Exception as e:
                    logger.warning(f"Failed to get price for hour {hour}: {e}")

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
                    "soc": 50.0,
                    "price": price,
                    "electricity_price": price,  # Add this for frontend compatibility
                    "grid_power": 0,
                    "is_current": hour == current_hour
                })

            except Exception as e:
                logger.error(f"Error processing hour {hour}: {e}")
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
                    "electricity_price": 1.0,
                    "grid_power": 0,
                    "is_current": hour == current_hour
                })
                idle_hours += 1

        response = {
            "current_hour": current_hour,
            "tou_intervals": tou_intervals,
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

        return add_camel_case_keys(response)

    except Exception as e:
        logger.error(f"Error in get_growatt_detailed_schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e