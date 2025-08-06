"""Updated API endpoints using canonical camelCase dataclasses."""

from datetime import datetime

from api_conversion import convert_keys_to_camel_case
from api_dataclasses import APIBatterySettings, APIPriceSettings
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

router = APIRouter()


@router.get("/api/settings/battery")
async def get_battery_settings():
    """Get current battery settings using unified conversion."""
    from app import bess_controller

    try:
        settings = bess_controller.system.get_settings()
        battery_settings = settings["battery"]
        estimated_consumption = settings["home"].default_hourly
        
        # Create APIBatterySettings using existing method (maintains compatibility)
        api_settings = APIBatterySettings.from_internal(battery_settings, estimated_consumption)
        return api_settings.__dict__
        
    except Exception as e:
        logger.error(f"Error getting battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/settings/battery")
async def update_battery_settings(settings: dict):
    """Update battery settings from canonical camelCase input."""
    from app import bess_controller

    try:
        api_settings = APIBatterySettings(**settings)
        internal_updates = api_settings.to_internal_update()
        bess_controller.system.update_settings({"battery": internal_updates})
        return {"message": "Battery settings updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/settings/electricity")
async def get_electricity_price_settings():
    """Get current electricity price settings in canonical camelCase format."""
    from app import bess_controller

    try:
        settings = bess_controller.system.get_settings()
        price_settings = settings["price"]
        
        api_settings = APIPriceSettings.from_internal(price_settings)
        return api_settings.__dict__
        
    except Exception as e:
        logger.error(f"Error getting electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/settings/electricity")
async def update_electricity_price_settings(settings: dict):
    """Update electricity price settings from canonical camelCase input."""
    from app import bess_controller

    try:
        api_settings = APIPriceSettings(**settings)
        internal_updates = api_settings.to_internal_update()
        bess_controller.system.update_settings({"price": internal_updates})
        return {"message": "Electricity settings updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/dashboard")
