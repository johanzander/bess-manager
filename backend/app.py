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

# Import endpoints router
from api import router as endpoints_router

# Get ingress prefix from environment variable
INGRESS_PREFIX = os.environ.get("INGRESS_PREFIX", "")

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

# Include the router from endpoints.py
app.include_router(endpoints_router)


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

# All API endpoints are found in api.py and are imported via the router
# The endpoints router is included in the app instance at the top of this file


