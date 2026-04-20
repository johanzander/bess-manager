"""Model training and evaluation for ML energy consumption prediction.

Orchestrates the full training pipeline: fetch data, engineer features,
train XGBoost model, evaluate with baseline comparisons, and persist to disk.
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from ml.data_fetcher import PERIODS_PER_DAY, fetch_training_data
from ml.feature_engineer import WATTS_TO_KWH_15MIN, engineer_features

_LOGGER = logging.getLogger(__name__)


def _temporal_train_test_split(
    df: pd.DataFrame,
    feature_columns: list[str],
    test_fraction: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split data by time: last test_fraction of rows become test set.

    This avoids data leakage from future values that random splitting would cause.

    Returns:
        (X_train, X_test, y_train, y_test) as numpy arrays.
    """
    split_idx = int(len(df) * (1 - test_fraction))

    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    X_train = train_df[feature_columns].values
    X_test = test_df[feature_columns].values
    y_train = train_df["target"].values
    y_test = test_df["target"].values

    _LOGGER.info(
        "Temporal split: %d train rows, %d test rows (%.0f%% test)",
        len(train_df),
        len(test_df),
        test_fraction * 100,
    )

    return X_train, X_test, y_train, y_test


def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Compute regression metrics for model evaluation."""
    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = r2_score(y_true, y_pred)

    # MAPE - avoid division by zero
    nonzero_mask = y_true != 0
    if nonzero_mask.any():
        mape = float(
            np.mean(
                np.abs(
                    (y_true[nonzero_mask] - y_pred[nonzero_mask]) / y_true[nonzero_mask]
                )
            )
            * 100
        )
    else:
        mape = float("inf")

    return {
        "mae_kwh": round(mae, 4),
        "rmse_kwh": round(rmse, 4),
        "r_squared": round(r2, 4),
        "mape_percent": round(mape, 2),
    }


def _get_feature_importance(
    model: XGBRegressor,
    feature_columns: list[str],
) -> list[tuple[str, float]]:
    """Extract and sort feature importance from trained model."""
    importances = model.feature_importances_
    feature_imp = list(zip(feature_columns, importances, strict=True))
    feature_imp.sort(key=lambda x: x[1], reverse=True)
    return feature_imp


def _compute_per_day_history_context(
    raw_df: pd.DataFrame,
    target_date: date,
    config: dict,
) -> dict:
    """Compute history context for a specific day from training data.

    During training, we compute history context relative to each day
    in the training set, using earlier data as the "history".

    Args:
        raw_df: Full training DataFrame with 'target' column (in raw units).
        target_date: The day we need context for.
        config: ML config dict.

    Returns:
        History context dict matching fetch_history_context() format.
    """
    # Convert target to kWh if needed
    target_col = raw_df["target"]
    if config["target"].get("unit") == "W":
        target_col = target_col * WATTS_TO_KWH_15MIN

    # Yesterday's profile
    yesterday = target_date - timedelta(days=1)
    yesterday_mask = target_col.index.date == yesterday
    yesterday_data = target_col[yesterday_mask]

    yesterday_profile = [0.0] * PERIODS_PER_DAY
    if not yesterday_data.empty:
        for i, val in enumerate(yesterday_data.values[:PERIODS_PER_DAY]):
            yesterday_profile[i] = float(val)

    yesterday_total = sum(yesterday_profile)

    # Weekly average profile
    week_profiles: list[list[float]] = []
    for days_back in range(1, 8):
        day = target_date - timedelta(days=days_back)
        day_mask = target_col.index.date == day
        day_data = target_col[day_mask]
        if len(day_data) >= PERIODS_PER_DAY // 2:
            profile = [0.0] * PERIODS_PER_DAY
            for i, val in enumerate(day_data.values[:PERIODS_PER_DAY]):
                profile[i] = float(val)
            week_profiles.append(profile)

    if week_profiles:
        week_avg_profile = [
            sum(p[i] for p in week_profiles) / len(week_profiles)
            for i in range(PERIODS_PER_DAY)
        ]
    else:
        week_avg_profile = yesterday_profile.copy()

    # Recent 24h mean (from data up to start of target_date)
    cutoff = pd.Timestamp(target_date, tz=target_col.index.tz)
    recent = target_col[target_col.index < cutoff].tail(PERIODS_PER_DAY)
    recent_24h_mean = float(recent.mean()) if not recent.empty else 0.0

    return {
        "yesterday_profile": yesterday_profile,
        "yesterday_total": yesterday_total,
        "week_avg_profile": week_avg_profile,
        "recent_24h_mean": recent_24h_mean,
    }


def _add_history_context_to_training_data(
    raw_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Add per-day history context columns to training data.

    For each unique day in the training data, computes history context
    from earlier days and adds the context columns.

    Returns:
        DataFrame with history context columns added.
    """
    target_col = raw_df["target"]
    if config["target"].get("unit") == "W":
        target_col = target_col * WATTS_TO_KWH_15MIN

    unique_dates = sorted(set(raw_df.index.date))

    # Pre-compute context for each day
    context_cache: dict[date, dict] = {}
    for d in unique_dates:
        context_cache[d] = _compute_per_day_history_context(raw_df, d, config)

    # Build columns
    yesterday_same_hour = []
    yesterday_total_vals = []
    week_avg_same_hour = []
    recent_24h_mean_vals = []

    for ts in raw_df.index:
        d = ts.date()
        qi = ts.hour * 4 + ts.minute // 15
        ctx = context_cache[d]

        yesterday_same_hour.append(
            ctx["yesterday_profile"][min(qi, PERIODS_PER_DAY - 1)]
        )
        yesterday_total_vals.append(ctx["yesterday_total"])
        week_avg_same_hour.append(ctx["week_avg_profile"][min(qi, PERIODS_PER_DAY - 1)])
        recent_24h_mean_vals.append(ctx["recent_24h_mean"])

    result = raw_df.copy()
    result["yesterday_same_hour"] = yesterday_same_hour
    result["yesterday_total"] = yesterday_total_vals
    result["week_avg_same_hour"] = week_avg_same_hour
    result["recent_24h_mean"] = recent_24h_mean_vals

    _LOGGER.info(
        "Added history context for %d unique days in training data",
        len(unique_dates),
    )

    return result


