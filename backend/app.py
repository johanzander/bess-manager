import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from threading import Thread
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Import BESS system modules
from core.bess import BatterySystemManager
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.price_manager import HANordpoolSource

import log_config
from loguru import logger

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
    app.mount("/assets", StaticFiles(directory=f"{static_directory}/assets"), name="assets")

@app.get("/status")
def get_status():
    return {"status": "ok", "ingress_prefix": INGRESS_PREFIX}

    
class BESSController:
    def __init__(self):
        """Initialize the BESS Controller."""
        # Load environment variables
        load_dotenv('/data/options.env')

        # Initialize Home Assistant API Controller
        self.ha_controller = self._init_ha_controller()
        
        # Initialize price source
        self.price_source = HANordpoolSource(self.ha_controller)
        
        # Create Battery System Manager
        self.system = BatterySystemManager(
            controller=self.ha_controller, 
            price_source=self.price_source
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
        
        logger.info(f"Initializing HA controller with {len(sensor_config)} sensor configurations")
        
        return HomeAssistantAPIController(
            base_url=ha_url, 
            token=ha_token,
            sensor_config=sensor_config
        )
        
    def _load_and_apply_settings(self):
        """Load options and apply settings."""
        try:
            options = self._load_options()
            if options:
                settings = {
                    "battery": {
                        "totalCapacity": options["battery"]["total_capacity"],
                        "minSoc": options["battery"]["min_soc"],
                        "chargeCycleCost": options["battery"]["cycle_cost"],
                        "chargingPowerRate": options["battery"]["charging_power_rate"]
                    },
                    "consumption": {
                        "defaultHourly": options["consumption"]["default_hourly"]
                    },
                    "price": {
                        "area": options["price"]["area"],
                        "markupRate": options["price"]["markup_rate"],
                        "vatMultiplier": options["price"]["vat_multiplier"],
                        "additionalCosts": options["price"]["additional_costs"],
                        "taxReduction": options["price"]["tax_reduction"],
                        "useActualPrice": options["price"]["use_actual_price"]
                    }
                }
                self.system.update_settings(settings)
                logger.info("Loaded settings from configuration")
        except Exception as e:
            logger.error("Error loading settings: %s", str(e))

    def _load_options(self):
        """Load options from Home Assistant add-on config or environment vars."""
        import yaml
        
        options_json = "/data/options.json"
        config_yaml = "/app/config.yaml"
        
        # First try the standard options.json (production)
        if os.path.exists(options_json):
            try:
                with open(options_json, "r") as f:
                    options = json.load(f)
                    logger.info(f"Loaded options from {options_json}")
                    return options
            except Exception as e:
                logger.error(f"Error loading options from {options_json}: {str(e)}")
        
        # If not available, try to load from config.yaml directly (development)
        if os.path.exists(config_yaml):
            try:
                with open(config_yaml, "r") as f:
                    config = yaml.safe_load(f)
                    
                # Extract options section if it exists
                if "options" in config:
                    options = config["options"]
                    logger.info(f"Loaded options from {config_yaml} (options section)")
                    return options
                    
                logger.warning(f"No 'options' section found in {config_yaml}, using entire file")
                return config
            except Exception as e:
                logger.error(f"Error loading from {config_yaml}: {str(e)}")
        

    def _init_scheduler(self):
        """Configure scheduler jobs."""

        # Hourly schedule update (every hour at xx:00)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(hour=datetime.now().hour),
            CronTrigger(minute=0)
        )

        # Next day preparation (daily at 23:55)
        self.scheduler.add_job(
            lambda: self.system.update_battery_schedule(hour=datetime.now().hour, prepare_next_day=True),
            CronTrigger(hour=23, minute=55)
        )

        # Inverter settings verification (every 15 minutes)
#        self.scheduler.add_job(
#            lambda: self.system.verify_inverter_settings(hour=datetime.now().hour),
#            CronTrigger(minute='*/15')
#        )

        # Charging power adjustment (every 5 minutes)
        self.scheduler.add_job(
            self.system.adjust_charging_power, 
            CronTrigger(minute='*/5')
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


# Create middleware to log request paths for debugging
@app.middleware("http")
async def fix_cloudflared_headers(request: Request, call_next):
    """Fix headers for requests coming through Cloudflared tunnel."""
    # Log all headers for debugging
    logger.info(f"Request headers: {dict(request.headers)}")
    
    # Check if this is a proxied request (via Cloudflared)
    host = request.headers.get("host", "")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    
    logger.info(f"Request host: {host}, forwarded_proto: {forwarded_proto}")
    
    response = await call_next(request)
    return response

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

@app.get("/health")
async def health_check():
    """Fast health check endpoint for Cloudflare."""
    return {"status": "ok"}

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
        return settings["battery"]
    except Exception as e:
        logger.error(f"Error getting battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings/battery")
async def update_battery_settings(settings: dict):
    """Update battery settings."""
    try:
        bess_controller.system.update_settings({"battery": settings})
        return {"message": "Battery settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating battery settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
            "taxReduction": settings["price"]["taxReduction"]
        }
    except Exception as e:
        logger.error(f"Error getting electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
                "taxReduction": settings["taxReduction"]
            }
        }
        
        bess_controller.system.update_settings(new_settings)
        return {"message": "Electricity settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating electricity settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/schedule")
