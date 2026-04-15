"""CLI entry point for ML energy consumption predictor.

Usage:
    python -m ml train          # Fetch data, train model, show metrics + baselines
    python -m ml predict        # Generate 24h prediction, print table
    python -m ml evaluate       # Show model performance on test data
    python -m ml baseline       # Show naive baseline metrics (no ML)
    python -m ml fetch-data     # Just fetch and display raw data (debugging)
    python -m ml report         # Retrain + predict + generate timestamped HTML chart
"""

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ml.config import load_config


def _setup_logging(verbose: bool) -> None:
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _cmd_train(config: dict, target_date: date | None = None) -> None:
    """Train model and display results."""
    from ml.trainer import train_model

    result = train_model(config, target_date=target_date)

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"  Train samples: {result['train_size']}")
    print(f"  Test samples:  {result['test_size']}")
    print(f"  Model saved:   {result['model_path']}")

    print("\nML Model Metrics:")
    for name, value in result["metrics"].items():
        print(f"  {name}: {value}")

    print("\nBaseline Comparison:")
    print(f"  {'Method':25s} {'MAE':>10s} {'RMSE':>10s} {'R²':>10s}")
    print("  " + "-" * 55)

    # ML model row
    m = result["metrics"]
    print(
        f"  {'XGBoost (ML model)':25s} {m['mae_kwh']:>10.4f} "
        f"{m['rmse_kwh']:>10.4f} {m['r_squared']:>10.4f}"
    )

    # Baseline rows
    for baseline_name, metrics in result["baselines"].items():
        label = baseline_name.replace("_", " ").title()
        print(
            f"  {label:25s} {metrics['mae_kwh']:>10.4f} "
            f"{metrics['rmse_kwh']:>10.4f} {metrics['r_squared']:>10.4f}"
        )

    # Improvement summary
    if "same_as_yesterday" in result["baselines"]:
        baseline_mae = result["baselines"]["same_as_yesterday"]["mae_kwh"]
        ml_mae = result["metrics"]["mae_kwh"]
        if baseline_mae > 0:
            improvement = (1 - ml_mae / baseline_mae) * 100
            print(
                f"\n  ML vs Same-as-Yesterday: "
                f"{improvement:+.1f}% MAE {'improvement' if improvement > 0 else 'worse'}"
            )

    print("\nFeature Importance (top 10):")
    for feature_name, importance in result["feature_importance"][:10]:
        bar = "#" * int(importance * 50)
        print(f"  {feature_name:30s} {importance:.4f} {bar}")


def _cmd_predict(config: dict) -> None:
    """Generate and display predictions for tomorrow."""
    from datetime import timedelta

    from ml.predictor import predict_with_timestamps

    target_date = date.today() + timedelta(days=1)
    predictions = predict_with_timestamps(config, target_date)

    print("\n" + "=" * 60)
    print("24-HOUR CONSUMPTION PREDICTION")
    print("=" * 60)
    print(f"{'Time':>8s}  {'kWh/15min':>10s}  {'kWh/hour':>10s}  {'Visual':s}")
    print("-" * 60)

    hourly_kwh = 0.0
    total_kwh = 0.0

    for i, (ts, kwh) in enumerate(predictions):
        hourly_kwh += kwh
        total_kwh += kwh

        # Print hourly summary at end of each hour
        if (i + 1) % 4 == 0:
            bar = "#" * int(hourly_kwh * 10)
            print(
                f"  {ts.strftime('%H:%M'):>6s}  {kwh:>10.3f}  {hourly_kwh:>10.3f}  {bar}"
            )
            hourly_kwh = 0.0
        else:
            print(f"  {ts.strftime('%H:%M'):>6s}  {kwh:>10.3f}")

    print("-" * 60)
    print(f"  Total predicted consumption: {total_kwh:.2f} kWh")
    print(f"  Average hourly: {total_kwh / 24:.2f} kWh/h")
    print(f"  Average per 15min: {total_kwh / 96:.3f} kWh")


