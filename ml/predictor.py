"""Prediction module for ML energy consumption forecasting.

Loads a trained XGBoost model and generates 96 quarter-hourly
consumption predictions using direct multi-output prediction:
a single model.predict(X) call on a pre-built 96-row feature matrix.

Each row contains only features known ahead of time:
- Time features (deterministic)
- Weather forecast (from Home Assistant)
- Historical context (from InfluxDB, computed once)
"""

import logging
from datetime import date, datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data_fetcher import (
    PERIODS_PER_DAY,
    fetch_history_context,
    fetch_weather_forecast,
)

_LOGGER = logging.getLogger(__name__)

QUARTER_MINUTES = 15


def _build_future_timestamps(
    config: dict,
    target_date: date,
    periods: int = PERIODS_PER_DAY,
) -> pd.DatetimeIndex:
    """Generate 15-minute timestamps covering target_date from midnight."""
    from ml.data_fetcher import _get_local_tz

    local_tz = _get_local_tz(config)
    start = datetime.combine(target_date, time.min, tzinfo=local_tz)
    return pd.date_range(start=start, periods=periods, freq="15min")


def _build_prediction_dataframe(
    future_timestamps: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build a raw DataFrame for the 96 future periods.

    Creates a DataFrame indexed by future timestamps with a dummy 'target'
    column (NaN, since we're predicting it). Weather and history context
    features are added during feature engineering.
    """
    df = pd.DataFrame(index=future_timestamps)
    df.index.name = None

    # Target is what we're predicting - use NaN placeholder
    df["target"] = np.nan

    return df


def predict_next_24h(config: dict, target_date: date) -> list[float]:
    """Generate 96 quarter-hourly consumption predictions for target_date.

    Uses direct multi-output prediction: builds a 96-row feature matrix
    with time features, weather forecast, and history context, then makes
    a single model.predict(X) call.

    Args:
        config: Resolved ML config dict.
        target_date: Local calendar date to forecast (midnight to midnight).

    Returns:
        List of 96 float values representing predicted consumption
        in kWh per 15-minute period. This format matches what
        battery_system_manager.optimize_battery_schedule() expects
        for the home_consumption parameter.

    Raises:
        FileNotFoundError: If no trained model exists.
        RuntimeError: If data fetching fails.
    """
    from xgboost import XGBRegressor

    from ml.feature_engineer import engineer_features

    model_path = config["model_path"]
    if not Path(model_path).exists():
        raise FileNotFoundError(
            f"No trained model found at {model_path}. Run 'train' first."
        )

    # Load feature column names
    feature_meta_path = str(Path(model_path).with_suffix(".features.txt"))
    if not Path(feature_meta_path).exists():
        raise FileNotFoundError(
            f"Feature metadata not found at {feature_meta_path}. Retrain the model."
        )

    with open(feature_meta_path) as f:
        feature_columns = [line.strip() for line in f.readlines() if line.strip()]

    _LOGGER.info("Loading model from %s", model_path)
    model = XGBRegressor()
    model.load_model(model_path)
    _LOGGER.info("Using %d features: %s", len(feature_columns), feature_columns)

    # Step 1: Generate future timestamps anchored at target_date midnight
    future_ts = _build_future_timestamps(config, target_date)
    _LOGGER.info(
        "Predicting %d periods for %s: %s to %s",
        len(future_ts),
        target_date,
        future_ts[0],
        future_ts[-1],
    )

    # Step 2: Fetch weather forecast from HA
    _LOGGER.info("Fetching weather forecast from Home Assistant...")
    weather_df = fetch_weather_forecast(config)

    # Step 3: Fetch history context from InfluxDB (anchored to target_date)
    _LOGGER.info("Fetching history context from InfluxDB for %s...", target_date)
    history_context = fetch_history_context(config, target_date=target_date)

    # Step 4: Build raw DataFrame for future periods
    raw_df = _build_prediction_dataframe(future_ts)

    # Step 5: Engineer features (weather + history context + time features)
    feature_df, _ = engineer_features(
        raw_df,
        config,
        convert_target_to_kwh=False,
        weather_df=weather_df,
        history_context=history_context,
    )

    # Ensure feature columns match training order
    missing_cols = set(feature_columns) - set(feature_df.columns)
    if missing_cols:
        raise RuntimeError(
            f"Feature mismatch: model expects {missing_cols} but they are missing "
            f"from prediction features. Available: {list(feature_df.columns)}"
        )

    X = feature_df[feature_columns].values

    # Step 6: Single predict call
    _LOGGER.info("Running model.predict() on %d-row feature matrix...", len(X))
    predictions = model.predict(X)

    # Clamp to non-negative (consumption can't be negative)
    predictions = np.maximum(predictions, 0.0)

    result = predictions.tolist()

    # Log summary statistics
    total_kwh = sum(result)
    _LOGGER.info(
        "Prediction summary for %s: total %.2f kWh, "
        "min %.3f kWh, max %.3f kWh, mean %.3f kWh per 15min",
        target_date,
        total_kwh,
        min(result),
        max(result),
        total_kwh / len(result),
    )

    return result


def predict_with_timestamps(
    config: dict, target_date: date
) -> list[tuple[datetime, float]]:
    """Generate predictions with their associated timestamps.

    Convenience wrapper that pairs each prediction with its timestamp.

    Args:
        config: Resolved ML config dict.
        target_date: Local calendar date to forecast.

    Returns:
        List of (datetime, kWh) tuples for 96 quarter-hourly periods.
    """
    future_ts = _build_future_timestamps(config, target_date)
    predictions = predict_next_24h(config, target_date)

    return [
        (ts.to_pydatetime(), pred)
        for ts, pred in zip(future_ts, predictions, strict=True)
    ]
