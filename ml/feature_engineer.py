"""Feature engineering for ML energy consumption prediction.

Creates a feature matrix from raw sensor DataFrames by adding
temporal features, daylight hours, weather forecast data, and
historical consumption context.
"""

import logging
import math
from datetime import date

import numpy as np
import pandas as pd
from astral import LocationInfo
from astral.sun import sun

_LOGGER = logging.getLogger(__name__)

WATTS_TO_KWH_15MIN = 1.0 / (4 * 1000)


def _add_cyclical_encoding(
    df: pd.DataFrame,
    values: pd.Series,
    name: str,
    period: float,
) -> pd.DataFrame:
    """Add sin/cos cyclical encoding for a periodic feature."""
    radians = 2 * math.pi * values / period
    df[f"{name}_sin"] = np.sin(radians)
    df[f"{name}_cos"] = np.cos(radians)
    return df


def _add_time_features(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Add temporal features derived from the DataFrame index."""
    derived = config["derived_features"]
    index = df.index

    if derived.get("hour_of_day", False):
        # Use fractional hour (0.0-23.75) for quarter-hour granularity
        fractional_hour = index.hour + index.minute / 60.0
        df = _add_cyclical_encoding(df, fractional_hour, "hour", 24.0)

    if derived.get("day_of_week", False):
        df = _add_cyclical_encoding(df, index.dayofweek, "dow", 7.0)
        df["is_weekend"] = (index.dayofweek >= 5).astype(int)

    return df


def _compute_daylight_hours(
    target_date: date, latitude: float, longitude: float, timezone: str
) -> float:
    """Compute daylight hours for a given date and location using astral."""
    location = LocationInfo(
        name="location",
        region="",
        timezone=timezone,
        latitude=latitude,
        longitude=longitude,
    )
    try:
        s = sun(location.observer, date=target_date)
        daylight_seconds = (s["sunset"] - s["sunrise"]).total_seconds()
        return daylight_seconds / 3600.0
    except ValueError:
        # Polar regions: sun doesn't rise or set
        # Return 0 for polar night, 24 for midnight sun
        _LOGGER.warning("Could not compute sunrise/sunset for %s", target_date)
        return 12.0


def _add_daylight_feature(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Add daylight hours feature for each row based on its date."""
    if not config["derived_features"].get("daylight_hours", False):
        return df

    latitude = config["location"]["latitude"]
    longitude = config["location"]["longitude"]
    timezone = config["location"]["timezone"]

    # Cache daylight hours per unique date
    unique_dates = df.index.date
    daylight_cache: dict[date, float] = {}

    daylight_values = []
    for d in unique_dates:
        if d not in daylight_cache:
            daylight_cache[d] = _compute_daylight_hours(d, latitude, longitude, timezone)
        daylight_values.append(daylight_cache[d])

    df["daylight_hours"] = daylight_values
    return df


def _add_weather_features(
    df: pd.DataFrame,
    weather_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Merge weather forecast columns into feature DataFrame by timestamp.

    During training, weather_df is None and observed outdoor_temperature
    from InfluxDB is used as a proxy for forecast temperature.

    During prediction, weather_df contains actual forecast data with
    columns: temperature, cloud_coverage, wind_speed, precipitation.
    """
    if weather_df is not None:
        # Prediction mode: merge forecast data by nearest timestamp
        for col in ["temperature", "cloud_coverage", "wind_speed", "precipitation"]:
            if col in weather_df.columns:
                # Align by finding nearest timestamp within 15 min
                merged = pd.merge_asof(
                    df[[]]
                    .reset_index()
                    .rename(columns={df.index.name or "index": "timestamp"}),
                    weather_df[[col]]
                    .reset_index()
                    .rename(columns={weather_df.index.name or "index": "timestamp"}),
                    on="timestamp",
                    direction="nearest",
                    tolerance=pd.Timedelta(minutes=30),
                )
                df[col] = merged[col].values

        _LOGGER.info(
            "Added weather forecast features: %s",
            [
                c
                for c in [
                    "temperature",
                    "cloud_coverage",
                    "wind_speed",
                    "precipitation",
                ]
                if c in df.columns
            ],
        )
    else:
        # Training mode: use observed outdoor_temperature as proxy for forecast
        if "outdoor_temperature" in df.columns:
            df["temperature"] = df["outdoor_temperature"]
            _LOGGER.info(
                "Using observed outdoor_temperature as training proxy for forecast"
            )

    return df


def _add_history_context_features(
    df: pd.DataFrame,
    history_context: dict | None,
) -> pd.DataFrame:
    """Add historical consumption context features.

    These features represent "what happened recently" and are computed
    once from InfluxDB before prediction (not iteratively).

    Features added:
    - yesterday_same_hour: consumption at same quarter yesterday
    - yesterday_total: total kWh yesterday (scalar, same for all rows)
    - week_avg_same_hour: average consumption at same quarter over past week
    - recent_24h_mean: mean kWh/15min over last 24h (scalar, same for all rows)
    """
    if history_context is None:
        return df

    yesterday_profile = history_context["yesterday_profile"]
    week_avg_profile = history_context["week_avg_profile"]

    # Map each row to its quarter-of-day index (0-95)
    quarter_indices = df.index.hour * 4 + df.index.minute // 15

    # yesterday_same_hour: what was consumption at this time yesterday
    df["yesterday_same_hour"] = [
        yesterday_profile[min(qi, len(yesterday_profile) - 1)] for qi in quarter_indices
    ]

    # yesterday_total: scalar context
    df["yesterday_total"] = history_context["yesterday_total"]

    # week_avg_same_hour: average at this time over the past week
    df["week_avg_same_hour"] = [
        week_avg_profile[min(qi, len(week_avg_profile) - 1)] for qi in quarter_indices
    ]

    # recent_24h_mean: scalar context
    df["recent_24h_mean"] = history_context["recent_24h_mean"]

    _LOGGER.info(
        "Added history context features: yesterday_total=%.2f kWh, "
        "recent_24h_mean=%.4f kWh/15min",
        history_context["yesterday_total"],
        history_context["recent_24h_mean"],
    )

    return df


def engineer_features(
    raw_df: pd.DataFrame,
    config: dict,
    convert_target_to_kwh: bool = True,
    weather_df: pd.DataFrame | None = None,
    history_context: dict | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Create feature matrix from raw sensor DataFrame.

    Takes a wide-format DataFrame (from data_fetcher) with columns like
    'target', 'outdoor_temperature' and adds all derived features
    specified in config.

    Args:
        raw_df: Wide-format DataFrame indexed by quarter-hour timestamps.
                Must contain a 'target' column with consumption values.
        config: Resolved ML config dict.
        convert_target_to_kwh: If True, convert target from Watts to kWh/15min.
        weather_df: Optional weather forecast DataFrame for prediction mode.
                    None during training (uses observed temperature as proxy).
        history_context: Optional dict from fetch_history_context().
                         None during training (computed per-day in trainer).

    Returns:
        Tuple of (feature_df, feature_columns) where:
        - feature_df has both features and 'target' column
        - feature_columns lists only the feature column names (not target)
    """
    df = raw_df.copy()

    # Convert target from W to kWh per 15-min period if needed
    if convert_target_to_kwh and config["target"].get("unit") == "W":
        df["target"] = df["target"] * WATTS_TO_KWH_15MIN

    # Add temporal features
    df = _add_time_features(df, config)

    # Add daylight hours
    df = _add_daylight_feature(df, config)

    # Add weather features (forecast in prediction, observed proxy in training)
    df = _add_weather_features(df, weather_df)

    # Add history context features
    df = _add_history_context_features(df, history_context)

    # Drop raw sensor columns that shouldn't be features
    columns_to_drop = ["outdoor_temperature"]
    for col in columns_to_drop:
        if col in df.columns and col != "temperature":
            df = df.drop(columns=[col])

    # Identify feature columns (everything except 'target')
    feature_columns = [col for col in df.columns if col != "target"]

    # Drop rows where any feature is NaN
    rows_before = len(df)
    df = df.dropna(subset=feature_columns)
    rows_dropped = rows_before - len(df)
    if rows_dropped > 0:
        _LOGGER.info(
            "Dropped %d rows with incomplete features",
            rows_dropped,
        )

    _LOGGER.info(
        "Engineered %d features from %d rows: %s",
        len(feature_columns),
        len(df),
        feature_columns,
    )

    return df, feature_columns
