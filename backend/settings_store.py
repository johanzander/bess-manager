"""Unified persistent settings store for BESS Manager.

All operational settings (battery, home, electricity_price, energy_provider,
growatt, sensors) are stored in /data/bess_settings.json, which is owned and
managed by this add-on.  InfluxDB credentials are the only settings that remain
in the HA Supervisor-controlled /data/options.json.

On first boot the store migrates existing settings from options.json so existing
users are not affected by the transition.
"""

import errno
import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

SETTINGS_PATH = "/data/bess_settings.json"

# Top-level sections that live in bess_settings.json (not options.json).
OWNED_SECTIONS = (
    "home",
    "battery",
    "electricity_price",
    "energy_provider",
    "growatt",
    "sensors",
)


class SettingsStore:
    """Read/write /data/bess_settings.json with atomic writes.

    The in-memory representation mirrors the JSON structure exactly so callers
    can treat ``store.data`` as a plain dict.
    """

    def __init__(self) -> None:
        self.data: dict = {}
        self._use_direct_write: bool = False  # set after first EBUSY

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, options: dict) -> None:
        """Load settings, migrating from options.json on first boot.

        Args:
            options: Full contents of /data/options.json (provided by HA
                     Supervisor).  Used only when bess_settings.json is absent
                     or empty (first-boot migration).
        """
        if os.path.exists(SETTINGS_PATH):
            loaded = self._read()
            if loaded:
                self.data = loaded
                logger.info(
                    "Loaded settings from %s (%d sections)",
                    SETTINGS_PATH,
                    len(self.data),
                )
                self._migrate_schema()
                # Always overlay sensors/discovery from options if bess_settings
                # has empty sensors (handles wizard flow after fresh migration).
                self._overlay_discovered(options)
                return

        # First boot: migrate from options.json
        logger.info("bess_settings.json absent or empty — migrating from options.json")
        self.data = self._migrate_from_options(options)
        self._migrate_schema()  # normalise any legacy field names copied from options.json
        self._write(self.data)
        logger.info(
            "Migration complete: wrote %d sections to %s",
            len(self.data),
            SETTINGS_PATH,
        )

    def get_section(self, name: str) -> dict:
        """Return a copy of a settings section dict.

        Args:
            name: Section key (e.g. 'battery', 'sensors').

        Returns:
            Dict copy of that section (empty dict if missing).
        """
        return dict(self.data.get(name, {}))

    def save_section(self, name: str, data: dict) -> None:
        """Persist a single section atomically.

        Args:
            name: Section key.
            data: New section contents (replaces existing).
        """
        self.data[name] = dict(data)
        self._write(self.data)
        logger.info("Saved settings section '%s'", name)

    def save_all(self, data: dict) -> None:
        """Replace all owned sections atomically.

        Args:
            data: Full settings dict (may contain only owned sections).
        """
        for section in OWNED_SECTIONS:
            if section in data:
                self.data[section] = dict(data[section])
        self._write(self.data)
        logger.info("Saved all settings to %s", SETTINGS_PATH)

    def apply_discovered(
        self,
        sensor_map: dict,
        nordpool_area: str | None = None,
        nordpool_config_entry_id: str | None = None,
        growatt_device_id: str | None = None,
    ) -> None:
        """Merge auto-discovered values into the store and persist.

        Sensors: non-empty discovered values always overwrite existing ones so
        that re-running discovery can correct previously wrong entity IDs.
        Empty strings are ignored so that a partial discovery run does not
        erase sensors that were already configured.

        Nordpool area, config_entry_id, and Growatt device_id are additive:
        they are only written when the field is currently empty.

        Args:
            sensor_map: Mapping of bess_sensor_key -> entity_id.
            nordpool_area: Nordpool price area (e.g. ``"SE4"``).
            nordpool_config_entry_id: HA config entry UUID for Nordpool.
            growatt_device_id: HA device registry ID for the Growatt device.
        """
        # Sensors: overwrite with any non-empty discovered value.
        # Empty strings are skipped so a partial discovery does not erase
        # already-configured sensors.
        sensors = dict(self.data.get("sensors", {}))
        for key, entity_id in sensor_map.items():
            if entity_id:
                sensors[key] = entity_id
        self.data["sensors"] = sensors

        # Nordpool area
        if nordpool_area:
            price = dict(self.data.get("electricity_price", {}))
            if not price.get("area"):
                price["area"] = nordpool_area
                self.data["electricity_price"] = price

        # Nordpool config_entry_id
        if nordpool_config_entry_id:
            ep = dict(self.data.get("energy_provider", {}))
            nordpool_official = dict(ep.get("nordpool_official", {}))
            if not nordpool_official.get("config_entry_id"):
                nordpool_official["config_entry_id"] = nordpool_config_entry_id
                ep["nordpool_official"] = nordpool_official
                self.data["energy_provider"] = ep

        # Growatt device_id
        if growatt_device_id:
            growatt = dict(self.data.get("growatt", {}))
            if not growatt.get("device_id"):
                growatt["device_id"] = growatt_device_id
                self.data["growatt"] = growatt

        self._write(self.data)
        logger.info("Persisted discovered config (%d sensors)", len(sensor_map))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read(self) -> dict:
        """Read bess_settings.json, returning empty dict on error."""
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            logger.warning("Could not read %s: %s", SETTINGS_PATH, e)
            return {}

    def _write(self, data: dict) -> None:
        """Write data to bess_settings.json via a temp file.

        Attempts an atomic rename first.  Some container filesystems (overlayfs,
        CIFS) return EBUSY on rename — in that case fall back to a direct
        overwrite.  Once EBUSY is seen the fallback is used for all subsequent
        writes so the failing syscall is not retried every time.
        """
        data_dir = os.path.dirname(SETTINGS_PATH)
        tmp_path: str | None = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if self._use_direct_write:
                self._copy_and_remove(tmp_path)
            else:
                try:
                    os.replace(tmp_path, SETTINGS_PATH)
                except OSError as e:
                    if e.errno != errno.EBUSY:
                        raise
                    logger.warning(
                        "os.replace EBUSY on %s — switching to direct write for all future saves",
                        SETTINGS_PATH,
                    )
                    self._use_direct_write = True
                    self._copy_and_remove(tmp_path)
        except OSError as e:
            logger.error("Failed to write %s: %s", SETTINGS_PATH, e)
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def _copy_and_remove(self, tmp_path: str) -> None:
        """Overwrite SETTINGS_PATH with tmp_path content, then delete tmp_path."""
        with open(tmp_path, encoding="utf-8") as src:
            content = src.read()
        with open(SETTINGS_PATH, "w", encoding="utf-8") as dst:
            dst.write(content)
        os.unlink(tmp_path)

    @staticmethod
    def _migrate_from_options(options: dict) -> dict:
        """Extract owned sections from options.json into a settings dict.

        Falls back to bootstrap defaults (from core constants) when options
        contains no operational sections — i.e. on a fresh installation before
        the setup wizard has run.

        Args:
            options: Full /data/options.json contents.

        Returns:
            Dict containing only OWNED_SECTIONS extracted from options.
        """
        result: dict = {}
        for section in OWNED_SECTIONS:
            if section in options:
                result[section] = dict(options[section])

        if not result:
            result = SettingsStore._bootstrap_defaults()
            logger.info("No operational settings found — applying bootstrap defaults")

        return result

    @staticmethod
    def _bootstrap_defaults() -> dict:
        """Minimal default settings for first boot before the setup wizard runs.

        Values are sourced from core/bess/settings.py constants so there is a
        single source of truth.  The wizard overwrites these with the user's
        actual values.
        """
        from core.bess.settings import (
            ADDITIONAL_COSTS,
            BATTERY_CHARGE_CYCLE_COST,
            BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW,
            BATTERY_MAX_SOC,
            BATTERY_MIN_ACTION_PROFIT_THRESHOLD,
            BATTERY_MIN_SOC,
            BATTERY_STORAGE_SIZE_KWH,
            DEFAULT_AREA,
            DEFAULT_CURRENCY,
            HOME_HOURLY_CONSUMPTION_KWH,
            HOUSE_MAX_FUSE_CURRENT_A,
            HOUSE_VOLTAGE_V,
            MARKUP_RATE,
            SAFETY_MARGIN_FACTOR,
            TAX_REDUCTION,
            VAT_MULTIPLIER,
        )

        return {
            "battery": {
                "total_capacity": BATTERY_STORAGE_SIZE_KWH,
                "min_soc": BATTERY_MIN_SOC,
                "max_soc": BATTERY_MAX_SOC,
                "max_charge_power_kw": BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW,
                "max_discharge_power_kw": BATTERY_MAX_CHARGE_DISCHARGE_POWER_KW,
                "cycle_cost_per_kwh": BATTERY_CHARGE_CYCLE_COST,
                "min_action_profit_threshold": BATTERY_MIN_ACTION_PROFIT_THRESHOLD,
            },
            "home": {
                "default_hourly": HOME_HOURLY_CONSUMPTION_KWH,
                "currency": DEFAULT_CURRENCY,
                "consumption_strategy": "fixed",
                "max_fuse_current": HOUSE_MAX_FUSE_CURRENT_A,
                "voltage": HOUSE_VOLTAGE_V,
                "safety_margin": SAFETY_MARGIN_FACTOR,
                "phase_count": 1,
                "power_monitoring_enabled": False,
            },
            "electricity_price": {
                "markup_rate": MARKUP_RATE,
                "vat_multiplier": VAT_MULTIPLIER,
                "additional_costs": ADDITIONAL_COSTS,
                "tax_reduction": TAX_REDUCTION,
                "area": DEFAULT_AREA,
            },
            "energy_provider": {
                "provider": "nordpool_official",
                "nordpool_official": {"config_entry_id": ""},
                "nordpool": {},
                "octopus": {},
            },
            "growatt": {"inverter_type": "", "device_id": ""},
            "sensors": {},
        }

    def _migrate_schema(self) -> None:
        """Add missing keys and normalize field names introduced in newer schema versions.

        Called after loading bess_settings.json so that old files are silently
        upgraded in place.  Values are sourced from core constants so there is a
        single source of truth.
        """
        from core.bess.settings import (
            BATTERY_CHARGE_CYCLE_COST,
            BATTERY_DEFAULT_CHARGING_POWER_RATE,
            BATTERY_EFFICIENCY_CHARGE,
            BATTERY_EFFICIENCY_DISCHARGE,
            BATTERY_MIN_ACTION_PROFIT_THRESHOLD,
        )

        changed = False

        battery = self.data.get("battery")
        if isinstance(battery, dict):
            # Rename: max_charge_discharge_power → max_charge_power_kw + max_discharge_power_kw
            if "max_charge_discharge_power" in battery and "max_charge_power_kw" not in battery:
                power = battery.pop("max_charge_discharge_power")
                battery["max_charge_power_kw"] = power
                battery["max_discharge_power_kw"] = power
                logger.info("Schema migration: renamed max_charge_discharge_power → max_charge_power_kw/max_discharge_power_kw = %s", power)
                changed = True

            # Rename: cycle_cost → cycle_cost_per_kwh
            if "cycle_cost" in battery and "cycle_cost_per_kwh" not in battery:
                battery["cycle_cost_per_kwh"] = battery.pop("cycle_cost")
                logger.info("Schema migration: renamed cycle_cost → cycle_cost_per_kwh = %s", battery["cycle_cost_per_kwh"])
                changed = True

            # Add missing fields with defaults
            for key, default in (
                ("cycle_cost_per_kwh", BATTERY_CHARGE_CYCLE_COST),
                ("min_action_profit_threshold", BATTERY_MIN_ACTION_PROFIT_THRESHOLD),
                ("charging_power_rate", BATTERY_DEFAULT_CHARGING_POWER_RATE),
                ("efficiency_charge", BATTERY_EFFICIENCY_CHARGE),
                ("efficiency_discharge", BATTERY_EFFICIENCY_DISCHARGE),
            ):
                if key not in battery:
                    battery[key] = default
                    logger.info("Schema migration: added battery.%s = %s", key, default)
                    changed = True

            if changed:
                self.data["battery"] = battery

        home = self.data.get("home")
        if isinstance(home, dict):
            # Rename: consumption → default_hourly  (matches HomeSettings attribute name)
            if "consumption" in home and "default_hourly" not in home:
                home["default_hourly"] = home.pop("consumption")
                logger.info("Schema migration: renamed home.consumption → home.default_hourly = %s", home["default_hourly"])
                changed = True

            # Rename: safety_margin_factor → safety_margin  (matches HomeSettings attribute name)
            if "safety_margin_factor" in home and "safety_margin" not in home:
                home["safety_margin"] = home.pop("safety_margin_factor")
                logger.info("Schema migration: renamed home.safety_margin_factor → home.safety_margin = %s", home["safety_margin"])
                changed = True

            if changed:
                self.data["home"] = home

        if changed:
            self._write(self.data)

    def _overlay_discovered(self, options: dict) -> None:
        """Apply legacy bess_discovered_config.json values if present.

        This handles the transition period where some users may have a
        bess_discovered_config.json written by the previous code.  Values are
        only applied when the corresponding field is empty in the store.
        """
        legacy_path = "/data/bess_discovered_config.json"
        if not os.path.exists(legacy_path):
            # Also check if sensors section from options should be merged
            # (e.g. wizard was never run but options has sensors)
            sensors_in_options = options.get("sensors", {})
            configured = sum(1 for v in sensors_in_options.values() if v)
            if configured > 0:
                sensors = dict(self.data.get("sensors", {}))
                own_configured = sum(1 for v in sensors.values() if v)
                if own_configured == 0:
                    logger.info(
                        "Overlaying %d sensors from options.json into store",
                        configured,
                    )
                    self.data["sensors"] = dict(sensors_in_options)
                    self._write(self.data)
            return

        try:
            with open(legacy_path, encoding="utf-8") as f:
                discovered = json.load(f)
            logger.info("Applying legacy bess_discovered_config.json overlay")
            self.apply_discovered(
                sensor_map=discovered.get("sensors", {}),
                nordpool_area=discovered.get("nordpool_area"),
                nordpool_config_entry_id=discovered.get("nordpool_config_entry_id"),
                growatt_device_id=discovered.get("growatt_device_id"),
            )
        except (OSError, ValueError) as e:
            logger.warning("Could not apply legacy discovered config: %s", e)