def _cmd_evaluate(config: dict, target_date: date | None = None) -> None:
    """Evaluate model and display detailed metrics."""
    from ml.trainer import evaluate_model

    result = evaluate_model(config, target_date=target_date)

    print("\n" + "=" * 60)
    print("MODEL EVALUATION")
    print("=" * 60)
    print(f"  Test samples: {result['test_size']}")

    print("\nOverall Metrics:")
    for name, value in result["metrics"].items():
        print(f"  {name}: {value}")

    print("\nHourly Error Analysis:")
    print(f"  {'Hour':>4s}  {'Mean Error':>12s}  {'MAE':>8s}  {'Samples':>8s}")
    print("  " + "-" * 40)
    for hour, data in sorted(result["hourly_errors"].items()):
        print(
            f"  {hour:>4d}  {data['mean_error']:>12.4f}  "
            f"{data['mae']:>8.4f}  {data['count']:>8d}"
        )


def _cmd_baseline(config: dict, target_date: date | None = None) -> None:
    """Compute and display naive baseline metrics."""
    from ml.trainer import compute_baselines

    result = compute_baselines(config, target_date=target_date)

    print("\n" + "=" * 60)
    print("BASELINE METRICS")
    print("=" * 60)
    print(f"  Total samples: {result['total_samples']}")
    print(f"  Test samples:  {result['test_samples']}")

    print(f"\n  {'Method':25s} {'MAE':>10s} {'RMSE':>10s} {'R²':>10s} {'MAPE%':>10s}")
    print("  " + "-" * 65)

    for baseline_name, metrics in result["baselines"].items():
        label = baseline_name.replace("_", " ").title()
        print(
            f"  {label:25s} {metrics['mae_kwh']:>10.4f} "
            f"{metrics['rmse_kwh']:>10.4f} {metrics['r_squared']:>10.4f} "
            f"{metrics['mape_percent']:>10.2f}"
        )

    print("\nInterpretation:")
    print("  These baselines represent the performance floor.")
    print("  An ML model should beat all of these to justify its complexity.")
    print("  'Same As Yesterday' is the strongest naive baseline for")
    print("  habitual consumption patterns (e.g., work-from-home).")


def _cmd_fetch_data(config: dict, target_date: date | None = None) -> None:
    """Fetch and display raw sensor data for debugging."""
    from ml.data_fetcher import fetch_training_data

    df = fetch_training_data(config, target_date=target_date)

    print("\n" + "=" * 60)
    print("RAW SENSOR DATA")
    print("=" * 60)
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")

    print("\nColumn Statistics:")
    print(df.describe().round(2).to_string())

    print("\nFirst 10 rows:")
    print(df.head(10).to_string())

    print("\nLast 10 rows:")
    print(df.tail(10).to_string())

    # Check for gaps
    time_diffs = df.index.to_series().diff()
    expected_diff = "15min"
    gaps = time_diffs[time_diffs > expected_diff]
    if not gaps.empty:
        print(f"\nData gaps found ({len(gaps)} gaps > 15min):")
        for ts, gap in gaps.head(10).items():
            print(f"  {ts}: {gap}")


