"""Unified persistent settings store for BESS Manager.

All operational settings (battery, home, electricity_price, energy_provider,
growatt, sensors) are stored in /data/bess_settings.json, which is owned and
managed by this add-on.  InfluxDB credentials are the only settings that remain
in the HA Supervisor-controlled /data/options.json.

On first boot the store migrates existing settings from options.json so existing
users are not affected by the transition.
"""

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
                # Always overlay sensors/discovery from options if bess_settings
                # has empty sensors (handles wizard flow after fresh migration).
                self._overlay_discovered(options)
                return

        # First boot: migrate from options.json
        logger.info("bess_settings.json absent or empty — migrating from options.json")
        self.data = self._migrate_from_options(options)
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

        Existing non-empty values are not overwritten (discovery is additive).

        Args:
            sensor_map: Mapping of bess_sensor_key -> entity_id.
            nordpool_area: Nordpool price area (e.g. ``"SE4"``).
            nordpool_config_entry_id: HA config entry UUID for Nordpool.
            growatt_device_id: HA device registry ID for the Growatt device.
        """
        # Sensors
        sensors = dict(self.data.get("sensors", {}))
        for key, entity_id in sensor_map.items():
            if entity_id and not sensors.get(key):
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
        """Atomically write data to bess_settings.json."""
        data_dir = os.path.dirname(SETTINGS_PATH)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, SETTINGS_PATH)
        except OSError as e:
            logger.error("Failed to write %s: %s", SETTINGS_PATH, e)
            raise

    @staticmethod
    def _migrate_from_options(options: dict) -> dict:
        """Extract owned sections from options.json into a settings dict.

        Args:
            options: Full /data/options.json contents.

        Returns:
            Dict containing only OWNED_SECTIONS extracted from options.
        """
        result: dict = {}
        for section in OWNED_SECTIONS:
            if section in options:
                result[section] = dict(options[section])
        return result

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