async def get_battery_schedule(
    date: str = Query(None, description="Date in YYYY-MM-DD format"),
):
    """Get battery schedule data for dashboard."""
    try:
        target_date = (
            datetime.strptime(date, "%Y-%m-%d").date()
            if date
            else datetime.now().date()
        )
        schedule = bess_controller.system.create_schedule(price_date=target_date)
        return schedule.get_schedule_data()
    except Exception as e:
        logger.error(f"Error getting battery schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/predictions/consumption")
async def get_consumption_predictions():
    """Get hourly consumption predictions for the next 24 hours."""
    try:
        predictions = bess_controller.system._energy_manager.get_consumption_predictions()
        return {"data": [float(val) for val in predictions]}
    except Exception as e:
        logger.error(f"Error getting consumption predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/predictions/solar")
async def get_solar_predictions():
    """Get hourly solar production predictions for the next 24 hours."""
    try:
        predictions = bess_controller.system._energy_manager.get_solar_predictions()
        return {"data": [float(val) for val in predictions]}
    except Exception as e:
        logger.error(f"Error getting solar predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/energy/balance")
async def get_energy_balance():
    """Get the current energy balance report."""
    try:
        hourly_data, totals = bess_controller.system._energy_manager.log_energy_balance()
        
        # Convert to serializable format (converting numpy arrays if present)
        hourly_data_serializable = []
        for data in hourly_data:
            serializable_item = {}
            for k, v in data.items():
                serializable_item[k] = float(v) if isinstance(v, (float, int)) else v
            hourly_data_serializable.append(serializable_item)
        
        totals_serializable = {}
        for k, v in totals.items():
            totals_serializable[k] = float(v) if isinstance(v, (float, int)) else v
        
        return {
            "hourlyData": hourly_data_serializable,
            "totals": totals_serializable
        }
    except Exception as e:
        logger.error(f"Error getting energy balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/energy/profile")
async def get_energy_profile(
    current_hour: int = Query(None, description="Current hour (0-23)")
):
    """Get the full energy profile combining historical and predicted data."""
    try:
        # Use current hour if not specified
        if current_hour is None:
            current_hour = datetime.now().hour
        
        profile = bess_controller.system._energy_manager.get_full_day_energy_profile(current_hour)
        
        # Convert numpy arrays to Python lists if needed
        for key in profile:
            if hasattr(profile[key], 'tolist'):
                profile[key] = profile[key].tolist()
        
        return profile
    except Exception as e:
        logger.error(f"Error getting energy profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/schedule/detailed")
async def get_detailed_schedule(
    date: str = Query(None, description="Date in YYYY-MM-DD format"),
):
    """Get detailed battery schedule with energy data."""
    try:
        target_date = (
            datetime.strptime(date, "%Y-%m-%d").date()
            if date
            else datetime.now().date()
        )
        
        # Get the basic schedule
        schedule = bess_controller.system.create_schedule(price_date=target_date)
        schedule_data = schedule.get_schedule_data()
        
        # Get the energy profile for additional data
        current_hour = datetime.now().hour if target_date == datetime.now().date() else 0
        energy_profile = bess_controller.system._energy_manager.get_full_day_energy_profile(current_hour)
        
        # Add energy profile data to the response
        return {
            **schedule_data,
            "energyProfile": {
                "consumption": energy_profile["consumption"],
                "solar": energy_profile["solar"],
                "battery_soc": energy_profile["battery_soc"],
                "actualHours": energy_profile.get("actual_hours", 0),
            }
        }
    except Exception as e:
        logger.error(f"Error getting detailed schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/system/status")
async def get_system_status():
    """Get current system status including battery state and active flows."""
    try:
        current_hour = datetime.now().hour
        
        status = {
            "timestamp": datetime.now().isoformat(),
            "battery": {
                "soc": bess_controller.system._controller.get_battery_soc(),
                "charging_power": bess_controller.system._controller.get_battery_charge_power(),
                "discharging_power": bess_controller.system._controller.get_battery_discharge_power(),
                "grid_charge_enabled": bess_controller.system._controller.grid_charge_enabled(),
                "charging_power_rate": bess_controller.system._controller.get_charging_power_rate(),
                "discharging_power_rate": bess_controller.system._controller.get_discharging_power_rate(),
            },
            "energy": {}
        }
        
        # Add today's energy data if available
        if hasattr(bess_controller.system._energy_manager, "get_energy_data"):
            try:
                energy_data = bess_controller.system._energy_manager.get_energy_data(current_hour)
                if energy_data:
                    status["energy"] = {
                        "solar_production": bess_controller.system._controller.get_solar_generation_today(),
                        "grid_import": bess_controller.system._controller.get_import_from_grid_today(),
                        "grid_export": bess_controller.system._controller.get_export_to_grid_today(),
                        "load_consumption": bess_controller.system._controller.get_load_consumption_today(),
                        "battery_charge": bess_controller.system._controller.get_battery_charge_today(),
                        "battery_discharge": bess_controller.system._controller.get_battery_discharge_today(),
                        "grid_to_battery": bess_controller.system._controller.get_grid_to_battery_today(),
                    }
            except Exception as e:
                logger.warning(f"Could not get energy data for current hour: {e}")
        
        return status
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))