def _generate_chart_html(
    train_result: dict,
    predictions: list[tuple[datetime, float]],
    weather_df: pd.DataFrame,
    history_context: dict,
) -> str:
    """Generate self-contained HTML chart from pipeline results."""
    # Quarter-hourly prediction data
    quarter_data = [
        {"time": ts.strftime("%H:%M"), "kwh": round(kwh, 4)} for ts, kwh in predictions
    ]

    # Yesterday's profile mapped to 15-min slots starting at 00:00
    yesterday_profile = history_context["yesterday_profile"]
    yesterday_data = [
        {"time": f"{i // 4:02d}:{(i % 4) * 15:02d}", "kwh": round(v, 4)}
        for i, v in enumerate(yesterday_profile)
    ]

    # Hourly aggregation from predictions
    hourly_data = []
    for i in range(0, len(predictions), 4):
        chunk = predictions[i : i + 4]
        hour_kwh = sum(kwh for _, kwh in chunk)
        label = chunk[0][0].strftime("%H:%M")
        hourly_data.append({"hour": label, "kwh": round(hour_kwh, 4)})

    # Weather data from forecast DataFrame
    weather_data = [
        {"time": ts.strftime("%H:%M"), "temp": round(row["temperature"], 1)}
        for ts, row in weather_df.iterrows()
    ]

    # Feature importance (cast to Python float for JSON serialization)
    feature_importance = [
        [name, round(float(imp), 4)] for name, imp in train_result["feature_importance"]
    ]

    # Summary card values
    total_kwh = sum(kwh for _, kwh in predictions)
    yesterday_total = history_context["yesterday_total"]

    hourly_totals = [d["kwh"] for d in hourly_data]
    peak_idx = hourly_totals.index(max(hourly_totals))
    low_idx = hourly_totals.index(min(hourly_totals))
    peak_hour = hourly_data[peak_idx]["hour"]
    peak_kwh = hourly_totals[peak_idx]
    low_hour = hourly_data[low_idx]["hour"]
    low_kwh = hourly_totals[low_idx]

    temps = [d["temp"] for d in weather_data]
    temp_min = min(temps) if temps else 0.0
    temp_max = max(temps) if temps else 0.0

    # Prediction time range
    pred_start = predictions[0][0].strftime("%Y-%m-%d %H:%M")
    pred_end = predictions[-1][0].strftime("%Y-%m-%d %H:%M")

    # Training data warning
    train_size = train_result["train_size"]
    configured_days = 30
    actual_days = train_size // 96
    show_warning = actual_days < configured_days

    # Baseline table rows
    metrics = train_result["metrics"]
    baselines = train_result["baselines"]

    baseline_rows_html = ""
    baseline_rows_html += (
        f'          <tr class="highlight"><td>XGBoost (ML)</td>'
        f'<td class="val">{metrics["mae_kwh"]:.4f}</td>'
        f'<td class="val">{metrics["rmse_kwh"]:.4f}</td>'
        f'<td class="val">{metrics["r_squared"]:.3f}</td>'
        f'<td class="val">{metrics["mape_percent"]:.1f}</td></tr>\n'
    )
    for name, bm in baselines.items():
        label = name.replace("_", " ").title()
        baseline_rows_html += (
            f"          <tr><td>{label}</td>"
            f'<td class="val">{bm["mae_kwh"]:.4f}</td>'
            f'<td class="val">{bm["rmse_kwh"]:.4f}</td>'
            f'<td class="val">{bm["r_squared"]:.3f}</td>'
            f'<td class="val">{bm["mape_percent"]:.1f}</td></tr>\n'
        )

    # Warning HTML
    warning_html = ""
    if show_warning:
        warning_html = f"""
  <div class="warning">
    <div class="warning-title">Limited Training Data</div>
    <div class="warning-text">
      Model trained on only <strong>{actual_days} days</strong> of data (~{train_size} samples) instead of the configured {configured_days} days.
      Metrics will improve significantly with more history.
    </div>
  </div>
"""

    # Yesterday start index — align yesterday data to prediction timeline
    pred_start_quarter = predictions[0][0].hour * 4 + predictions[0][0].minute // 15

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ML Energy Prediction &mdash; BESS Manager</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e1e4e8; padding: 24px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 4px; }}
  .subtitle {{ color: #8b949e; font-size: 0.9rem; margin-bottom: 24px; }}
  .subtitle span {{ color: #f0883e; }}
  h2 {{ font-size: 1.1rem; font-weight: 600; margin: 0 0 16px; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .card-label {{ color: #8b949e; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
  .card-value {{ font-size: 1.6rem; font-weight: 700; }}
  .card-sub {{ color: #8b949e; font-size: 0.75rem; margin-top: 4px; }}
  .card-value.total {{ color: #58a6ff; }}
  .card-value.peak {{ color: #f0883e; }}
  .card-value.low {{ color: #3fb950; }}
  .card-value.temp {{ color: #bc8cff; }}
  .card-unit {{ color: #8b949e; font-size: 0.8rem; font-weight: 400; }}
  .chart-panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
  .chart-title {{ font-size: 0.95rem; font-weight: 600; margin-bottom: 16px; }}
  .chart-wrap {{ position: relative; height: 280px; }}
  .toggle-row {{ display: flex; gap: 8px; margin-bottom: 24px; }}
  .toggle-btn {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 8px 16px; color: #8b949e; cursor: pointer; font-size: 0.85rem; transition: all 0.15s; }}
  .toggle-btn.active {{ background: #1f6feb22; border-color: #58a6ff; color: #58a6ff; }}
  .toggle-btn:hover {{ border-color: #58a6ff88; }}
  .section {{ margin-top: 32px; margin-bottom: 16px; }}
  .section-label {{ color: #8b949e; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .metrics-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  .metrics-table th {{ text-align: left; color: #8b949e; font-weight: 500; padding: 8px 12px; border-bottom: 1px solid #30363d; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .metrics-table td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; }}
  .metrics-table tr.highlight td {{ color: #58a6ff; font-weight: 600; }}
  .metrics-table td.val {{ font-family: 'SF Mono', 'Fira Code', monospace; text-align: right; font-size: 0.8rem; }}
  .feat-row {{ display: flex; align-items: center; margin-bottom: 6px; }}
  .feat-name {{ width: 170px; font-size: 0.8rem; color: #8b949e; text-align: right; padding-right: 12px; flex-shrink: 0; }}
  .feat-bar-wrap {{ flex: 1; height: 18px; background: #21262d; border-radius: 4px; overflow: hidden; }}
  .feat-bar {{ height: 100%; border-radius: 4px; transition: width 0.4s; }}
  .feat-pct {{ width: 50px; font-size: 0.75rem; color: #8b949e; text-align: right; padding-left: 8px; font-family: monospace; }}
  .warning {{ background: #f0883e15; border: 1px solid #f0883e44; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
  .warning-title {{ color: #f0883e; font-weight: 600; font-size: 0.9rem; margin-bottom: 6px; }}
  .warning-text {{ color: #8b949e; font-size: 0.85rem; line-height: 1.5; }}
  @media (max-width: 768px) {{
    .cards {{ grid-template-columns: repeat(2, 1fr); }}
    .cols {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
  <h1>ML Energy Consumption Prediction</h1>
  <p class="subtitle">Direct prediction with weather forecast &mdash; <span>{pred_start} to {pred_end}</span></p>
{warning_html}
  <div class="cards">
    <div class="card">
      <div class="card-label">Predicted 24h</div>
      <div class="card-value total">{total_kwh:.2f} <span class="card-unit">kWh</span></div>
      <div class="card-sub">Yesterday: {yesterday_total:.2f} kWh</div>
    </div>
    <div class="card">
      <div class="card-label">Peak Hour</div>
      <div class="card-value peak">{peak_kwh:.2f} <span class="card-unit">kWh/h</span></div>
      <div class="card-sub">{peak_hour}</div>
    </div>
    <div class="card">
      <div class="card-label">Lowest Hour</div>
      <div class="card-value low">{low_kwh:.2f} <span class="card-unit">kWh/h</span></div>
      <div class="card-sub">{low_hour}</div>
    </div>
    <div class="card">
      <div class="card-label">Temperature Range</div>
      <div class="card-value temp">{temp_min:.1f}&ndash;{temp_max:.1f} <span class="card-unit">&deg;C</span></div>
    </div>
  </div>

  <div class="toggle-row">
    <button class="toggle-btn active" data-view="quarter">15-min intervals</button>
    <button class="toggle-btn" data-view="hourly">Hourly totals</button>
  </div>

  <div class="chart-panel">
    <div class="chart-title">Predicted Consumption vs Yesterday</div>
    <div class="chart-wrap"><canvas id="mainChart"></canvas></div>
  </div>

  <div class="cols">
    <div class="chart-panel">
      <div class="chart-title">Hourly Breakdown</div>
      <div class="chart-wrap"><canvas id="barChart"></canvas></div>
    </div>
    <div class="chart-panel">
      <div class="chart-title">Temperature &amp; Consumption Correlation</div>
      <div class="chart-wrap"><canvas id="tempChart"></canvas></div>
    </div>
  </div>

  <div class="section">
    <div class="section-label">Model Analysis</div>
  </div>

  <div class="cols">
    <div class="chart-panel">
      <h2>Baseline Comparison</h2>
      <table class="metrics-table">
        <thead>
          <tr><th>Method</th><th class="val">MAE</th><th class="val">RMSE</th><th class="val">R&sup2;</th><th class="val">MAPE%</th></tr>
        </thead>
        <tbody>
{baseline_rows_html}        </tbody>
      </table>
    </div>

    <div class="chart-panel">
      <h2>Feature Importance</h2>
      <div id="feat-bars"></div>
    </div>
  </div>

  <div class="section">
    <div class="section-label">Methodology</div>
  </div>

  <div class="chart-panel">
    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; font-size: 0.85rem; color: #8b949e; line-height: 1.6;">
      <div>
        <div style="color: #e1e4e8; font-weight: 600; margin-bottom: 8px;">Direct Prediction</div>
        Single <code style="color:#58a6ff">model.predict(X)</code> call on a 96-row feature matrix.
        No iterative loop, no error compounding. Each row contains only
        features known ahead of time for that future period.
      </div>
      <div>
        <div style="color: #e1e4e8; font-weight: 600; margin-bottom: 8px;">Weather-Driven</div>
        48-hour forecast from Home Assistant (temperature, cloud cover,
        wind, precipitation) interpolated to 15-min intervals.
      </div>
      <div>
        <div style="color: #e1e4e8; font-weight: 600; margin-bottom: 8px;">History Context</div>
        Yesterday's consumption profile, weekly averages, and recent 24h mean
        provide stable context without feeding predictions back as input.
        Computed once from InfluxDB before prediction.
      </div>
    </div>
  </div>
</div>

<script>
const quarterData = {json.dumps(quarter_data)};
const yesterdayData = {json.dumps(yesterday_data)};
const hourlyData = {json.dumps(hourly_data)};
const weatherData = {json.dumps(weather_data)};
const featureImportance = {json.dumps(feature_importance)};

const gridColor = '#21262d';
const tickColor = '#8b949e';
const blue = '#58a6ff';
const orange = '#f0883e';
const green = '#3fb950';
const purple = '#bc8cff';

function makeGradient(ctx, r, g, b, h) {{
  const grad = ctx.createLinearGradient(0, 0, 0, h || 280);
  grad.addColorStop(0, `rgba(${{r}},${{g}},${{b}},0.3)`);
  grad.addColorStop(1, `rgba(${{r}},${{g}},${{b}},0.02)`);
  return grad;
}}

// Reorder yesterday data to align with prediction start time
const yesterdayReordered = [];
const startIdx = {pred_start_quarter};
for (let i = 0; i < 96; i++) {{
  yesterdayReordered.push(yesterdayData[(startIdx + i) % 96]);
}}

// Main chart: prediction vs yesterday
const mainCtx = document.getElementById('mainChart').getContext('2d');
const mainChart = new Chart(mainCtx, {{
  type: 'line',
  data: {{
    labels: quarterData.map(d => d.time),
    datasets: [
      {{
        label: 'ML Prediction',
        data: quarterData.map(d => d.kwh),
        borderColor: blue,
        backgroundColor: makeGradient(mainCtx, 88, 166, 255),
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        pointHitRadius: 8,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: blue,
      }},
      {{
        label: 'Yesterday Actual',
        data: yesterdayReordered.map(d => d.kwh),
        borderColor: '#484f58',
        borderWidth: 1.5,
        borderDash: [4, 4],
        fill: false,
        tension: 0.3,
        pointRadius: 0,
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ labels: {{ color: tickColor, boxWidth: 12, padding: 16, font: {{ size: 11 }} }} }},
      tooltip: {{
        backgroundColor: '#1c2128', borderColor: '#30363d', borderWidth: 1,
        titleColor: '#e1e4e8', bodyColor: '#8b949e', padding: 10,
        callbacks: {{ label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y.toFixed(3)}} kWh` }}
      }}
    }},
    scales: {{
      x: {{
        grid: {{ color: gridColor }},
        ticks: {{ color: tickColor, maxTicksLimit: 24, callback: function(val) {{ const l = this.getLabelForValue(val); return l.endsWith(':00') ? l : ''; }} }}
      }},
      y: {{
        grid: {{ color: gridColor }},
        ticks: {{ color: tickColor, callback: v => v.toFixed(2) }},
        title: {{ display: true, text: 'kWh / 15min', color: tickColor }}
      }}
    }}
  }}
}});

// Bar chart
const barCtx = document.getElementById('barChart').getContext('2d');
function barColors(data) {{
  const max = Math.max(...data);
  return data.map(v => {{
    const r = v / max;
    if (r > 0.8) return orange;
    if (r > 0.5) return blue;
    return green;
  }});
}}
const hourlyKwh = hourlyData.map(d => d.kwh);
new Chart(barCtx, {{
  type: 'bar',
  data: {{
    labels: hourlyData.map(d => d.hour),
    datasets: [{{ label: 'kWh/hour', data: hourlyKwh, backgroundColor: barColors(hourlyKwh), borderRadius: 4, borderSkipped: false }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ backgroundColor: '#1c2128', borderColor: '#30363d', borderWidth: 1, titleColor: '#e1e4e8', bodyColor: '#8b949e', padding: 10, callbacks: {{ label: ctx => `${{ctx.parsed.y.toFixed(3)}} kWh` }} }}
    }},
    scales: {{
      x: {{ grid: {{ color: gridColor }}, ticks: {{ color: tickColor, maxTicksLimit: 12 }} }},
      y: {{ grid: {{ color: gridColor }}, ticks: {{ color: tickColor, callback: v => v.toFixed(1) }}, title: {{ display: true, text: 'kWh/hour', color: tickColor }} }}
    }}
  }}
}});

// Temperature + consumption dual axis chart
const tempCtx = document.getElementById('tempChart').getContext('2d');
new Chart(tempCtx, {{
  type: 'line',
  data: {{
    labels: quarterData.map(d => d.time),
    datasets: [
      {{
        label: 'Consumption',
        data: quarterData.map(d => d.kwh),
        borderColor: blue,
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        tension: 0.3,
        pointRadius: 0,
        yAxisID: 'y',
      }},
      {{
        label: 'Temperature',
        data: weatherData.map(d => d.temp),
        borderColor: orange,
        backgroundColor: makeGradient(tempCtx, 240, 136, 62),
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        yAxisID: 'y1',
      }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ labels: {{ color: tickColor, boxWidth: 12, padding: 16, font: {{ size: 11 }} }} }},
      tooltip: {{
        backgroundColor: '#1c2128', borderColor: '#30363d', borderWidth: 1, titleColor: '#e1e4e8', bodyColor: '#8b949e', padding: 10,
        callbacks: {{ label: ctx => ctx.dataset.label === 'Temperature' ? `${{ctx.parsed.y.toFixed(1)}} °C` : `${{ctx.parsed.y.toFixed(3)}} kWh` }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ color: gridColor }}, ticks: {{ color: tickColor, maxTicksLimit: 12, callback: function(val) {{ const l = this.getLabelForValue(val); return l.endsWith(':00') ? l : ''; }} }} }},
      y: {{ position: 'left', grid: {{ color: gridColor }}, ticks: {{ color: blue, callback: v => v.toFixed(2) }}, title: {{ display: true, text: 'kWh', color: blue }} }},
      y1: {{ position: 'right', grid: {{ drawOnChartArea: false }}, ticks: {{ color: orange, callback: v => v + '°' }}, title: {{ display: true, text: '°C', color: orange }} }}
    }}
  }}
}});

// Toggle quarter/hourly
document.querySelectorAll('.toggle-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const view = btn.dataset.view;
    if (view === 'hourly') {{
      mainChart.data.labels = hourlyData.map(d => d.hour);
      mainChart.data.datasets[0].data = hourlyKwh;
      mainChart.data.datasets[0].label = 'ML Prediction (hourly)';
      const yHourly = [];
      for (let i = 0; i < 96; i += 4) {{
        let s = 0;
        for (let j = 0; j < 4; j++) s += yesterdayReordered[i + j].kwh;
        yHourly.push(s);
      }}
      mainChart.data.datasets[1].data = yHourly;
      mainChart.options.scales.y.title.text = 'kWh / hour';
    }} else {{
      mainChart.data.labels = quarterData.map(d => d.time);
      mainChart.data.datasets[0].data = quarterData.map(d => d.kwh);
      mainChart.data.datasets[0].label = 'ML Prediction';
      mainChart.data.datasets[1].data = yesterdayReordered.map(d => d.kwh);
      mainChart.options.scales.y.title.text = 'kWh / 15min';
    }}
    mainChart.update();
  }});
}});

// Feature importance bars
const featContainer = document.getElementById('feat-bars');
const maxImp = Math.max(...featureImportance.map(f => f[1]));
const barColors2 = [blue, blue, orange, green, green, purple, green, '#484f58', '#484f58', '#484f58', '#484f58'];
featureImportance.forEach(([name, imp], i) => {{
  const pct = maxImp > 0 ? (imp / maxImp * 100) : 0;
  const row = document.createElement('div');
  row.className = 'feat-row';
  row.innerHTML = `
    <div class="feat-name">${{name.replace(/_/g, ' ')}}</div>
    <div class="feat-bar-wrap"><div class="feat-bar" style="width:${{pct}}%; background:${{barColors2[i] || '#484f58'}}"></div></div>
    <div class="feat-pct">${{(imp * 100).toFixed(1)}}%</div>
  `;
  featContainer.appendChild(row);
}});
</script>
</body>
</html>
"""


def _cmd_report(config: dict) -> None:
    """Retrain model, generate predictions for tomorrow, produce HTML chart."""
    from datetime import timedelta

    from ml.data_fetcher import fetch_history_context, fetch_weather_forecast
    from ml.predictor import predict_with_timestamps
    from ml.trainer import train_model

    target_date = date.today() + timedelta(days=1)

    print("Retraining model...")
    train_result = train_model(config)
    print(f"  Train samples: {train_result['train_size']}")
    print(f"  MAE: {train_result['metrics']['mae_kwh']:.4f} kWh")

    print(f"Generating predictions for {target_date}...")
    predictions = predict_with_timestamps(config, target_date)
    total_kwh = sum(kwh for _, kwh in predictions)
    print(f"  Predicted 24h total: {total_kwh:.2f} kWh")

    print("Fetching weather forecast...")
    weather_df = fetch_weather_forecast(config)
    print(f"  Weather points: {len(weather_df)}")

    print("Fetching history context...")
    history_context = fetch_history_context(config, target_date=target_date)
    print(f"  Yesterday total: {history_context['yesterday_total']:.2f} kWh")

    print("Generating HTML chart...")
    html = _generate_chart_html(train_result, predictions, weather_df, history_context)

    output_path = Path("ml") / f"prediction_chart-{date.today().isoformat()}.html"
    output_path.write_text(html, encoding="utf-8")

    print(f"\nReport saved: {output_path}")
    print("  Open in browser to view charts with live data")


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ml",
        description="ML Energy Consumption Predictor for BESS",
    )
    parser.add_argument(
        "command",
        choices=["train", "predict", "evaluate", "baseline", "fetch-data", "report"],
        help="Command to execute",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to ml_config.yaml (default: ml_config.yaml in project root)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--target-date",
        default=None,
        help="End date for data window (YYYY-MM-DD). Defaults to yesterday.",
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    config = load_config(args.config)

    target_date = None
    if args.target_date:
        target_date = date.fromisoformat(args.target_date)

    if args.command == "train":
        _cmd_train(config, target_date)
    elif args.command == "predict":
        _cmd_predict(config)
    elif args.command == "evaluate":
        _cmd_evaluate(config, target_date)
    elif args.command == "baseline":
        _cmd_baseline(config, target_date)
    elif args.command == "fetch-data":
        _cmd_fetch_data(config, target_date)
    elif args.command == "report":
        _cmd_report(config)
