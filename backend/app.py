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
from core.bess import BatterySystemManager
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.price_manager import HANordpoolSource

# Get ingress prefix from environment variable
INGRESS_PREFIX = os.environ.get("INGRESS_PREFIX", "")
logger.info(f"Ingress prefix: {INGRESS_PREFIX}")

# Create FastAPI app with correct root_path
app = FastAPI(root_path=INGRESS_PREFIX)

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

        # Initialize price source
        self.price_source = HANordpoolSource(self.ha_controller)

        # Create Battery System Manager
        self.system = BatterySystemManager(
            controller=self.ha_controller, price_source=self.price_source
        )

        # Create scheduler
        self.scheduler = BackgroundScheduler()

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
        except Exception:
            logger.error("Error loading settings", exc_info=True)

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
        )

        # Next day preparation (daily at 23:55)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(
                hour=datetime.now().hour, prepare_next_day=True
            ),
            CronTrigger(hour=23, minute=55),
        )

        # Inverter settings verification (every 15 minutes)
        #        self.scheduler.add_job(
        #            lambda: self.system.verify_inverter_settings(hour=datetime.now().hour),
        #            CronTrigger(minute='*/15')
        #        )

        # Charging power adjustment (every 5 minutes)
        self.scheduler.add_job(
            self.system.adjust_charging_power, CronTrigger(minute="*/5")
        )

        self.scheduler.start()

    def start(self):
        """Start the scheduler."""
        try:
            self.system.start()
            self.system.update_battery_schedule(hour=datetime.now().hour),
            self._init_scheduler()
            logger.info("Scheduler started successfully")
        except Exception as e:
            logger.critical(f"Scheduler failed to start: {e}", exc_info=True)
            raise


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
    """Get battery schedule data for dashboard with enhanced reporting.

    This endpoint returns the schedule data with three calculation scenarios:
    1. Grid-Only: Base case with all consumption from grid
    2. Solar-Only: Impact of solar without battery optimization
    3. Solar+Battery: Full optimization with both technologies

    Args:
        date: Date to get schedule for in YYYY-MM-DD format (defaults to today)

    Returns:
        Complete schedule data with hourly breakdown and summary statistics
    """
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
        logger.info(f"Schedule data generated successfully for {target_date}")

        return schedule_data
    except Exception as e:
        logger.error(f"Error getting battery schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/schedule/detailed")
async def get_detailed_schedule():
    """Get detailed battery schedule data directly from the current schedule report."""
    try:
        # Get the current schedule
        current_schedule = bess_controller.system._current_schedule

        if not current_schedule:
            raise HTTPException(
                status_code=404,
                detail="No current schedule found. Please generate a schedule first.",
            )

        # Get the schedule data - this contains the hourly data and summary directly from the report
        schedule_data = current_schedule.get_schedule_data()

        # Return the data exactly as generated by the report
        return schedule_data
    except Exception as e:
        logger.error(f"Error getting detailed schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/schedule/current")
async def get_current_schedule():
    """Get the current active battery schedule."""
    try:
        if bess_controller.system._current_schedule is not None:
            current_hour = datetime.now().hour
            return {
                "current_hour": current_hour,
                "schedule": bess_controller.system._current_schedule.get_schedule_data(),
                "tou_intervals": bess_controller.system._schedule_manager.get_daily_TOU_settings(),
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
        return bess_controller.system.get_daily_savings_report()
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
    """Get the current energy balance report."""
    try:
        (
            hourly_data,
            totals,
        ) = bess_controller.system._energy_manager.log_energy_balance()

        # Convert to serializable format (converting numpy arrays if present)
        hourly_data_serializable = []
        for data in hourly_data:
            serializable_item = {}
            for k, v in data.items():
                serializable_item[k] = float(v) if isinstance(v, float | int) else v
            hourly_data_serializable.append(serializable_item)

        totals_serializable = {}
        for k, v in totals.items():
            totals_serializable[k] = float(v) if isinstance(v, float | int) else v

        return {"hourlyData": hourly_data_serializable, "totals": totals_serializable}
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

        profile = bess_controller.system._energy_manager.get_full_day_energy_profile(
            current_hour
        )

        # Convert numpy arrays to Python lists if needed
        for key in profile:
            if hasattr(profile[key], "tolist"):
                profile[key] = profile[key].tolist()

        return profile
    except Exception as e:
        logger.error(f"Error getting energy profile: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
