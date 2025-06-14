from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

# Import centralized utilities
from utils import add_camel_case_keys, convert_keys_to_snake

# Create API router
router = APIRouter()

############################################################################################
# API Endpoints for Settings  
############################################################################################

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

############################################################################################
# API Endpoints for Schedule(s)
############################################################################################

def get_enhanced_daily_view():
    """Get enhanced daily view using centralized energy flow calculations."""
    from app import bess_controller
    from core.bess.dp_battery_algorithm import calculate_detailed_energy_flows

    try:
        daily_view = bess_controller.system.get_current_daily_view()

        # Initialize totals
        total_consumption = 0
        total_solar = 0
        total_grid_import = 0
        total_grid_export = 0
        total_battery_charge = 0
        total_battery_discharge = 0
        
        # Initialize detailed flow totals
        total_solar_to_home = 0
        total_solar_to_battery = 0
        total_solar_to_grid = 0
        total_grid_to_home = 0
        total_grid_to_battery = 0
        total_battery_to_home = 0
        total_battery_to_grid = 0
        
        battery_capacity = bess_controller.system.battery_settings.total_capacity
        intent_summary = {}
        hourly_data = []
        
        # Process each hour using centralized flow calculations
        for h in daily_view.hourly_data:
            # Use centralized energy flow calculation
            flows = calculate_detailed_energy_flows(
                solar_production=h.solar_generated,
                home_consumption=h.home_consumed,
                grid_import=h.grid_imported,
                grid_export=h.grid_exported,
                battery_charged=h.battery_charged,
                battery_discharged=h.battery_discharged
            )
            
            # Accumulate basic totals
            total_consumption += flows.home_consumption
            total_solar += flows.solar_production
            total_grid_import += flows.grid_import
            total_grid_export += flows.grid_export
            total_battery_charge += flows.battery_charged
            total_battery_discharge += flows.battery_discharged
            
            # Accumulate detailed flow totals  
            total_solar_to_home += flows.solar_to_home
            total_solar_to_battery += flows.solar_to_battery
            total_solar_to_grid += flows.solar_to_grid
            total_grid_to_home += flows.grid_to_home
            total_grid_to_battery += flows.grid_to_battery
            total_battery_to_home += flows.battery_to_home
            total_battery_to_grid += flows.battery_to_grid
            
            # Track strategic intents
            strategic_intent = getattr(h, 'strategic_intent', 'IDLE')
            intent_summary[strategic_intent] = intent_summary.get(strategic_intent, 0) + 1
            
            # Create hour data with centralized flow calculations
            hour_data = {
                "hour": h.hour,
                "data_source": h.data_source,
                "home_consumption": flows.home_consumption,
                "consumption": flows.home_consumption,
                "solar_production": flows.solar_production,
                "grid_import": flows.grid_import,
                "grid_export": flows.grid_export,
                "battery_charged": flows.battery_charged,
                "battery_discharged": flows.battery_discharged,
                "battery_level": h.battery_soc_end,
                "buy_price": h.buy_price,
                "sell_price": h.sell_price,
                "hourly_cost": h.hourly_cost,
                "hourly_savings": h.hourly_savings,
                "battery_action": h.battery_action,
                "strategic_intent": strategic_intent,                
                "battery_cycle_cost": h.battery_cycle_cost,
                
                # All detailed flows from centralized calculation
                "solar_to_home": flows.solar_to_home,
                "solar_to_battery": flows.solar_to_battery,
                "solar_to_grid": flows.solar_to_grid,
                "grid_to_home": flows.grid_to_home,
                "grid_to_battery": flows.grid_to_battery,
                "battery_to_home": flows.battery_to_home,
                "battery_to_grid": flows.battery_to_grid,
                
                # Legacy field names for backward compatibility
                "direct_solar": flows.solar_to_home,
                "export_solar": flows.solar_to_grid,
                "solar_charged": flows.solar_to_battery,
                "is_actual": h.data_source == "actual",
                "is_predicted": h.data_source == "predicted",
            }
            hourly_data.append(hour_data)

        # Create summary and totals with centralized calculations
        avg_buy_price = sum(h.buy_price for h in daily_view.hourly_data) / len(daily_view.hourly_data)
        avg_sell_price = sum(h.sell_price for h in daily_view.hourly_data) / len(daily_view.hourly_data)        
        # Calculate base cost (grid-only scenario cost for comparison)
        base_cost = sum(h.home_consumed * h.buy_price for h in daily_view.hourly_data)

        summary = {
            "total_solar": total_solar,
            "total_grid_import": total_grid_import,
            "total_grid_export": total_grid_export,
            "total_battery_charge": total_battery_charge,
            "total_battery_discharge": total_battery_discharge,
            "cycle_count": total_battery_discharge / battery_capacity,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "total_consumption": total_consumption,
            "total_solar_to_home": total_solar_to_home,
            "total_solar_to_battery": total_solar_to_battery,
            "total_solar_to_grid": total_solar_to_grid,
            "total_grid_to_home": total_grid_to_home,
            "total_grid_to_battery": total_grid_to_battery,
            "total_battery_to_home": total_battery_to_home,
            "total_battery_to_grid": total_battery_to_grid,
            "total_charge_from_solar": total_solar_to_battery,
            "total_charge_from_grid": total_grid_to_battery,
            "estimated_battery_cycles": total_battery_discharge / battery_capacity,
            "base_cost": base_cost,
        }

        totals = {
            "total_solar": total_solar,
            "total_consumption": total_consumption,
            "total_grid_import": total_grid_import,
            "total_grid_export": total_grid_export,
            "total_battery_charged": total_battery_charge,
            "total_battery_discharged": total_battery_discharge,
            "total_solar_to_home": total_solar_to_home,
            "total_solar_to_battery": total_solar_to_battery,
            "total_solar_to_grid": total_solar_to_grid,
            "total_grid_to_home": total_grid_to_home,
            "total_grid_to_battery": total_grid_to_battery,
            "total_battery_to_home": total_battery_to_home,
            "total_battery_to_grid": total_battery_to_grid,
            "cycle_count": total_battery_discharge / battery_capacity,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "total_charge_from_solar": total_solar_to_battery,
            "total_charge_from_grid": total_grid_to_battery,
            "estimated_battery_cycles": total_battery_discharge / battery_capacity,
        }

        result = {
            "date": daily_view.date.isoformat(),
            "current_hour": daily_view.current_hour,
            "total_daily_savings": daily_view.total_daily_savings,
            "actual_savings_so_far": daily_view.actual_savings_so_far,
            "predicted_remaining_savings": daily_view.predicted_remaining_savings,
            "actual_hours_count": daily_view.actual_hours_count,
            "predicted_hours_count": daily_view.predicted_hours_count,
            "data_sources": daily_view.data_sources,
            "hourly_data": hourly_data,
            "summary": summary,
            "enhanced_summary": summary,
            "totals": totals,
            "strategic_intent_summary": intent_summary,
            "battery_capacity": battery_capacity,
            "energy_profile": {
                "consumption": [h["consumption"] for h in hourly_data],
                "solar": [h["solar_production"] for h in hourly_data],
                "battery_soc": [h["battery_level"] for h in hourly_data],
                "actual_hours": daily_view.actual_hours_count,
            },
        }

        return add_camel_case_keys(result)

    except Exception as e:
        logger.error(f"Error getting daily view v2: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
    

@router.get("/api/schedule/detailed")
async def get_detailed_schedule():
    """Get detailed battery schedule data."""    
    return get_enhanced_daily_view()

@router.get("/api/schedule")
async def get_battery_schedule(date: str = Query(None)):
    """Get battery schedule data for dashboard."""    
    return get_enhanced_daily_view()
        
@router.get("/api/schedule/current")
async def get_current_schedule():
    """Get the current active battery schedule."""
    return get_enhanced_daily_view()

############################################################################################
# API Endpoints for Report(s)
############################################################################################

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


############################################################################################
# API Endpoints for Growatt inverter (s)
############################################################################################

@router.get("/api/growatt/inverter_status")
async def get_inverter_status():
    """Get comprehensive real-time inverter status data."""
    from app import bess_controller

    try:
        controller = bess_controller.system.controller
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