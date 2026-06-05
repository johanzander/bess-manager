# BESS Domain Knowledge

Shared domain knowledge for all BESS analyst contexts (GitHub issue analysis,
in-app AI chat, etc.).  This is the single source of truth for how the BESS
system works and how to investigate it.

## Key Source Files

Read these before analyzing any issue.  Use tools (read_file, search_code)
to read the actual code — never assume how things work from memory.

| File | What it explains |
|------|-----------------|
| `decisionframework.md` | Strategic intents, economic decision logic, when charging/discharging is profitable |
| `core/bess/sw_design_hourly_update.wsd` | System flow: when and how optimization runs, how schedules are applied |
| `core/bess/dp_battery_algorithm.py` | Dynamic programming optimization, cost basis tracking, profitability thresholds, savings calculation |
| `core/bess/models.py` | EnergyData (energy flows), EconomicData (costs/savings), PeriodData (historical/predicted) |
| `core/bess/energy_flow_calculator.py` | How sensor data becomes energy flows, derived flow calculations |
| `core/bess/growatt_schedule.py` | How strategic intents become TOU intervals, hardware schedule application |
| `core/bess/daily_view_builder.py` | How historical and predicted data are combined for the dashboard |
| `core/bess/battery_system_manager.py` | Main orchestrator |
| `core/bess/decision_intelligence.py` | Decision explanations |
| `core/bess/settings.py` | Configuration parameters |

## Evidence-Based Analysis

**Every claim must be backed by evidence** — a specific data point, log line,
or line of code.  If you cannot point to evidence, do not make the claim.

Rules:
- NEVER speculate.  Do not use "likely", "probably", "suggests", "may have",
  "possibly", or "could have".  State what happened with evidence, or say
  "I don't have enough data to determine this."
- Start from what the data actually shows, not from a theory about what
  might have happened.
- Verify claims against actual code paths — code that works for one inverter
  platform may behave differently on another.
- A design choice that is intentional is not a bug, even if a user finds it
  unexpected.

## Strategic Intents and Hardware Behavior

Strategic intents are NOT just labels — they control actual inverter modes:
- **EXPORT_ARBITRAGE** → grid_first mode (enables export)
- **GRID_CHARGING** → battery_first mode (allows grid charging)
- **LOAD_SUPPORT** → load_first mode (discharge for home)
- Wrong intent = wrong hardware mode = system malfunction

## Prediction Snapshots and Expected Savings

The prediction snapshots track **expected total savings** over the day.
Each snapshot records:

    expected_savings = actual_savings + predicted_savings

- **Actual savings**: sum of savings for completed time slots (past).
- **Predicted savings**: sum of savings for future time slots (from the
  latest optimization schedule).

**Expected savings should NOT naturally decrease as time passes.** As the
day progresses, predictions become actuals, but the total should stay
roughly the same IF the system performs as predicted.

If expected savings DROP between snapshots, it means **actual performance
was worse than predicted** — NOT "natural decay."

Possible causes (but you MUST verify which one by checking the data):
- Tomorrow's prices became available, causing the optimizer to shift
  discharge value to a more profitable time tomorrow.
- Actual solar production was lower than the forecast.
- Actual consumption was higher than estimated (e.g., EV charging).
- Price data changed between optimization runs.

**NEVER say savings "naturally decay" or "diminish over time."** A drop
is always a real deviation that deserves investigation with specific data.

## Debugging Negative Savings

1. Read how `EconomicData.from_energy_and_prices()` calculates savings
2. Understand the difference between:
   - `hourly_savings`: per-quarter-hour comparison
   - `grid_to_battery_solar_savings`: total optimization savings
3. Check if viewing partial arbitrage cycle (charge happened, discharge pending)
4. Verify energy balance consistency in sensor data

## Debugging Optimization Decisions

1. Read `dp_battery_algorithm.py` optimization logic
2. Check `min_action_profit_threshold` vs calculated savings
3. Trace the cost basis tracking through charge/discharge
4. Verify price data fed to optimizer

## Debugging Schedule Issues

1. Read `growatt_schedule.py` TOU conversion logic
2. Check strategic intent → TOU interval mapping
3. Verify schedule comparison logic (why update vs keep)
