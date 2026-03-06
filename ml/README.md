# ML Energy Consumption Predictor

Standalone CLI tool for training and running ML-based energy consumption
predictions. Uses XGBoost gradient boosting on historical InfluxDB sensor
data to produce 96 quarter-hourly consumption forecasts.

## Prerequisites

On macOS, XGBoost requires OpenMP:

```bash
brew install libomp
```

## Setup

Always use the dedicated venv for the ML module:

```bash
# Create venv (one time)
python3 -m venv ml/.venv

# Install dependencies
ml/.venv/bin/pip install -r backend/requirements.txt

# Install dev tools
ml/.venv/bin/pip install black ruff
```

## Usage

All commands must be run from the project root using the venv Python:

```bash
# Train a model
ml/.venv/bin/python -m ml train

# Generate 24h consumption prediction
ml/.venv/bin/python -m ml predict

# Evaluate model performance
ml/.venv/bin/python -m ml evaluate

# Show naive baseline metrics (no ML)
ml/.venv/bin/python -m ml baseline

# Retrain + predict + generate timestamped HTML chart
ml/.venv/bin/python -m ml report

# Fetch and display raw sensor data (debugging)
ml/.venv/bin/python -m ml fetch-data

# Verbose mode for any command
ml/.venv/bin/python -m ml train -v
```

The `report` command runs the full pipeline (train, predict, fetch weather/history)
and produces `ml/prediction_chart-YYYY-MM-DD.html` — a self-contained dark-theme
Chart.js dashboard. Run it periodically to track model evolution as more data
accumulates.

## Configuration

Edit `ml_config.yaml` in the project root. Environment variables
(`${HA_DB_URL}`, etc.) are resolved from `.env` or the shell environment.

## Quality Checks

```bash
ml/.venv/bin/black ml/
ml/.venv/bin/ruff check --fix ml/
```

## Integration with BESS Manager

The ML predictor integrates with the main BESS optimization system via the
`consumption_strategy` setting. To use ML predictions for battery optimization:

```yaml
home:
  consumption_strategy: "ml_prediction"
```

When this strategy is active, the battery system manager calls
`ml.predictor.predict_next_24h()` to generate the consumption forecast
used by the optimizer. The `influxdb_profile` strategy also reuses the
`ml.data_fetcher.fetch_history_context()` function to produce a 7-day
average profile without requiring a trained model.

See the [Installation Guide](../INSTALLATION.md) for all available
consumption strategies.

## Output Format

Predictions are 96 float values (kWh per 15-minute period), matching
the format expected by `battery_system_manager.optimize_battery_schedule()`.
