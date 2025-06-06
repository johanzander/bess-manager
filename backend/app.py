import json
import os
from datetime import datetime

import log_config  # noqa: F401
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

# Import BESS system modules
from core.bess.battery_controller_v2 import BatterySystemManager
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.health_check import run_system_health_checks
from core.bess.price_manager import HomeAssistantSource

# Get ingress prefix from environment variable
INGRESS_PREFIX = os.environ.get("INGRESS_PREFIX", "")


def add_camel_case_keys(data):
    """Add camelCase versions of snake_case keys for frontend compatibility."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            result[key] = add_camel_case_keys(value)
            # Convert snake_case to camelCase
            if "_" in key:
                camel_key = "".join(
                    word.capitalize() if i > 0 else word
                    for i, word in enumerate(key.split("_"))
                )
                result[camel_key] = add_camel_case_keys(value)
        return result
    elif isinstance(data, list):
        return [add_camel_case_keys(item) for item in data]
    else:
        return data


# Create FastAPI app with correct root_path
app = FastAPI(root_path=INGRESS_PREFIX)

# Now that logger patching is complete, log the ingress prefix
logger.info(f"Ingress prefix: {INGRESS_PREFIX}")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for the various paths
static_directory = "/app/frontend"
if os.path.exists(static_directory):
    # Root path assets
    app.mount(
        "/assets", StaticFiles(directory=f"{static_directory}/assets"), name="assets"
    )


@app.get("/status")
def get_status():
    return {"status": "ok", "ingress_prefix": INGRESS_PREFIX}


class BESSController:
    def __init__(self):
        """Initialize the BESS Controller."""
        # Load environment variables
        load_dotenv("/data/options.env")

        # Initialize Home Assistant API Controller
        self.ha_controller = self._init_ha_controller()
        self.ha_controller.set_test_mode(False)

        # Create Battery System Manager
        price_source = HomeAssistantSource(self.ha_controller)
        self.system = BatterySystemManager(self.ha_controller, price_source)

        # Create scheduler with increased misfire grace time to avoid unnecessary warnings
        self.scheduler = BackgroundScheduler(
            {
                "apscheduler.executors.default": {
                    "class": "apscheduler.executors.pool:ThreadPoolExecutor",
                    "max_workers": "20",
                },
                "apscheduler.job_defaults": {
                    "misfire_grace_time": 30  # Allow 30 seconds of misfire before warning
                },
            }
        )

        # Load and apply settings
        self._load_and_apply_settings()

        logger.info("BESS Controller initialized")

    def _init_ha_controller(self):
        """Initialize Home Assistant API controller based on environment."""
        ha_token = os.getenv("HASSIO_TOKEN")
        if ha_token:
            ha_url = "http://supervisor/core"
        else:
            ha_token = os.environ.get("HA_TOKEN", "")
            ha_url = os.environ.get("HA_URL", "http://supervisor/core")

        # Get sensor configuration from options
        options = self._load_options()
        sensor_config = options.get("sensors", {}) if options else {}

        logger.info(
            f"Initializing HA controller with {len(sensor_config)} sensor configurations"
        )

        return HomeAssistantAPIController(
            base_url=ha_url, token=ha_token, sensor_config=sensor_config
        )

    def _load_and_apply_settings(self):
        """Load options and apply settings."""
        try:
            options = self._load_options()
            logger.debug(
                f"Options loaded for settings: {json.dumps(options, indent=2)}"
            )
            if options:
                settings = {
                    "battery": {
                        "totalCapacity": options["battery"]["total_capacity"],
                        "chargeCycleCost": options["battery"]["cycle_cost"],
                        "maxChargeDischargePower": options["battery"][
                            "max_charge_discharge_power"
                        ],
                        "estimatedConsumption": options["home"]["consumption"],
                    },
                    "consumption": {"defaultHourly": options["home"]["consumption"]},
                    "price": {
                        "area": options["electricity_price"]["area"],
                        "markupRate": options["electricity_price"]["markup_rate"],
                        "vatMultiplier": options["electricity_price"]["vat_multiplier"],
                        "additionalCosts": options["electricity_price"][
                            "additional_costs"
                        ],
                        "taxReduction": options["electricity_price"]["tax_reduction"],
                        "minProfit": options["electricity_price"].get(
                            "min_profit", 0.05
                        ),
                    },
                }
                logger.debug(f"Loaded settings: {json.dumps(settings, indent=2)}")
                self.system.update_settings(settings)
        except Exception as e:
            logger.error(f"Error loading settings: {e}", exc_info=True)
            logger.error(
                f"Options dict at failure: {json.dumps(options, indent=2) if 'options' in locals() else 'N/A'}"
            )

    def _load_options(self):
        """Load options from Home Assistant add-on config or environment vars."""
        import yaml

        options_json = "/data/options.json"
        config_yaml = "/app/config.yaml"

        # First try the standard options.json (production)
        if os.path.exists(options_json):
            try:
                with open(options_json) as f:
                    options = json.load(f)
                    logger.info(f"Loaded options from {options_json}")
                    return options
            except Exception as e:
                logger.error(f"Error loading options from {options_json}: {e!s}")

        # If not available, try to load from config.yaml directly (development)
        if os.path.exists(config_yaml):
            try:
                with open(config_yaml) as f:
                    config = yaml.safe_load(f)

                # Extract options section if it exists
                if "options" in config:
                    options = config["options"]
                    logger.info(f"Loaded options from {config_yaml} (options section)")
                    return options

                logger.warning(
                    f"No 'options' section found in {config_yaml}, using entire file"
                )
                return config
            except Exception as e:
                logger.error(f"Error loading from {config_yaml}: {e!s}")

    def _init_scheduler(self):
        """Configure scheduler jobs."""

        # Hourly schedule update (every hour at xx:00)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(hour=datetime.now().hour),
            CronTrigger(minute=0),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Next day preparation (daily at 23:55)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(
                hour=datetime.now().hour, prepare_next_day=True
            ),
            CronTrigger(hour=23, minute=55),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Charging power adjustment (every 5 minutes)
        self.scheduler.add_job(
            self.system.adjust_charging_power,
            CronTrigger(minute="*/5"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        self.scheduler.start()

    def start(self):
        """Start the scheduler."""
        #        try:
        self.system.start()
        self.system.update_battery_schedule(hour=datetime.now().hour),
        self._init_scheduler()
        logger.info("Scheduler started successfully")


#        except Exception as e:
#            logger.critical(f"Scheduler failed to start: {e}", exc_info=True)
#            raise


# Global BESS controller instance
bess_controller = BESSController()
bess_controller.start()

# Get ingress base path, important for Home Assistant ingress
ingress_base_path = os.environ.get("INGRESS_BASE_PATH", "/local_bess_manager/ingress")


@app.on_event("startup")
async def startup_debug():
    """Print all registered routes for debugging."""
    routes = []
    for route in app.routes:
        if hasattr(route, "methods"):
            routes.append(f"{route.path} - {route.methods}")
        else:
            routes.append(f"{route.path} - Mounted route or no methods")
    logger.info(f"Registered routes: {routes}")
    logger.info(f"Using ingress base path: {ingress_base_path}")


# Handle root and ingress paths
@app.get("/")
async def root_index():
    logger.info("Root path requested")
    return FileResponse("/app/frontend/index.html")


@app.get("/api/settings/battery")
async def get_battery_settings():
    """Get current battery settings."""
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


@app.post("/api/settings/battery")
async def update_battery_settings(settings: dict):
    """Update battery settings."""
    try:
        bess_controller.system.update_settings({"battery": settings})
        return {"message": "Battery settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/settings/electricity")
async def get_electricity_price_settings():
    """Get current electricity price settings."""
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


@app.post("/api/settings/electricity")
async def update_electricity_price_settings(settings: dict):
    """Update electricity price settings."""
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


@app.get("/api/schedule")
async def get_battery_schedule(
    date: str = Query(None, description="Date in YYYY-MM-DD format"),
):
    """Get battery schedule data for dashboard with enhanced reporting."""
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


@app.get("/api/schedule/detailed")
async def get_detailed_schedule():
    """Get detailed battery schedule data directly from the current schedule report."""
    try:
        from utils import add_camel_case_keys  # Import the utility function

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


@app.get("/api/schedule/current")
async def get_current_schedule():
    """Get the current active battery schedule."""
    try:
        from utils import add_camel_case_keys  # Import the utility function

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


@app.get("/api/predictions/consumption")
async def get_consumption_predictions():
    """Get hourly consumption predictions for the next 24 hours."""
    try:
        predictions = (
            bess_controller.system._energy_manager.get_consumption_predictions()
        )
        return {"data": [float(val) for val in predictions]}
    except Exception as e:
        logger.error(f"Error getting consumption predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/report/daily_savings")
async def get_daily_savings_report():
    """Get the daily savings report with detailed energy analysis."""
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


@app.get("/api/energy/balance")
async def get_energy_balance():
    """Get energy balance for the day."""
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


@app.get("/api/energy/profile")
async def get_energy_profile(
    current_hour: int = Query(None, description="Current hour (0-23)")
):
    """Get the full energy profile combining historical and predicted data."""
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


@app.get("/api/system/health")
async def get_system_health():
    """Get system health check results."""
    try:
        health_results = run_system_health_checks(bess_controller.system)
        return health_results
    except Exception as e:
        logger.error(f"Error running health checks: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/system/info")
async def get_system_info():
    """Get system information and version details."""
    try:
        # Basic system information that can be extended as needed
        return {
            "status": "ok",
            "version": "1.0.0",  # You may want to get this from a version file
            "uptime": bess_controller.system.get_uptime()
            if hasattr(bess_controller.system, "get_uptime")
            else None,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/v2/daily_view")
async def get_daily_view_v2():
    """FIXED: Ensure historical data is properly included."""
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
            f"Daily view API: returning {actual_count} actual + {predicted_count} predicted hours"
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
                    "electricity_price": h.electricity_price,
                    "price": h.electricity_price,
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


@app.get("/api/growatt/tou_settings")
async def get_tou_settings():
    """Get current TOU (Time of Use) settings with strategic intent information."""
    logger.info("=== FRONTEND API REQUEST: tou_settings ===")
    logger.info("Current hour: %02d:00", datetime.now().hour)

    try:
        schedule_manager = bess_controller.system._schedule_manager
        if not schedule_manager:
            logger.warning("No schedule manager found for TOU settings")
            return {"status": "unavailable", "message": "No schedule manager available"}

        # Get TOU intervals
        tou_intervals = schedule_manager.get_daily_TOU_settings()
        current_hour = datetime.now().hour

        logger.info("Retrieved %d TOU intervals", len(tou_intervals))

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
        strategic_summary = {}
        if hasattr(schedule_manager, "get_strategic_intent_summary"):
            try:
                strategic_summary = schedule_manager.get_strategic_intent_summary()
            except Exception as e:
                logger.warning("Failed to get strategic intent summary: %s", e)

        response = {
            "status": "ok",
            "tou_intervals": enhanced_tou_intervals,
            "hourly_settings": hourly_settings,
            "current_hour": current_hour,
            "strategic_summary": strategic_summary,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info("API response generated successfully")
        return response

    except Exception as e:
        logger.error("Error getting TOU settings: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/optimization/history")
async def get_optimization_history():
    """Get optimization decision history for insights."""
    try:
        history = bess_controller.system.get_optimization_history()
        return {"data": history}
    except Exception as e:
        logger.error(f"Error getting optimization history: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/energy/historical_events")
async def get_historical_events():
    """Get historical energy events for analytics."""
    try:
        events = bess_controller.system.get_historical_events()
        return {"data": events}
    except Exception as e:
        logger.error(f"Error getting historical events: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/growatt/inverter_status")
async def get_inverter_status():
    """Get comprehensive real-time inverter status data."""
    logger.info("=== FRONTEND API REQUEST: inverter_status ===")
    logger.info("Current hour: %02d:00", datetime.now().hour)

    try:
        logger.info("Fetching real-time inverter status")

        controller = bess_controller.system._controller
        battery_settings = bess_controller.system.battery_settings

        # Get core data
        battery_soc = controller.get_battery_soc()
        battery_soe = (battery_soc / 100.0) * battery_settings.total_capacity
        grid_charge_enabled = controller.grid_charge_enabled()
        discharge_power_rate = controller.get_discharging_power_rate()

        logger.info(
            "Current battery status: SOC=%.1f%%, SOE=%.1f kWh, GridCharge=%s, DischargeRate=%d%%",
            battery_soc,
            battery_soe,
            grid_charge_enabled,
            discharge_power_rate,
        )

        # Get power values with error handling
        try:
            battery_charge_power = controller.get_battery_charge_power()
        except (AttributeError, NotImplementedError):
            battery_charge_power = 0.0

        try:
            battery_discharge_power = controller.get_battery_discharge_power()
        except (AttributeError, NotImplementedError):
            battery_discharge_power = 0.0

        # Log current activity
        if battery_charge_power > 100:
            logger.info("BATTERY ACTIVITY: Charging at %.1f W", battery_charge_power)
        elif battery_discharge_power > 100:
            logger.info(
                "BATTERY ACTIVITY: Discharging at %.1f W", battery_discharge_power
            )
        else:
            logger.info("BATTERY ACTIVITY: Idle")

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

        logger.info("API response generated successfully")
        return response

    except Exception as e:
        logger.error("Error getting inverter status: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/growatt/detailed_schedule")
async def get_growatt_detailed_schedule():
    """Get detailed Growatt-specific schedule information with strategic intents."""
    logger.info("=== FRONTEND API REQUEST: detailed_schedule ===")
    logger.info("Current hour: %02d:00", datetime.now().hour)

    try:
        logger.info("Starting get_growatt_detailed_schedule")

        # Check if system exists
        if not hasattr(bess_controller, "system"):
            logger.error("BESS system not available")
            raise HTTPException(status_code=500, detail="BESS system not available")

        # Check if schedule manager exists
        if not hasattr(bess_controller.system, "_schedule_manager"):
            logger.error("Schedule manager not available")
            raise HTTPException(
                status_code=500, detail="Schedule manager not available"
            )

        schedule_manager = bess_controller.system._schedule_manager
        if schedule_manager is None:
            logger.error("Schedule manager is None")
            raise HTTPException(status_code=500, detail="Schedule manager is None")

        current_hour = datetime.now().hour
        logger.info("Current hour: %d", current_hour)

        # Get TOU intervals with error handling
        try:
            tou_intervals = schedule_manager.get_daily_TOU_settings()
            logger.info("Got %d TOU intervals", len(tou_intervals))
        except Exception as e:
            logger.error("Failed to get TOU intervals: %s", e)
            tou_intervals = []

        # Build hourly schedule data with strategic intents
        schedule_data = []
        charge_hours = 0
        discharge_hours = 0
        idle_hours = 0
        mode_distribution = {}
        intent_distribution = {}

        logger.info("Building hourly schedule data")

        for hour in range(24):
            try:
                # Get hourly settings with error handling
                try:
                    hourly_settings = schedule_manager.get_hourly_settings(hour)
                except Exception as e:
                    logger.warning(
                        "Failed to get hourly settings for hour %d: %s", hour, e
                    )
                    hourly_settings = {
                        "grid_charge": False,
                        "discharge_rate": 0,
                        "state": "idle",
                        "strategic_intent": "IDLE",
                        "battery_action": 0.0,
                    }

                # Find battery mode for this hour
                battery_mode = "load-first"
                for interval in tou_intervals:
                    try:
                        start_hour = int(interval["start_time"].split(":")[0])
                        end_hour = int(interval["end_time"].split(":")[0])
                        if start_hour <= hour <= end_hour and interval.get(
                            "enabled", False
                        ):
                            battery_mode = interval["batt_mode"]
                            break
                    except Exception as e:
                        logger.warning(
                            "Error processing TOU interval for hour %d: %s", hour, e
                        )
                        continue

                # Get strategic intent safely
                strategic_intent = hourly_settings.get("strategic_intent", "IDLE")
                intent_distribution[strategic_intent] = (
                    intent_distribution.get(strategic_intent, 0) + 1
                )

                # Determine action based on strategic intent
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

                mode_distribution[battery_mode] = (
                    mode_distribution.get(battery_mode, 0) + 1
                )

                # Get price with error handling
                price = 1.0  # Default fallback
                try:
                    if hasattr(bess_controller.system, "price_manager"):
                        price_entries = (
                            bess_controller.system.price_manager.get_today_prices()
                        )
                        if price_entries and hour < len(price_entries):
                            price = price_entries[hour].get("buyPrice", 1.0)
                except Exception as e:
                    logger.warning("Failed to get price for hour %d: %s", hour, e)

                # Get battery action safely
                battery_action = hourly_settings.get("battery_action", 0.0)

                schedule_data.append(
                    {
                        "hour": hour,
                        "mode": hourly_settings.get("state", "idle"),
                        "battery_mode": battery_mode,
                        "grid_charge": hourly_settings.get("grid_charge", False),
                        "discharge_rate": hourly_settings.get("discharge_rate", 0),
                        "state": hourly_settings.get("state", "idle"),
                        "strategic_intent": strategic_intent,
                        "action": action,
                        "action_color": action_color,
                        "battery_action": battery_action,
                        "soc": 50.0,  # Placeholder
                        "price": price,
                        "grid_power": 0,
                        "is_current": hour == current_hour,
                    }
                )

            except Exception as e:
                logger.error("Error processing hour %d: %s", hour, e)
                # Add minimal data for this hour to avoid breaking the frontend
                schedule_data.append(
                    {
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
                        "is_current": hour == current_hour,
                    }
                )
                idle_hours += 1

        logger.info("Building enhanced TOU intervals")

        # Enhanced TOU intervals with strategic intent information
        enhanced_tou_intervals = []
        for interval in tou_intervals:
            try:
                enhanced_interval = interval.copy()
                start_hour = int(interval["start_time"].split(":")[0])

                try:
                    settings = schedule_manager.get_hourly_settings(start_hour)
                    enhanced_interval["grid_charge"] = settings.get(
                        "grid_charge", False
                    )
                    enhanced_interval["discharge_rate"] = settings.get(
                        "discharge_rate", 0
                    )
                    enhanced_interval["strategic_intent"] = settings.get(
                        "strategic_intent", "IDLE"
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to get settings for TOU interval starting at hour %d: %s",
                        start_hour,
                        e,
                    )
                    enhanced_interval["grid_charge"] = False
                    enhanced_interval["discharge_rate"] = 0
                    enhanced_interval["strategic_intent"] = "IDLE"

                enhanced_tou_intervals.append(enhanced_interval)

            except Exception as e:
                logger.error("Error processing TOU interval: %s", e)
                continue

        logger.info("Completed get_growatt_detailed_schedule successfully")

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

        logger.info("API response generated successfully")
        return response

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(
            "Unexpected error in get_growatt_detailed_schedule: %s", e, exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {e!s}"
        ) from e


@app.get("/api/growatt/strategic_intents")
async def get_strategic_intents():
    """Get strategic intent information for the current schedule."""
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