def _compute_baseline_metrics(
    feature_df: pd.DataFrame,
    test_fraction: float,
) -> dict[str, dict[str, float]]:
    """Compute naive baseline metrics on the test set.

    Baselines:
    - same_as_yesterday: predict today = yesterday's same quarter
    - hourly_mean: predict each quarter = historical mean for that quarter-of-day
    - flat_estimate: predict every quarter = overall mean of training data

    Returns:
        Dict mapping baseline name to metrics dict.
    """
    split_idx = int(len(feature_df) * (1 - test_fraction))
    train_df = feature_df.iloc[:split_idx]
    test_df = feature_df.iloc[split_idx:]

    y_test = test_df["target"].values
    baselines: dict[str, dict[str, float]] = {}

    # Baseline 1: Same as yesterday
    if "yesterday_same_hour" in test_df.columns:
        y_yesterday = test_df["yesterday_same_hour"].values
        baselines["same_as_yesterday"] = _compute_metrics(y_test, y_yesterday)

    # Baseline 2: Hourly mean (average by quarter-of-day from training set)
    train_quarters = train_df.index.hour * 4 + train_df.index.minute // 15
    quarter_means = train_df.assign(qi=train_quarters).groupby("qi")["target"].mean()

    test_quarters = test_df.index.hour * 4 + test_df.index.minute // 15
    y_hourly_mean = np.array(
        [quarter_means.get(qi, train_df["target"].mean()) for qi in test_quarters]
    )
    baselines["hourly_mean"] = _compute_metrics(y_test, y_hourly_mean)

    # Baseline 3: Flat estimate (overall training mean)
    overall_mean = train_df["target"].mean()
    y_flat = np.full_like(y_test, overall_mean)
    baselines["flat_estimate"] = _compute_metrics(y_test, y_flat)

    return baselines


