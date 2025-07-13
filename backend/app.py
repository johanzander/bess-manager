import json
import os
from datetime import datetime

import log_config  # noqa: F401

# Import endpoints router
from api import router as endpoints_router
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

# Import BESS system modules
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.ha_api_controller import HomeAssistantAPIController

#from core.bess.health_check import run_system_health_checks # TODO ADD health check
from core.bess.price_manager import HomeAssistantSource

# Get ingress prefix from environment variable
INGRESS_PREFIX = os.environ.get("INGRESS_PREFIX", "")

# Create FastAPI app with correct root_path
app = FastAPI(root_path=INGRESS_PREFIX)

# Add global exception handler to prevent server restarts
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback

    from fastapi.responses import JSONResponse
    
    # Get the full stack trace
    tb_str = traceback.format_exception(type(exc), exc, exc.__traceback__)
    error_msg = "".join(tb_str)
    
    # Log the full error details
    logger.error(f"Unhandled exception: {exc!s}")
    logger.error(f"Request path: {request.url.path}")
    logger.error(f"Stack trace:\n{error_msg}")
    
    # Return a 500 response but keep the server running
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": str(type(exc).__name__),
            "message": "The server encountered an internal error but is still running."
        },
    )

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

# Include the router from endpoints.py
app.include_router(endpoints_router)


class BESSController:
    def __init__(self):
        """Initialize the BESS Controller."""
        # Load environment variables
        load_dotenv("/data/options.env")

        # Load all settings as early as possible
        options = self._load_options()
        if not options:
            logger.warning("No configuration options found, using defaults")
            options = {}

        # Initialize Home Assistant API Controller with sensor config from options
        sensor_config = options.get("sensors", {})
        self.ha_controller = self._init_ha_controller(sensor_config)
        self.ha_controller.set_test_mode(True)

        # Extract settings for price manager
        price_settings = options.get("electricity_price", {})
        vat_multiplier = price_settings.get("vat_multiplier", 1.25)

        # Create Battery System Manager with configured VAT multiplier
        price_source = HomeAssistantSource(self.ha_controller, vat_multiplier=vat_multiplier)
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

        # Apply all settings to the system immediately
        self._apply_settings(options)

        logger.info("BESS Controller initialized with early settings loading")

    def _init_ha_controller(self, sensor_config):
        """Initialize Home Assistant API controller based on environment.
        
        Args:
            sensor_config: Sensor configuration dictionary to use for the controller.
        """
        ha_token = os.getenv("HASSIO_TOKEN")
        if ha_token:
            ha_url = "http://supervisor/core"
        else:
            ha_token = os.environ.get("HA_TOKEN", "")
            ha_url = os.environ.get("HA_URL", "http://supervisor/core")

        logger.info(
            f"Initializing HA controller with {len(sensor_config)} sensor configurations"
        )

        return HomeAssistantAPIController(
            base_url=ha_url, token=ha_token, sensor_config=sensor_config
        )

    def _load_and_apply_settings(self):
        """Load options and apply settings.
        
        This method is kept for backwards compatibility, but all settings should now be
        applied early during initialization using _apply_settings().
        """
        try:
            options = self._load_options()
            if options:
                logger.debug("Reapplying settings from _load_and_apply_settings (redundant)")
                self._apply_settings(options)
            else:
                logger.warning("No options found when reapplying settings")
        except Exception as e:
            logger.error(f"Error reloading settings: {e}", exc_info=True)

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

    def _init_scheduler_jobs(self):
        """Configure scheduler jobs."""

        # Hourly schedule update (every hour at xx:00)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(current_hour=datetime.now().hour),
            CronTrigger(minute=0),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Next day preparation (daily at 23:55)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(
                current_hour=datetime.now().hour, prepare_next_day=True
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

    def _apply_settings(self, options):
        """Apply all settings from the provided options dictionary.
        
        This consolidates settings application in one place, ensuring settings
        are applied as early as possible in the initialization process.
        
        Args:
            options: Dictionary containing all configuration options
        """
        try:
            if not options:
                logger.warning("No options provided for settings application")
                return
                
            logger.debug(f"Applying settings: {json.dumps(options, indent=2)}")
            
            settings = {
                "battery": {
                    "totalCapacity": options.get("battery", {}).get("total_capacity", 30.0),
                    "cycleCostPerKwh": options.get("battery", {}).get("cycle_cost", 0.50),  
                    "maxChargePowerKw": options.get("battery", {}).get("max_charge_discharge_power", 15.0),    
                    "maxDischargePowerKw": options.get("battery", {}).get("max_charge_discharge_power", 15.0),  
                    "estimatedConsumption": options.get("home", {}).get("consumption", 3.5),
                },
                "consumption": {
                    "defaultHourly": options.get("home", {}).get("consumption", 3.5)
                },
                "price": {
                    "area": options.get("electricity_price", {}).get("area", "SE4"),
                    "markupRate": options.get("electricity_price", {}).get("markup_rate", 0.08),
                    "vatMultiplier": options.get("electricity_price", {}).get("vat_multiplier", 1.25),
                    "additionalCosts": options.get("electricity_price", {}).get("additional_costs", 1.03),
                    "taxReduction": options.get("electricity_price", {}).get("tax_reduction", 0.6518),
                    "minProfit": options.get("electricity_price", {}).get("min_profit", 0.05),
                },
            }
            
            logger.debug(f"Formatted settings: {json.dumps(settings, indent=2)}")
            self.system.update_settings(settings)
            logger.info("All settings applied successfully")
            
        except Exception as e:
            logger.error(f"Error applying settings: {e}", exc_info=True)

    def start(self):
        """Start the scheduler."""
        self.system.start()
        self.system.update_battery_schedule(current_hour=datetime.now().hour)
        self._init_scheduler_jobs()
        logger.info("Scheduler started successfully")


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
        path = getattr(route, "path", getattr(route, "mount_path", "Unknown path"))
        methods = getattr(route, "methods", None)
        if methods is not None:
            routes.append(f"{path} - {methods}")
        else:
            routes.append(f"{path} - Mounted route or no methods")
    logger.info(f"Registered routes: {routes}")
    logger.info(f"Using ingress base path: {ingress_base_path}")


# Handle root and ingress paths
@app.get("/")
async def root_index():
    logger.info("Root path requested")
    return FileResponse("/app/frontend/index.html")

# All API endpoints are found in api.py and are imported via the router
# The endpoints router is included in the app instance at the top of this file