async def get_dashboard_data(date: str = Query(None)):
    """Unified dashboard endpoint returning canonical camelCase data directly."""
    # Import at function level to avoid circular imports
    from api_dataclasses import flatten_hourly_data
    
    from app import bess_controller

    try:
        logger.debug("Starting dashboard data retrieval")
        
        # Get daily view data
        daily_view = bess_controller.system.get_current_daily_view()
        logger.debug(f"Daily view retrieved successfully with {len(daily_view.hourly_data)} hours")
        
        # Get settings for additional calculations
        settings = bess_controller.system.get_settings()
        battery_capacity = settings["battery"].total_capacity
        logger.debug(f"Retrieved battery capacity: {battery_capacity}")
        
        # Process hourly data using values directly from the HourlyData objects
        api_hourly_data = []
        for i, hour_data in enumerate(daily_view.hourly_data):
            # Get the flattened data with all fields directly from the model
            flattened = flatten_hourly_data(hour_data, battery_capacity)
            
            # Only calculate UI-specific derived fields that aren't in the model
            home_consumption = flattened.get("homeConsumption", 0)
            solar_production = flattened.get("solarProduction", 0)
            
            # Calculate derived display fields that aren't part of the core model
            # These are purely for UI convenience
            direct_solar = min(solar_production, home_consumption)
            grid_import_needed = max(0, home_consumption - direct_solar)
            solar_excess = max(0, solar_production - home_consumption)
            
            # Update only UI-specific derived fields
            flattened.update({
                "directSolar": direct_solar,
                "gridImportNeeded": grid_import_needed,
                "solarExcess": solar_excess
            })
            
            api_hourly_data.append(flattened)
            if i == 0:  # Log first hour as sample
                logger.debug(f"Sample hour data: {flattened}")
                
        logger.debug(f"Processed {len(api_hourly_data)} hours of data")
        
        # Get battery information
        controller = bess_controller.system.controller
        battery_soc = controller.get_battery_soc()
        battery_soe = (battery_soc / 100.0) * battery_capacity
        logger.debug(f"Battery SOC: {battery_soc}%, SOE: {battery_soe} kWh")
        
        # Calculate totals from hourly data - using only canonical camelCase field names
        totals = {
            # Main energy sources and sinks
            "totalSolarProduction": sum(h.get("solarProduction", 0) for h in api_hourly_data),
            "totalHomeConsumption": sum(h.get("homeConsumption", 0) for h in api_hourly_data),
            "totalGridImport": sum(h.get("gridImported", 0) for h in api_hourly_data),
            "totalGridExport": sum(h.get("gridExported", 0) for h in api_hourly_data),
            
            # Detailed energy flows - Solar origin
            "totalSolarToHome": sum(h.get("solarToHome", 0) for h in api_hourly_data),
            "totalSolarToBattery": sum(h.get("solarToBattery", 0) for h in api_hourly_data),
            "totalSolarToGrid": sum(h.get("solarToGrid", 0) for h in api_hourly_data),
            
            # Detailed energy flows - Grid origin
            "totalGridToHome": sum(h.get("gridToHome", 0) for h in api_hourly_data),
            "totalGridToBattery": sum(h.get("gridToBattery", 0) for h in api_hourly_data),
            
            # Detailed energy flows - Battery origin
            "totalBatteryToHome": sum(h.get("batteryToHome", 0) for h in api_hourly_data),
            "totalBatteryToGrid": sum(h.get("batteryToGrid", 0) for h in api_hourly_data),
            
            # Economic data - Costs
            "totalGridOnlyCost": sum(h.get("gridOnlyCost", 0) for h in api_hourly_data),
            "totalSolarOnlyCost": sum(h.get("solarOnlyCost", 0) for h in api_hourly_data), 
            "totalOptimizedCost": sum(h.get("hourlyCost", 0) for h in api_hourly_data),
            
            # Economic data - Savings (calculate from hourly sums)
            "totalBatterySavings": sum(h.get("batterySavings", 0) for h in api_hourly_data),
        }
        
        # Calculate battery totals from flow components (more reliable than direct hourly sums)
        totals["totalBatteryCharged"] = totals["totalSolarToBattery"] + totals["totalGridToBattery"]
        totals["totalBatteryDischarged"] = totals["totalBatteryToHome"] + totals["totalBatteryToGrid"]
        
        # Calculate total savings correctly from cost differences
        totals["totalSolarSavings"] = totals["totalGridOnlyCost"] - totals["totalSolarOnlyCost"]
        totals["totalOptimizationSavings"] = totals["totalGridOnlyCost"] - totals["totalOptimizedCost"]
        logger.debug("Calculated totals successfully")
        
        # Use values from totals where available - BUT calculate savings directly from hourly data  
        total_grid_only_cost = totals["totalGridOnlyCost"]
        total_solar_only_cost = totals["totalSolarOnlyCost"]
        total_optimized_cost = totals["totalOptimizedCost"]
        
        # Get battery costs directly from hourly data
        total_battery_costs = sum(h.get("batteryCycleCost", 0) for h in api_hourly_data)
        
        # Calculate grid costs (net cost of grid interactions)
        total_grid_costs = sum(h.get("gridCost", 0) for h in api_hourly_data)
        
        # Calculate savings directly from cost totals (ignore pre-calculated fields)
        solar_savings_calculated = total_grid_only_cost - total_solar_only_cost     # Grid-Only → Solar-Only
        battery_savings_calculated = total_solar_only_cost - total_optimized_cost  # Solar-Only → Solar+Battery  
        total_savings_calculated = total_grid_only_cost - total_optimized_cost     # Grid-Only → Solar+Battery
        
        logger.debug("Calculated costs and savings")
        
        # Build canonical summary with consistent field names
        summary = {
            # Baseline costs (what scenarios would cost) - CANONICAL
            "gridOnlyCost": total_grid_only_cost,
            "solarOnlyCost": total_solar_only_cost, 
            "optimizedCost": total_optimized_cost,
            
            # Component costs (breakdown) - CANONICAL
            "totalGridCost": total_grid_costs,
            "totalBatteryCycleCost": total_battery_costs,
            
            # Savings calculations - CANONICAL (use correct calculations)
            "totalSavings": total_savings_calculated,        # Grid-Only → Solar+Battery total savings
            "solarSavings": solar_savings_calculated,        # Grid-Only → Solar-Only savings  
            "batterySavings": battery_savings_calculated,    # Solar-Only → Solar+Battery additional savings
            
            # Energy totals - CANONICAL
            "totalSolarProduction": totals["totalSolarProduction"],
            "totalHomeConsumption": totals["totalHomeConsumption"], 
            "totalBatteryCharged": totals["totalBatteryCharged"],
            "totalBatteryDischarged": totals["totalBatteryDischarged"],
            "totalGridImported": totals["totalGridImport"],
            "totalGridExported": totals["totalGridExport"],
            
            # Efficiency metrics - CANONICAL
            "cycleCount": totals["totalBatteryCharged"] / battery_capacity if battery_capacity > 0 else 0.0,
        }
        
        result = {
            "date": daily_view.date.isoformat(),
            "currentHour": daily_view.current_hour,
            "totalDailySavings": daily_view.total_daily_savings,
            "actualSavingsSoFar": daily_view.actual_savings_so_far,
            "predictedRemainingSavings": daily_view.predicted_remaining_savings,
            "actualHoursCount": daily_view.actual_hours_count,
            "predictedHoursCount": daily_view.predicted_hours_count,
            "dataSources": daily_view.data_sources,
            "hourlyData": api_hourly_data,
            "summary": summary,
            "totals": totals,
            "batteryCapacity": battery_capacity,
            "batterySoc": battery_soc,
            "batterySoe": battery_soe,
        }
        
        logger.debug("Dashboard data prepared successfully")
        return result
        
    except Exception as e:
        logger.error(f"Error generating dashboard data: {e}")
        logger.exception("Full dashboard error traceback:")
        raise HTTPException(status_code=500, detail=str(e)) from e
