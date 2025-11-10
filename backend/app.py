import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

import log_config  # noqa: F401
import yaml

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

# from core.bess.health_check import run_system_health_checks # TODO ADD health check

# Get ingress prefix from environment variable
INGRESS_PREFIX = os.environ.get("INGRESS_PREFIX", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager for FastAPI app."""
    # Startup
    routes = []
    for route in app.routes:
        path = getattr(route, "path", getattr(route, "mount_path", "Unknown path"))
        methods = getattr(route, "methods", None)
        if methods is not None:
            routes.append(f"{path} - {methods}")
        else:
            routes.append(f"{path} - Mounted route or no methods")
    logger.info(f"Registered routes: {routes}")
    logger.info(
        f"Using ingress base path: {os.environ.get('INGRESS_BASE_PATH', '/local_bess_manager/ingress')}"
    )

    yield

    # Shutdown (if needed in the future)
    pass


# Create FastAPI app with correct root_path
app = FastAPI(root_path=INGRESS_PREFIX, lifespan=lifespan)


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
            "message": "The server encountered an internal error but is still running.",
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

        # Enable test mode based on environment variable (defaults to False for production)
        test_mode = os.environ.get("HA_TEST_MODE", "false").lower() in ("true", "1", "yes")
        if test_mode:
            logger.info("Enabling test mode - hardware writes will be simulated")
        self.ha_controller.set_test_mode(test_mode)

        # Extract nordpool configuration
        nordpool_config = options.get("nordpool", {})

        # Create Battery System Manager with nordpool configuration
        # Let the system manager choose the appropriate price source
        self.system = BatterySystemManager(
            self.ha_controller,
            price_source=None,  # Let system manager auto-select based on config
            nordpool_config=nordpool_config,
        )

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
            ha_url=ha_url, token=ha_token, sensor_config=sensor_config
        )

    def _load_and_apply_settings(self):
        """Load options and apply settings.

        This method is kept for backwards compatibility, but all settings should now be
        applied early during initialization using _apply_settings().
        """
        try:
            options = self._load_options()
            if options:
                logger.debug(
                    "Reapplying settings from _load_and_apply_settings (redundant)"
                )
                self._apply_settings(options)
            else:
                logger.warning("No options found when reapplying settings")
        except Exception as e:
            logger.error(f"Error reloading settings: {e}", exc_info=True)

    def _load_options(self):
        """Load options from Home Assistant add-on config or environment vars."""

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
            lambda: self.system.update_battery_schedule(
                current_hour=datetime.now().hour
            ),
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

        All user-facing settings must be explicitly configured in config.yaml.
        No fallback defaults are provided to ensure deterministic behavior.

        Args:
            options: Dictionary containing all configuration options
        """
        try:
            if not options:
                raise ValueError("Configuration options are required but not provided")

            logger.debug(f"Applying settings: {json.dumps(options, indent=2)}")

            # Validate required sections exist
            required_sections = ["battery", "electricity_price", "home"]
            for section in required_sections:
                if section not in options:
                    raise ValueError(
                        f"Required configuration section '{section}' is missing from config.yaml"
                    )

            # Validate required values without defaults
            battery_config = options["battery"]
            electricity_price_config = options["electricity_price"]
            home_config = options["home"]

            # Required battery settings
            required_battery_keys = [
                "total_capacity",
                "cycle_cost",
                "max_charge_discharge_power",
                "min_action_profit_threshold",
            ]
            for key in required_battery_keys:
                if key not in battery_config:
                    raise ValueError(
                        f"Required battery setting '{key}' is missing from config.yaml"
                    )

            # Required electricity price settings
            required_price_keys = [
                "area",
                "markup_rate",
                "vat_multiplier",
                "additional_costs",
                "tax_reduction",
            ]
            for key in required_price_keys:
                if key not in electricity_price_config:
                    raise ValueError(
                        f"Required electricity_price setting '{key}' is missing from config.yaml"
                    )

            # Required home settings
            required_home_keys = ["consumption", "currency"]
            for key in required_home_keys:
                if key not in home_config:
                    raise ValueError(
                        f"Required home setting '{key}' is missing from config.yaml"
                    )

            settings = {
                "battery": {
                    "totalCapacity": battery_config["total_capacity"],
                    "cycleCostPerKwh": battery_config["cycle_cost"],
                    "maxChargePowerKw": battery_config["max_charge_discharge_power"],
                    "maxDischargePowerKw": battery_config["max_charge_discharge_power"],
                    "minActionProfitThreshold": battery_config[
                        "min_action_profit_threshold"
                    ],
                },
                "home": {
                    "defaultHourly": home_config["consumption"],
                    "currency": home_config["currency"],
                },
                "price": {
                    "area": electricity_price_config["area"],
                    "markupRate": electricity_price_config["markup_rate"],
                    "vatMultiplier": electricity_price_config["vat_multiplier"],
                    "additionalCosts": electricity_price_config["additional_costs"],
                    "taxReduction": electricity_price_config["tax_reduction"],
                },
            }

            logger.debug(f"Formatted settings: {json.dumps(settings, indent=2)}")
            self.system.update_settings(settings)
            logger.info("All settings applied successfully")

        except Exception as e:
            logger.error(
                f"CRITICAL: Failed to apply settings from config.yaml: {e}",
                exc_info=True
            )
            raise RuntimeError(
                f"Settings application failed - system cannot start safely. "
                f"Check config.yaml for invalid or missing settings. Error: {e}"
            ) from e

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


# Handle root and ingress paths
@app.get("/")
async def root_index():
    logger.info("Root path requested")
    return FileResponse("/app/frontend/index.html")


# All API endpoints are found in api.py and are imported via the router
# The endpoints router is included in the app instance at the top of this file
