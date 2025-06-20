from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

# Import centralized utilities
from utils import convert_keys_to_snake, convert_snake_to_camel_case

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
        return convert_snake_to_camel_case(battery_settings)
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
        return convert_snake_to_camel_case(price_settings)
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
# UNIFIED DASHBOARD API ENDPOINT
############################################################################################

@router.get("/api/dashboard")
async def get_dashboard_data(date: str = Query(None)):
    """
    Unified dashboard endpoint combining schedule + daily view data.
    Returns comprehensive energy data for dashboard consumption.
    
    """
    from app import bess_controller

    try:
        daily_view = bess_controller.system.get_current_daily_view()
        battery_capacity = bess_controller.system.battery_settings.total_capacity

        actual_count = len([h for h in daily_view.hourly_data if h.data_source == "actual"])
        predicted_count = len([h for h in daily_view.hourly_data if h.data_source == "predicted"])
        logger.info(f"Dashboard API: Returning {actual_count} actual + {predicted_count} predicted hours")
        
        # Process hourly data with enhanced fields for compatibility
        hourly_data = []
        
        # Calculate totals
        total_consumption = 0
        total_solar = 0
        total_grid_import = 0
        total_grid_export = 0
        total_battery_charge = 0
        total_battery_discharge = 0
        
        for h in daily_view.hourly_data:
            # Track strategic intents
            intent = getattr(h, 'strategic_intent', 'IDLE')
            
            # Accumulate totals
            total_consumption += h.home_consumed
            total_solar += h.solar_generated
            total_grid_import += h.grid_imported
            total_grid_export += h.grid_exported
            total_battery_charge += h.battery_charged
            total_battery_discharge += h.battery_discharged
            
            # Simple energy flow estimates for enhanced functionality
            solar_to_home = min(h.solar_generated, h.home_consumed)
            solar_excess = max(0, h.solar_generated - solar_to_home)
            remaining_consumption = max(0, h.home_consumed - solar_to_home)
            
            solar_to_battery = min(solar_excess, h.battery_charged) if h.battery_charged > 0 else 0
            solar_to_grid = max(0, solar_excess - solar_to_battery)
            grid_to_home = max(0, remaining_consumption - h.battery_discharged)
            grid_to_battery = max(0, h.battery_charged - solar_to_battery)
            battery_to_home = min(h.battery_discharged, remaining_consumption) if h.battery_discharged > 0 else 0
            battery_to_grid = max(0, h.battery_discharged - battery_to_home)
            
            # Create comprehensive hourly data entry
            hour_entry = {
                # Core metadata
                "hour": h.hour,
                "data_source": h.data_source,
                "is_actual": h.data_source == "actual",
                "is_predicted": h.data_source == "predicted",
                
                # Energy flows
                "solar_generated": h.solar_generated,
                "home_consumed": h.home_consumed,
                "grid_imported": h.grid_imported,
                "grid_exported": h.grid_exported,
                "battery_charged": h.battery_charged,
                "battery_discharged": h.battery_discharged,
                
                # Detailed energy flows
                "solar_to_home": solar_to_home,
                "solar_to_battery": solar_to_battery,
                "solar_to_grid": solar_to_grid,
                "grid_to_home": grid_to_home,
                "grid_to_battery": grid_to_battery,
                "battery_to_home": battery_to_home,
                "battery_to_grid": battery_to_grid,
                
                # Battery state
                "battery_soc_start": h.battery_soc_start,
                "battery_soc_end": h.battery_soc_end,
                
                # Pricing & costs
                "buy_price": h.buy_price,
                "sell_price": h.sell_price,
                "hourly_cost": h.hourly_cost,
                "hourly_savings": h.hourly_savings,
                "battery_cycle_cost": h.battery_cycle_cost,
                
                # Control & analysis
                "battery_action": h.battery_action,
                "strategic_intent": intent,
            }
            
            hourly_data.append(hour_entry)
        
        # Calculate energy flow totals
        total_solar_to_home = sum(h["solar_to_home"] for h in hourly_data)
        total_solar_to_battery = sum(h["solar_to_battery"] for h in hourly_data)
        total_solar_to_grid = sum(h["solar_to_grid"] for h in hourly_data)
        total_grid_to_home = sum(h["grid_to_home"] for h in hourly_data)
        total_grid_to_battery = sum(h["grid_to_battery"] for h in hourly_data)
        total_battery_to_home = sum(h["battery_to_home"] for h in hourly_data)
        total_battery_to_grid = sum(h["battery_to_grid"] for h in hourly_data)
        
        # Calculate pricing statistics
        buy_prices = [h.buy_price for h in daily_view.hourly_data]
        sell_prices = [h.sell_price for h in daily_view.hourly_data]
        avg_buy_price = sum(buy_prices) / len(buy_prices) if buy_prices else 0
        avg_sell_price = sum(sell_prices) / len(sell_prices) if sell_prices else 0
        
        # Create comprehensive summary - only include values we actually calculate
        summary = {
            "base_cost": sum(h.home_consumed * h.buy_price for h in daily_view.hourly_data),
            "optimized_cost": sum(h.hourly_cost for h in daily_view.hourly_data),
            "grid_costs": total_grid_import * avg_buy_price - total_grid_export * avg_sell_price,
            "total_grid_import_cost": sum((h.grid_imported * h.buy_price) for h in daily_view.hourly_data),
            "total_grid_export_earnings": sum((h.grid_exported * h.sell_price) for h in daily_view.hourly_data),
            "battery_costs": total_battery_charge * bess_controller.system.battery_settings.cycle_cost_per_kwh,
            "savings": daily_view.total_daily_savings,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "battery_cycle_cost": total_battery_charge * bess_controller.system.battery_settings.cycle_cost_per_kwh,
        }
        
        # Create comprehensive totals
        totals = {
            "total_consumption": total_consumption,
            "total_solar": total_solar,
            "total_solar_to_home": total_solar_to_home,
            "total_solar_to_battery": total_solar_to_battery,
            "total_solar_to_grid": total_solar_to_grid,
            "total_grid_import": total_grid_import,
            "total_grid_export": total_grid_export,
            "total_grid_to_home": total_grid_to_home,
            "total_grid_to_battery": total_grid_to_battery,
            "total_battery_charge": total_battery_charge,
            "total_battery_discharge": total_battery_discharge,
            "total_battery_to_home": total_battery_to_home,
            "total_battery_to_grid": total_battery_to_grid,
            "total_charge_from_solar": total_solar_to_battery,
            "total_charge_from_grid": total_grid_to_battery,
        }
        
        # Get current battery state from controller if available
        battery_soc = 0
        battery_soe = 0
        try:
            controller = bess_controller.system.controller
            battery_soc = controller.get_battery_soc()
            battery_soe = (battery_soc / 100.0) * battery_capacity
        except Exception as e:
            logger.warning(f"Could not get current battery state: {e}")
        
        # Unified response structure
        result = {
            # Core metadata
            "date": daily_view.date.isoformat(),
            "current_hour": daily_view.current_hour,
            
            # Financial summary
            "total_daily_savings": daily_view.total_daily_savings,
            "actual_savings_so_far": daily_view.actual_savings_so_far,
            "predicted_remaining_savings": daily_view.predicted_remaining_savings,
            
            # Data structure info
            "actual_hours_count": daily_view.actual_hours_count,
            "predicted_hours_count": daily_view.predicted_hours_count,
            "data_sources": daily_view.data_sources,
            
            # Main data arrays
            "hourly_data": hourly_data,
            
            # Enhanced summaries
            "summary": summary,
            "totals": totals,
            
            # Battery info - include current state to reduce API calls
            "battery_capacity": battery_capacity,
            "battery_soc": battery_soc,
            "battery_soe": battery_soe,
        }
        
        return convert_snake_to_camel_case(result)
        
    except ValueError as e:
        # Check if this is the specific error about missing historical data
        error_msg = str(e)
        if "Missing historical data for hours" in error_msg:
            logger.warning(f"Missing historical data in dashboard request: {error_msg}")
            # Return a graceful failure response
            return {
                "error": "incomplete_data",
                "message": "Some historical data is missing. The dashboard may display incomplete information.",
                "detail": error_msg,
                "current_hour": datetime.now().hour,
                "date": datetime.now().date().isoformat(),
                "hourly_data": []  # Return empty dataset that frontend can handle
            }
        else:
            # Other ValueError errors still result in 500
            logger.error(f"ValueError in dashboard data: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
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

        # charging/discharging rates: 0 - 100%
        charge_power_rate = controller.get_charging_power_rate()
        discharge_power_rate = controller.get_discharging_power_rate()

        # charging/discharging power in watts
        battery_charge_power = controller.get_battery_charge_power()
        battery_discharge_power = controller.get_battery_discharge_power()

        grid_charge_enabled = controller.grid_charge_enabled()

        response = {
            "charge_stop_soc": battery_settings.max_soc, # percentage
            "discharge_stop_soc": battery_settings.min_soc, # percentage
            "max_charging_power": battery_settings.max_charge_power_kw * 1000, # w
            "max_discharging_power": battery_settings.max_discharge_power_kw * 1000, # w
            "battery_soc": battery_soc, # percentage
            "battery_soe": battery_soe, # kwh
            "battery_charge_power": battery_charge_power, # kw
            "battery_discharge_power": battery_discharge_power, # kw
            "charge_power_rate": charge_power_rate, # percentage
            "discharge_power_rate": discharge_power_rate, # percentage
            "grid_charge_enabled": grid_charge_enabled, # boolean
            "cycle_cost": battery_settings.cycle_cost_per_kwh, # SEK/kWh
            "timestamp": datetime.now().isoformat(),
        }

        return convert_snake_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error updating battery control settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/growatt/detailed_schedule")
async def get_growatt_detailed_schedule():
    """Get detailed Growatt-specific schedule information with hourly inverter settings."""
    from app import bess_controller
    
    try:
        system = bess_controller.system
        schedule_manager = system._schedule_manager
        current_hour = datetime.now().hour
        
        # Get TOU intervals (what's actually programmed in the inverter)
        tou_intervals = []
        daily_tou = schedule_manager.get_daily_TOU_settings()
        for interval in daily_tou:
            tou_intervals.append({
                "segment_id": interval.get("segment_id", 0),
                "start_time": interval.get("start_time", ""),
                "end_time": interval.get("end_time", ""),
                "batt_mode": interval.get("batt_mode", "load-first"),
                "enabled": interval.get("enabled", True)
            })
        
        # Get detailed hourly schedule data
        schedule_data = []
        for hour in range(24):
            hourly_settings = schedule_manager.get_hourly_settings(hour)
            
            # Get battery action from current schedule
            battery_action = 0.0
            if (system._current_schedule and 
                system._current_schedule.actions and 
                hour < len(system._current_schedule.actions)):
                battery_action = system._current_schedule.actions[hour]
            
            # Calculate charged/discharged amounts
            battery_charged = max(0, battery_action)
            battery_discharged = max(0, -battery_action)
            
            # Get SOC from current schedule state_of_energy
            battery_soc_end = 50.0  # Default
            if (system._current_schedule and 
                system._current_schedule.state_of_energy and 
                hour < len(system._current_schedule.state_of_energy)):
                # Convert kWh to percentage
                soe_kwh = system._current_schedule.state_of_energy[hour]
                battery_capacity = system.battery_settings.total_capacity
                battery_soc_end = (soe_kwh / battery_capacity) * 100
            
            schedule_data.append({
                "hour": hour,
                "strategic_intent": hourly_settings.get("strategic_intent", "IDLE"),
                "battery_action": battery_action,
                "battery_charged": battery_charged,
                "battery_discharged": battery_discharged,
                "battery_soc_end": battery_soc_end,
                "battery_mode": hourly_settings.get("batt_mode", "load-first"),
                "charge_power_rate": hourly_settings.get("charge_rate", 0),
                "discharge_power_rate": hourly_settings.get("discharge_rate", 0),
                "grid_charge": hourly_settings.get("grid_charge", False),
                "state": hourly_settings.get("state", "idle"),
                "is_actual": hour < current_hour,
                "is_predicted": hour >= current_hour,
                "data_source": "actual" if hour < current_hour else "predicted"
            })
        
        # Get strategic intent summary
        strategic_intent_summary = schedule_manager.get_strategic_intent_summary()
        
        # Get system settings
        settings = system.get_settings()
        
        response = {
            "current_time": datetime.now().isoformat(),
            "current_hour": current_hour,
            "battery_capacity": settings["battery"]["total_capacity"],
            "system_status": "online",
            "last_optimization": current_hour,
            "last_updated": datetime.now().isoformat(),
            
            # TOU intervals (actual inverter programming)
            "tou_intervals": tou_intervals,
            
            # Detailed hourly schedule with inverter settings
            "schedule_data": schedule_data,
            
            # Strategic intent summary
            "strategic_intent_summary": strategic_intent_summary,
        }
        
        return convert_snake_to_camel_case(response)
    
    except Exception as e:
        logger.error(f"Error getting detailed schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e