############################################################################################
# API Endpoints for Decision Insights
############################################################################################

def convert_real_data_to_mock_format(hourly_data_list: list, current_hour: int) -> dict:
    """
    Convert real HourlyData with enhanced DecisionData to exact mock format.
    
    Enhanced with comprehensive decision intelligence analysis including:
    - Real DP alternatives with confidence scores
    - Detailed economic breakdown
    - Future value timeline
    - Decision confidence and opportunity cost
    """
    patterns = []
    
    for hour_data in hourly_data_list:
        is_current = hour_data.hour == current_hour
        is_actual = hour_data.data_source == "actual"
        
        # Base pattern with existing fields
        pattern = {
            "hour": hour_data.hour,
            "battery_action": hour_data.decision.battery_action,
            "strategic_intent": hour_data.decision.strategic_intent,
            "pattern_name": hour_data.decision.pattern_name,
            "description": hour_data.decision.description,
            "economic_chain": hour_data.decision.economic_chain,
            "immediate_value": hour_data.decision.immediate_value,
            "future_value": hour_data.decision.future_value,
            "net_strategy_value": hour_data.decision.net_strategy_value,
            "cost_basis": hour_data.decision.cost_basis,
            "is_current_hour": is_current,
            "is_actual": is_actual
        }
        
        # NEW: Decision Landscape (alternatives evaluated by DP algorithm)
        pattern["decision_landscape"] = [
            {
                "battery_action": alt.battery_action,
                "immediate_reward": alt.immediate_reward,
                "future_value": alt.future_value,
                "total_reward": alt.total_reward,
                "confidence_score": alt.confidence_score,
            }
            for alt in hour_data.decision.alternatives_evaluated
        ] if hour_data.decision.alternatives_evaluated else []
        
        # NEW: Economic Breakdown (detailed cost/benefit analysis)
        if hour_data.decision.economic_breakdown:
            pattern["economic_breakdown"] = {
                "grid_purchase_cost": hour_data.decision.economic_breakdown.grid_purchase_cost,
                "grid_avoidance_benefit": hour_data.decision.economic_breakdown.grid_avoidance_benefit,
                "battery_cost_basis": hour_data.decision.economic_breakdown.battery_cost_basis,
                "battery_wear_cost": hour_data.decision.economic_breakdown.battery_wear_cost,
                "export_revenue": hour_data.decision.economic_breakdown.export_revenue,
                "net_immediate_value": hour_data.decision.economic_breakdown.net_immediate_value,
            }
        else:
            pattern["economic_breakdown"] = {}
        
        # NEW: Future Timeline (when future value is realized)
        pattern["future_timeline"] = [
            {
                "hour": contrib.hour,
                "contribution": contrib.contribution,
                "action": contrib.action,
                "action_type": contrib.action_type,
            }
            for contrib in hour_data.decision.future_value_timeline
        ] if hour_data.decision.future_value_timeline else []
        
        # NEW: Decision Confidence and Opportunity Cost
        pattern["decision_confidence"] = hour_data.decision.decision_confidence
        pattern["opportunity_cost"] = hour_data.decision.opportunity_cost
        
        # NEW: Context Data (for analysis)
        pattern["context"] = {
            "grid_price": hour_data.economic.buy_price if hour_data.economic.buy_price > 0 else 1.0,
            "consumption": hour_data.energy.home_consumption,
            "solar_production": hour_data.energy.solar_production,
            "battery_soe": hour_data.energy.battery_soe_start,
        }
        
        patterns.append(pattern)
    
    # Calculate summary statistics with enhanced decision intelligence metrics
    if patterns:
        total_net_value = sum(p["net_strategy_value"] for p in patterns)
        actual_patterns = [p for p in patterns if p["is_actual"]]
        predicted_patterns = [p for p in patterns if not p["is_actual"]]
        best_decision = max(patterns, key=lambda p: p["net_strategy_value"])
        
        # NEW: Decision intelligence summary metrics
        average_confidence = sum(p["decision_confidence"] for p in patterns) / len(patterns)
        total_opportunity_cost = sum(p["opportunity_cost"] for p in patterns)
        hours_with_alternatives = len([p for p in patterns if p["decision_landscape"]])
        
        summary = {
            "total_net_value": total_net_value,
            "best_decision_hour": best_decision["hour"],
            "best_decision_value": best_decision["net_strategy_value"],
            "actual_hours_count": len(actual_patterns),
            "predicted_hours_count": len(predicted_patterns),
            # NEW: Enhanced summary metrics
            "average_confidence": average_confidence,
            "total_opportunity_cost": total_opportunity_cost,
            "hours_with_alternatives": hours_with_alternatives,
            "analysis_version": "enhanced_v1",
        }
    else:
        summary = {
            "total_net_value": 0.0,
            "best_decision_hour": 0,
            "best_decision_value": 0.0,
            "actual_hours_count": 0,
            "predicted_hours_count": 0,
            # NEW: Enhanced summary defaults
            "average_confidence": 1.0,
            "total_opportunity_cost": 0.0,
            "hours_with_alternatives": 0,
            "analysis_version": "enhanced_v1",
        }
    
    # Create response matching exact mock format
    response = {
        "patterns": patterns,
        "summary": summary
    }
    
    # Process future_opportunity objects for camelCase conversion (existing logic)
    for pattern in patterns:
        opportunity = pattern.get("future_opportunity")
        if opportunity:
            pattern["future_opportunity"] = {
                "description": opportunity["description"],
                "targetHours": opportunity["target_hours"],
                "expectedValue": opportunity["expected_value"],
                "dependencies": opportunity["dependencies"]
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
        
        # Convert real HourlyData to mock format
        response = convert_real_data_to_mock_format(
            daily_view.hourly_data, 
            daily_view.current_hour
        )
        
        # Convert snake_case to camelCase for frontend (matching mock behavior)
        return convert_keys_to_camel_case(response)
        
    except Exception as e:
        logger.error(f"Error generating decision intelligence from real data: {e}")
        # Fallback to empty response on error
        empty_response = {
            "patterns": [],
            "summary": {
                "total_net_value": 0.0,
                "best_decision_hour": 0,
                "best_decision_value": 0.0,
                "actual_hours_count": 0,
                "predicted_hours_count": 0
            }
        }
        return convert_keys_to_camel_case(empty_response)


# Add growatt endpoints for inverter status and detailed schedule
@router.get("/api/growatt/inverter_status")
async def get_inverter_status():
    """Get comprehensive real-time inverter status data."""
    from app import bess_controller

    try:
        # Safety checks to avoid None references
        if not hasattr(bess_controller, "system") or bess_controller.system is None:
            logger.error("Battery system not initialized")
            raise HTTPException(status_code=503, detail="Battery system not initialized")
            
        controller = bess_controller.system._controller
        if controller is None:
            logger.error("Battery controller not initialized")
            raise HTTPException(status_code=503, detail="Battery controller not initialized")
            
        battery_settings = bess_controller.system.battery_settings
        
        # Default values in case of errors
        battery_soc = 50.0
        battery_soe = 0.0
        grid_charge_enabled = False
        discharge_power_rate = 100.0
        battery_charge_power = 0.0
        battery_discharge_power = 0.0
        
        # Get battery data with error handling
        try:
            battery_soc = controller.get_battery_soc()
            battery_soe = (battery_soc / 100.0) * battery_settings.total_capacity
            grid_charge_enabled = controller.grid_charge_enabled()
            discharge_power_rate = controller.get_discharging_power_rate()
            battery_charge_power = controller.get_battery_charge_power()
            battery_discharge_power = controller.get_battery_discharge_power()
        except Exception as e:
            logger.error(f"Error getting battery status: {e}")

        response = {
            "battery_soc": battery_soc,
            "battery_soe": battery_soe,
            "battery_charge_power": battery_charge_power,
            "battery_discharge_power": battery_discharge_power,
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
        current_hour = datetime.now().hour

        # Get TOU intervals directly from schedule manager
        try:
            tou_intervals = schedule_manager.get_daily_TOU_settings()
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
                battery_mode = hourly_settings.get("batt_mode", "load-first")
                mode_distribution[battery_mode] = mode_distribution.get(battery_mode, 0) + 1
                
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
                    if hasattr(bess_controller.system, "price_manager"):
                        price_entries = bess_controller.system.price_manager.get_today_prices()
                        if hour < len(price_entries):
                            price = price_entries[hour]
                except Exception as e:
                    logger.warning(f"Failed to get price for hour {hour}: {e}")

                # Calculate or default battery-related values
                battery_action = hourly_settings.get("battery_action", 0.0)
                battery_charged = max(0, battery_action) if battery_action > 0 else 0
                battery_discharged = abs(min(0, battery_action)) if battery_action < 0 else 0
                battery_soe_kwh = 25.0  # Default SOE value in kWh
                battery_capacity = 50.0  # Default capacity in kWh
                
                # Try to get actual SOE values from controller if possible
                try:
                    if hour == current_hour and hasattr(bess_controller.system, "controller"):
                        battery_soc_percent = bess_controller.system.controller.get_battery_soc()
                        # Convert SOC percent to SOE kWh
                        if hasattr(bess_controller.system, "battery_settings"):
                            battery_capacity = bess_controller.system.battery_settings.total_capacity
                            battery_soe_kwh = (battery_soc_percent / 100.0) * battery_capacity
                        else:
                            battery_soe_kwh = (battery_soc_percent / 100.0) * battery_capacity
                except Exception:
                    pass  # Silently continue with default
                
                # Calculate SOC for display
                battery_soc_end = (battery_soe_kwh / battery_capacity) * 100.0
                
                schedule_data.append({
                    "hour": hour,
                    "mode": hourly_settings.get("state", "idle"),
                    "batt_mode": battery_mode,
                    "batteryMode": battery_mode,  # Add alias for frontend compatibility
                    "grid_charge": hourly_settings.get("grid_charge", False),
                    "discharge_rate": hourly_settings.get("discharge_rate", 100),
                    "dischargePowerRate": hourly_settings.get("discharge_rate", 100),  # Add alias
                    "chargePowerRate": 100,  # Default charge power rate
                    "strategic_intent": strategic_intent,
                    "intent_description": schedule_manager._get_intent_description(strategic_intent)
                    if hasattr(schedule_manager, "_get_intent_description") else "",
                    "action": action,
                    "action_color": action_color,
                    "battery_action": battery_action,
                    "battery_action_kw": hourly_settings.get("battery_action_kw", 0.0),
                    "batteryCharged": battery_charged,  # Add for frontend compatibility
                    "batteryDischarged": battery_discharged,  # Add for frontend compatibility
                    "soc": 50.0,
                    "batterySocEnd": battery_soc_end,  # Add for frontend compatibility
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
                    "batt_mode": "load-first",
                    "batteryMode": "load-first",  # Add alias for frontend compatibility
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
                    "is_current": hour == current_hour
                })
                idle_hours += 1

        response = {
            "current_hour": current_hour,
            "tou_intervals": tou_intervals,
            "schedule_data": schedule_data,
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
        if not hasattr(bess_controller, "system") or bess_controller.system is None:
            logger.error("Battery system not initialized")
            raise HTTPException(status_code=503, detail="Battery system not initialized")
            
        if not hasattr(bess_controller.system, "_schedule_manager"):
            logger.error("Schedule manager not initialized")
            raise HTTPException(status_code=503, detail="Schedule manager not initialized")
            
        schedule_manager = bess_controller.system._schedule_manager
        tou_intervals = schedule_manager.get_daily_TOU_settings()
        current_hour = datetime.now().hour

        # Enhanced TOU intervals with hourly settings and strategic intents
        enhanced_tou_intervals = []
        for interval in tou_intervals:
            enhanced_interval = interval.copy()
            start_hour = int(interval["start_time"].split(":")[0])
            try:
                settings = schedule_manager.get_hourly_settings(start_hour)
                enhanced_interval["grid_charge"] = settings.get("grid_charge", False)
                enhanced_interval["discharge_rate"] = settings.get("discharge_rate", 100)
                enhanced_interval["strategic_intent"] = settings.get(
                    "strategic_intent", "IDLE"
                )
            except Exception as e:
                logger.error(f"Error getting hourly settings for hour {start_hour}: {e}")
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
        if not hasattr(bess_controller, "system") or bess_controller.system is None:
            logger.error("Battery system not initialized")
            raise HTTPException(status_code=503, detail="Battery system not initialized")
            
        if not hasattr(bess_controller.system, "_schedule_manager"):
            logger.error("Schedule manager not initialized")
            raise HTTPException(status_code=503, detail="Schedule manager not initialized")
            
        schedule_manager = bess_controller.system._schedule_manager

        # Get strategic intent summary
        strategic_summary = {}
        if hasattr(schedule_manager, "get_strategic_intent_summary"):
            strategic_summary = schedule_manager.get_strategic_intent_summary()

        # Get hourly strategic intents
        hourly_intents = []
        for hour in range(24):
            try:
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
                        "grid_charge": settings.get("grid_charge", False),
                        "discharge_rate": settings.get("discharge_rate", 100),
                        "is_current": hour == datetime.now().hour,
                    }
                )
            except Exception as e:
                logger.warning(f"Error getting hourly settings for hour {hour}: {e}")
                # Add fallback data
                hourly_intents.append(
                    {
                        "hour": hour,
                        "intent": "UNKNOWN",
                        "description": "Data unavailable",
                        "battery_action": 0.0,
                        "grid_charge": False,
                        "discharge_rate": 100,
                        "is_current": hour == datetime.now().hour,
                    }
                )

        response = {
            "summary": strategic_summary,
            "hourly_intents": hourly_intents,
        }

        return convert_keys_to_camel_case(response)

    except Exception as e:
        logger.error(f"Error getting strategic intents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e