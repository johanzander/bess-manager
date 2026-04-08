"""
Main application entry point for the BESS management system.
"""

import json
import os
import tempfile
from contextlib import asynccontextmanager

import log_config  # noqa: F401

# Import endpoints router
from api import router as endpoints_router
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

# Import BESS system modules
from core.bess import time_utils
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
        # Environment variables are injected by HA Supervisor (production)
        # or docker-compose (development).

        # Load all settings as early as possible
        options = self._load_options()
        if not options:
            logger.warning("No configuration options found, using defaults")
            options = {}

        # Initialize Home Assistant API Controller with sensor config from options
        sensor_config = options.get("sensors", {})
        growatt_config = options.get("growatt", {})
        growatt_device_id = growatt_config.get("device_id")
        self.ha_controller = self._init_ha_controller(sensor_config, growatt_device_id)

        # Set timezone from HA config before any BESS modules use it
        try:
            ha_config = self.ha_controller.get_ha_config()
            ha_timezone = ha_config["time_zone"]
            from core.bess.time_utils import set_timezone

            set_timezone(ha_timezone)
            logger.info(f"Timezone set from HA: {ha_timezone}")
        except Exception as e:
            logger.warning(f"Could not read timezone from HA, using default: {e}")

        # Enable test mode based on environment variable (defaults to False for production)
        test_mode = os.environ.get("HA_TEST_MODE", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        if test_mode:
            logger.info("Enabling test mode - hardware writes will be simulated")
        self.ha_controller.set_test_mode(test_mode)

        # Extract energy provider configuration
        energy_provider_config = options.get("energy_provider", {})

        # Create Battery System Manager with price provider configuration
        # Let the system manager choose the appropriate price source
        self.system = BatterySystemManager(
            self.ha_controller,
            price_source=None,  # Let system manager auto-select based on config
            energy_provider_config=energy_provider_config,
            addon_options=options,
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

    def _init_ha_controller(self, sensor_config, growatt_device_id=None):
        """Initialize Home Assistant API controller based on environment.

        Args:
            sensor_config: Sensor configuration dictionary to use for the controller.
            growatt_device_id: Growatt device ID for TOU segment operations.
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
            ha_url=ha_url,
            token=ha_token,
            sensor_config=sensor_config,
            growatt_device_id=growatt_device_id,
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
        """Load options from Home Assistant add-on standard location.

        In production: /data/options.json provided by Home Assistant add-on system
        In development: /data/options.json mounted from backend/dev-options.json (extracted by dev-run.sh)

        If the sensor configuration is empty (first-time setup), an overlay from
        /data/bess_discovered_config.json is applied when available.
        """
        options_json = "/data/options.json"

        if os.path.exists(options_json):
            try:
                with open(options_json) as f:
                    options = json.load(f)
                    logger.info(f"Loaded options from {options_json}")
            except Exception as e:
                logger.error(f"Error loading options from {options_json}: {e!s}")
                raise RuntimeError(
                    f"Failed to load configuration from {options_json}. " f"Error: {e}"
                ) from e
        else:
            raise RuntimeError(
                f"Configuration file not found at {options_json}. "
                f"In development, ensure dev-run.sh has extracted options from config.yaml."
            )

        # If sensors are not configured, try to load from previously discovered config
        sensors = options.get("sensors", {})
        configured_count = sum(1 for v in sensors.values() if v)
        if configured_count == 0:
            discovered = self._load_discovered_config()
            if discovered:
                logger.info(
                    "No sensors configured in options.json, applying discovered config "
                    f"({len(discovered.get('sensors', {}))} sensors)"
                )
                options = self._merge_discovered_config(options, discovered)

        return options

    def _load_discovered_config(self) -> dict | None:
        """Load previously discovered sensor config from /data/bess_discovered_config.json."""
        discovered_config_path = "/data/bess_discovered_config.json"
        if not os.path.exists(discovered_config_path):
            return None
        try:
            with open(discovered_config_path, encoding="utf-8") as f:
                config = json.load(f)
                logger.info(f"Loaded discovered config from {discovered_config_path}")
                return config
        except Exception as e:
            logger.warning(f"Could not load discovered config: {e!s}")
            return None

    def _merge_discovered_config(self, options: dict, discovered: dict) -> dict:
        """Merge discovered sensor config into options dict.

        Copies sensor entity IDs, electricity_price area, nordpool config_entry_id,
        and growatt device_id from the discovered config into the options dict.
        Existing non-empty values are not overwritten.
        """
        merged = dict(options)

        # Merge sensors
        if "sensors" in discovered:
            merged_sensors = dict(merged.get("sensors", {}))
            for key, entity_id in discovered["sensors"].items():
                if entity_id and not merged_sensors.get(key):
                    merged_sensors[key] = entity_id
            merged["sensors"] = merged_sensors

        # Merge nordpool area
        if "nordpool_area" in discovered:
            price_config = dict(merged.get("electricity_price", {}))
            if not price_config.get("area"):
                price_config["area"] = discovered["nordpool_area"]
                merged["electricity_price"] = price_config

        # Merge nordpool config_entry_id
        if "nordpool_config_entry_id" in discovered:
            provider_config = dict(merged.get("energy_provider", {}))
            nordpool_official = dict(provider_config.get("nordpool_official", {}))
            if not nordpool_official.get("config_entry_id"):
                nordpool_official["config_entry_id"] = discovered[
                    "nordpool_config_entry_id"
                ]
                provider_config["nordpool_official"] = nordpool_official
                merged["energy_provider"] = provider_config

        # Merge growatt device_id
        if "growatt_device_id" in discovered:
            growatt_config = dict(merged.get("growatt", {}))
            if not growatt_config.get("device_id"):
                growatt_config["device_id"] = discovered["growatt_device_id"]
                merged["growatt"] = growatt_config

        return merged

    def apply_discovered_config(
        self,
        sensor_map: dict,
        nordpool_area: str | None = None,
        nordpool_config_entry_id: str | None = None,
        growatt_device_id: str | None = None,
    ) -> None:
        """Persist discovered config and apply it to the running controller.

        Args:
            sensor_map: dict mapping bess_sensor_key → entity_id
            nordpool_area: Nordpool price area (e.g. "SE4")
            nordpool_config_entry_id: HA config entry ID for Nordpool integration
            growatt_device_id: HA device registry ID for Growatt device
        """
        self._save_discovered_config(
            sensor_map=sensor_map,
            nordpool_area=nordpool_area,
            nordpool_config_entry_id=nordpool_config_entry_id,
            growatt_device_id=growatt_device_id,
        )

        # Apply to running controller so BESS starts using new sensors immediately
        self.ha_controller.sensors.update({k: v for k, v in sensor_map.items() if v})
        if growatt_device_id:
            self.ha_controller.growatt_device_id = growatt_device_id
        if nordpool_area:
            self.system.price_manager.area = nordpool_area

    def _save_discovered_config(
        self,
        sensor_map: dict,
        nordpool_area: str | None = None,
        nordpool_config_entry_id: str | None = None,
        growatt_device_id: str | None = None,
    ) -> None:
        """Persist discovered config to /data/bess_discovered_config.json.

        Uses atomic write (write to temp file, then rename) to prevent
        corruption if the process crashes mid-write.

        Args:
            sensor_map: dict mapping bess_sensor_key → entity_id
            nordpool_area: Nordpool price area (e.g. "SE4")
            nordpool_config_entry_id: HA config entry ID for Nordpool integration
            growatt_device_id: HA device registry ID for Growatt device
        """
        discovered_config_path = "/data/bess_discovered_config.json"
        payload: dict = {"sensors": sensor_map}
        if nordpool_area:
            payload["nordpool_area"] = nordpool_area
        if nordpool_config_entry_id:
            payload["nordpool_config_entry_id"] = nordpool_config_entry_id
        if growatt_device_id:
            payload["growatt_device_id"] = growatt_device_id
        try:
            fd, tmp_path = tempfile.mkstemp(dir="/data", suffix=".json")
            with os.fdopen(fd, "w") as tmp_f:
                json.dump(payload, tmp_f, indent=2)
            os.replace(tmp_path, discovered_config_path)
            logger.info(f"Saved discovered config to {discovered_config_path}")
        except Exception as e:
            logger.error(f"Failed to save discovered config: {e!s}")
            raise

    def _init_scheduler_jobs(self):
        """Configure scheduler jobs."""

        # Quarterly schedule update (every 15 minutes: 0, 15, 30, 45)
        def update_schedule_quarterly():
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15
            self.system.update_battery_schedule(current_period=current_period)

        self.scheduler.add_job(
            update_schedule_quarterly,
            CronTrigger(minute="0,15,30,45"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Next day preparation (daily at 23:55)
        def prepare_next_day():
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15
            self.system.update_battery_schedule(
                current_period=current_period, prepare_next_day=True
            )

        self.scheduler.add_job(
            prepare_next_day,
            CronTrigger(hour=23, minute=55),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Charging power adjustment (every 5 minutes)
        self.scheduler.add_job(
            self.system.adjust_charging_power,
            CronTrigger(minute="*/5"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Discharge inhibit monitoring (every minute)
        self.scheduler.add_job(
            self.system.apply_discharge_inhibit,
            CronTrigger(minute="*"),
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
                "min_soc",
                "max_soc",
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
            required_home_keys = [
                "consumption",
                "currency",
                "max_fuse_current",
                "voltage",
                "safety_margin_factor",
                "phase_count",
                "consumption_strategy",
                "power_monitoring_enabled",
            ]
            for key in required_home_keys:
                if key not in home_config:
                    raise ValueError(
                        f"Required home setting '{key}' is missing from config.yaml"
                    )

            settings = {
                "battery": {
                    "totalCapacity": battery_config["total_capacity"],
                    "minSoc": battery_config["min_soc"],
                    "maxSoc": battery_config["max_soc"],
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
                    "maxFuseCurrent": home_config["max_fuse_current"],
                    "voltage": home_config["voltage"],
                    "safetyMargin": home_config["safety_margin_factor"],
                    "phaseCount": home_config["phase_count"],
                    "consumptionStrategy": home_config["consumption_strategy"],
                    "powerMonitoringEnabled": home_config["power_monitoring_enabled"],
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
                exc_info=True,
            )
            raise RuntimeError(
                f"Settings application failed - system cannot start safely. "
                f"Check config.yaml for invalid or missing settings. Error: {e}"
            ) from e

    def start(self):
        """Start the scheduler."""
        self.system.start()
        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15
        self.system.update_battery_schedule(current_period=current_period)
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


# SPA catch-all: serve index.html for any path not matched by API or asset routes
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, request: Request):
    return FileResponse("/app/frontend/index.html")