def train_model(config: dict, target_date: date | None = None) -> dict:
    """Full training pipeline: fetch, engineer, train, evaluate, save.

    Args:
        config: Resolved ML config dict.
        target_date: End date for training window. Defaults to yesterday.

    Returns:
        Dict with keys: metrics, baselines, feature_importance, model_path,
        train_size, test_size.

    Raises:
        RuntimeError: If data fetching or training fails.
    """
    # Step 1: Fetch historical data
    _LOGGER.info("Step 1/5: Fetching training data from InfluxDB...")
    raw_df = fetch_training_data(config, target_date=target_date)

    # Step 2: Add per-day history context to training data
    _LOGGER.info("Step 2/5: Computing per-day history context...")
    raw_with_context = _add_history_context_to_training_data(raw_df, config)

    # Step 3: Engineer features (no weather_df for training - uses observed temp)
    _LOGGER.info("Step 3/5: Engineering features...")
    feature_df, feature_columns = engineer_features(
        raw_with_context, config, history_context=None
    )

    min_samples = 20
    if len(feature_df) < min_samples:
        raise RuntimeError(
            f"Insufficient training data: {len(feature_df)} samples "
            f"(minimum {min_samples}). Need more days of InfluxDB history."
        )

    # Step 4: Train/test split and model training
    _LOGGER.info("Step 4/5: Training XGBoost model...")
    test_fraction = config["training"]["test_split"]
    X_train, X_test, y_train, y_test = _temporal_train_test_split(
        feature_df, feature_columns, test_fraction
    )

    model_params = config["training"]["model_params"]
    model = XGBRegressor(
        n_estimators=model_params["n_estimators"],
        max_depth=model_params["max_depth"],
        learning_rate=model_params["learning_rate"],
        min_child_weight=model_params["min_child_weight"],
        random_state=42,
        objective="reg:squarederror",
    )

    model.fit(
        X_train,
        y_train,
        verbose=False,
    )

    # Step 5: Evaluate, compute baselines, and save
    _LOGGER.info("Step 5/5: Evaluating model and computing baselines...")
    y_pred = model.predict(X_test)
    metrics = _compute_metrics(y_test, y_pred)
    feature_importance = _get_feature_importance(model, feature_columns)
    baselines = _compute_baseline_metrics(feature_df, test_fraction)

    # Save model
    model_path = config["model_path"]
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    model.save_model(model_path)

    # Save feature column names alongside model for prediction
    feature_meta_path = str(Path(model_path).with_suffix(".features.txt"))
    with open(feature_meta_path, "w") as f:
        f.write("\n".join(feature_columns))

    _LOGGER.info("Model saved to %s", model_path)
    _LOGGER.info("Feature metadata saved to %s", feature_meta_path)

    # Save training report sidecar for the web UI
    report_data = {
        "trained_at": datetime.now().isoformat(),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "metrics": metrics,
        "baselines": baselines,
        "feature_importance": [
            {"name": name, "importance": round(float(imp), 6)}
            for name, imp in feature_importance
        ],
    }
    report_path = str(Path(model_path).with_suffix(".report.json"))
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
    _LOGGER.info("Training report saved to %s", report_path)

    return {
        "metrics": metrics,
        "baselines": baselines,
        "feature_importance": feature_importance,
        "model_path": model_path,
        "train_size": len(X_train),
        "test_size": len(X_test),
    }


def evaluate_model(config: dict, target_date: date | None = None) -> dict:
    """Load a trained model and evaluate on recent test data.

    Uses the same training data but only evaluates the test split,
    useful for checking model performance without retraining.

    Args:
        config: Resolved ML config dict.
        target_date: End date for evaluation window. Defaults to yesterday.

    Returns:
        Dict with metrics and per-period analysis.

    Raises:
        FileNotFoundError: If no trained model exists.
        RuntimeError: If data fetching fails.
    """
    model_path = config["model_path"]
    if not Path(model_path).exists():
        raise FileNotFoundError(
            f"No trained model found at {model_path}. Run 'train' first."
        )

    # Load model
    model = XGBRegressor()
    model.load_model(model_path)

    # Fetch and prepare test data
    raw_df = fetch_training_data(config, target_date=target_date)
    raw_with_context = _add_history_context_to_training_data(raw_df, config)
    feature_df, feature_columns = engineer_features(
        raw_with_context, config, history_context=None
    )

    test_fraction = config["training"]["test_split"]
    _, X_test, _, y_test = _temporal_train_test_split(
        feature_df, feature_columns, test_fraction
    )

    y_pred = model.predict(X_test)
    metrics = _compute_metrics(y_test, y_pred)

    # Per-hour analysis: average error by hour of day
    split_idx = int(len(feature_df) * (1 - test_fraction))
    test_df = feature_df.iloc[split_idx:].copy()
    test_df["predicted"] = y_pred
    test_df["error"] = test_df["predicted"] - test_df["target"]
    test_df["abs_error"] = test_df["error"].abs()
    test_df["hour"] = test_df.index.hour

    hourly_errors = (
        test_df.groupby("hour")
        .agg(
            mean_error=pd.NamedAgg(column="error", aggfunc="mean"),
            mae=pd.NamedAgg(column="abs_error", aggfunc="mean"),
            count=pd.NamedAgg(column="error", aggfunc="count"),
        )
        .round(4)
    )

    return {
        "metrics": metrics,
        "hourly_errors": hourly_errors.to_dict("index"),
        "test_size": len(X_test),
    }


def compute_baselines(config: dict, target_date: date | None = None) -> dict:
    """Compute baseline metrics on the test set without training a model.

    Fetches data, engineers features (to get history context columns),
    then computes naive baseline metrics.

    Args:
        config: Resolved ML config dict.
        target_date: End date for data window. Defaults to yesterday.

    Returns:
        Dict with baseline metrics for each heuristic.

    Raises:
        RuntimeError: If data fetching fails.
    """
    raw_df = fetch_training_data(config, target_date=target_date)
    raw_with_context = _add_history_context_to_training_data(raw_df, config)
    feature_df, _ = engineer_features(raw_with_context, config, history_context=None)

    test_fraction = config["training"]["test_split"]
    baselines = _compute_baseline_metrics(feature_df, test_fraction)

    return {
        "baselines": baselines,
        "total_samples": len(feature_df),
        "test_samples": int(len(feature_df) * test_fraction),
    }
