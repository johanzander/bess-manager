"""Configuration loading for ML energy predictor.

Loads ml_config.yaml with environment variable interpolation,
resolving ${ENV_VAR} syntax from the environment or a .env file.
"""

import logging
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

_LOGGER = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

DEFAULT_MODEL_PATH = "ml/trained_model.json"


def _resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} placeholders with environment variable values.

    Raises:
        KeyError: If an environment variable is not set.
    """

    def _replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise KeyError(
                f"Environment variable '{var_name}' is not set. "
                f"Check your .env file or environment."
            )
        return env_value

    return _ENV_VAR_PATTERN.sub(_replacer, value)


def _resolve_recursive(obj: object) -> object:
    """Walk a nested dict/list and resolve all string values containing ${...}."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_recursive(item) for item in obj]
    return obj


def _build_from_app_options(app_options: dict) -> dict:
    """Build ML config dict from the main app options (/data/options.json).

    InfluxDB and HA credentials are read from environment variables (they are
    never written to options.json). ML settings come from the 'ml' section.
    The target sensor is derived from sensors.local_load_power.
    """
    ml = app_options["ml"]
    sensors = app_options.get("sensors", {})

    local_load = sensors.get("local_load_power", "")
    if local_load.startswith("sensor."):
        local_load = local_load[len("sensor."):]

    raw_feature_sensors = ml.get("feature_sensors", {})
    feature_sensors = {
        k: v[len("sensor."):] if isinstance(v, str) and v.startswith("sensor.") else v
        for k, v in raw_feature_sensors.items()
    }

    return {
        "influxdb": {
            "url": os.environ["HA_DB_URL"],
            "bucket": os.environ["HA_DB_BUCKET"],
            "username": os.environ["HA_DB_USER_NAME"],
            "password": os.environ["HA_DB_PASSWORD"],
        },
        "ha_api": {
            "url": os.environ["HA_URL"],
            "token": os.environ["HA_TOKEN"],
            "weather_entity": ml["weather_entity"],
        },
        "location": ml["location"],
        "target": {
            "sensor": local_load,
            "unit": "W",
        },
        "feature_sensors": feature_sensors,
        "derived_features": ml["derived_features"],
        "history_context": ml["history_context"],
        "training": ml["training"],
        "model_path": DEFAULT_MODEL_PATH,
    }


def load_config(
    config_path: str | None = None, app_options: dict | None = None
) -> dict:
    """Load and resolve the ML configuration.

    When app_options is provided (the main app /data/options.json dict), the
    config is built directly from it and no YAML file is read. This is the
    path used by the live system.

    When app_options is None, falls back to loading ml_config.yaml from disk
    (used by the standalone CLI tools).

    Args:
        config_path: Path to ml_config.yaml for CLI use. Ignored when
                     app_options is provided.
        app_options: Main app options dict. When set, config is derived
                     from the app config + environment variables.

    Returns:
        Fully resolved configuration dictionary.

    Raises:
        FileNotFoundError: If config file does not exist (CLI path only).
        KeyError: If required environment variables are missing.
    """
    # Load .env file for local development (needed for env var resolution)
    project_root = Path(__file__).resolve().parent.parent
    dotenv_path = project_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
        _LOGGER.debug("Loaded .env from %s", dotenv_path)

    if app_options is not None:
        _LOGGER.info("ML config built from app options")
        return _build_from_app_options(app_options)

    if config_path is None:
        config_path = str(project_root / "ml_config.yaml")

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"ML config file not found: {config_path}")

    with open(path) as f:
        raw_config = yaml.safe_load(f)

    resolved = _resolve_recursive(raw_config)
    assert isinstance(resolved, dict)

    resolved.setdefault("model_path", DEFAULT_MODEL_PATH)

    _LOGGER.info("ML config loaded from %s", config_path)
    return resolved
