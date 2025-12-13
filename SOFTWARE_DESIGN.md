# BESS Manager Software Design

## System Overview

The Battery Energy Storage System (BESS) Manager is a Home Assistant add-on that optimizes battery storage systems for cost savings through price-based arbitrage and solar integration. The system uses dynamic programming optimization to generate optimal daily battery schedules at 15-minute (quarterly) resolution while adapting to real-time conditions.

## Architecture Principles

- **Event-Driven Design**: Hourly updates and schedule adaptations based on real measurements
- **Component Separation**: Clear boundaries between data collection, optimization, and control
- **Deterministic Operation**: Explicit failure modes, no fallbacks or defaults
- **Data Immutability**: Historical data is immutable, predictions are versioned

## Core Components

### BatterySystemManager

**Purpose**: Main coordinator that orchestrates all components and provides the primary API.

**Key Responsibilities**:

- Initialize and configure system components
- Create and update battery schedules using dynamic programming optimization
- Apply scheduled settings to Growatt inverter via Home Assistant
- Coordinate hourly updates and real-time adaptations
- Manage system settings and configuration

**Key Methods**:

```python
def update_battery_schedule(current_period: int, prepare_next_day: bool = False) -> None
def adjust_charging_power() -> None
def update_settings(settings: dict) -> None
def get_current_daily_view(current_period: int | None = None) -> DailyView
def start() -> None
```

### SensorCollector

**Purpose**: Collects energy data from Home Assistant sensors with validation and flow calculation.

**Key Responsibilities**:

- Collect quarterly (15-minute) energy measurements from InfluxDB and real-time sensors
- Calculate detailed energy flows (solar-to-home, grid-to-battery, etc.)
- Validate energy balance and detect sensor anomalies
- Reconstruct historical data during system startup
- Support strategic intent reconstruction from sensor patterns

**Data Sources**:

- InfluxDB for historical cumulative sensor data
- Home Assistant API for real-time readings
- Sensor abstraction layer for device independence

### HomeAssistantAPIController

**Purpose**: Centralized interface to Home Assistant with sensor abstraction.

**Key Responsibilities**:

- Manage sensor configuration and entity ID mapping
- Provide unified API for reading sensor values and controlling devices
- Handle different sensor types (power, energy, state)
- Support sensor validation and health checking
- Control Growatt inverter settings (battery modes, TOU schedules)

**Sensor Abstraction**:

- All sensor access uses method names, not entity IDs
- Configurable sensor mapping for different hardware setups
- Centralized validation and error handling

### Dynamic Programming Optimization Engine

**Purpose**: Core algorithm that generates optimal battery schedules.

**Algorithm Flow**:

1. **State Initialization**: Start with current battery SOC and energy basis
2. **Solar Integration**: Apply predicted solar charging (free energy)
3. **Arbitrage Opportunities**: Find profitable charge/discharge pairs
4. **Constraint Optimization**: Respect battery capacity, power limits, consumption needs
5. **Economic Modeling**: Include battery cycle costs, price calculations

**Inputs**:

- 96 quarterly (15-minute) electricity price forecast
- Battery parameters (capacity, limits, cycle cost)
- Consumption predictions (96 quarterly periods)
- Solar production forecast (96 quarterly periods)
- Current battery state and cost basis

**Outputs**:

- Quarterly battery actions (charge/discharge/idle) for 96 periods
- Expected battery SOC progression at 15-minute resolution
- Economic analysis (costs, savings, decision reasoning)

### DailyViewBuilder

**Purpose**: Creates complete daily views combining actual and predicted data at quarterly resolution.

**Key Responsibilities**:

- Merge historical actuals with current predictions
- Provide always-complete 96-period quarterly data for UI/API
- Recalculate total daily savings from combined data
- Mark data sources (actual vs predicted) for each period

**Data Integration**:

- Historical data from HistoricalDataStore (immutable)
- Predicted data from ScheduleStore (latest optimization)
- Real-time current state for seamless transitions

### HistoricalDataStore

**Purpose**: Immutable storage of actual energy events that occurred.

**Data Model**:

```python
class PeriodData:
    period: int  # Period index (0-95 for normal day)
    energy: EnergyData  # Actual measured flows
    timestamp: datetime
    data_source: str = "actual"
    economic: EconomicData
    decision: DecisionData
```

**Key Features**:

- Immutable once recorded
- Complete energy flow tracking
- Physics validation (energy balance)
- Supports data reconstruction after system restart

### ScheduleStore

**Purpose**: Versioned storage of optimization results throughout the day.

**Storage Model**:

```python
class StoredSchedule:
    timestamp: datetime
    optimization_period: int
    optimization_result: OptimizationResult
```

**Key Features**:

- Stores complete optimization results with metadata
- Tracks when and why each optimization was created
- Enables debugging and analysis of optimization decisions
- Supports multiple optimizations per day as conditions change

### GrowattScheduleManager

**Purpose**: Converts optimization results to Growatt inverter commands.

**Key Responsibilities**:

- Convert quarterly schedule to hourly Time-of-Use (TOU) intervals (hardware constraint)
- Manage battery modes (load-first, battery-first)
- Configure grid charging and discharge rate settings
- Apply strategic intents to hardware parameters
- Aggregate quarterly periods to hourly for Growatt inverter

**Hardware Integration**:

- Formats schedules for Growatt inverter API
- Handles inverter-specific constraints and capabilities
- Manages schedule deployment and updates

### PriceManager

**Purpose**: Manages electricity price data and calculations.

**Key Responsibilities**:

- Fetch Nordpool spot prices for current day and next day
- Calculate retail buy/sell prices with markup, VAT, additional costs
- Support multiple price areas (SE1-SE4)
- Provide price forecasts for optimization

**Price Calculation**:

```python
buy_price = (spot_price + markup) * vat_multiplier + additional_costs
sell_price = spot_price * export_rate - tax_reduction
```text

### PowerMonitor

**Purpose**: Real-time power monitoring and charging adjustment.

**Key Responsibilities**:

- Monitor electrical phase loading to prevent circuit overload
- Calculate available charging power based on current consumption
- Dynamically adjust battery charging power to stay within fuse limits
- Provide safety margins for electrical system protection

## Data Flow Architecture

### Hourly Update Cycle

```text

1. Sensor Collection

   └── SensorCollector reads InfluxDB + real-time sensors
   └── Calculate energy flows and validate balance

2. Historical Recording

   └── Record completed hour in HistoricalDataStore
   └── Immutable storage of what actually happened

3. Optimization Decision

   └── Check if reoptimization needed (significant changes)
   └── Run DP algorithm for remaining hours
   └── Store new schedule in ScheduleStore

4. Hardware Application

   └── GrowattScheduleManager converts to TOU intervals
   └── Apply settings to inverter via HomeAssistantAPIController

5. View Generation

   └── DailyViewBuilder merges actual + predicted data
   └── Generate complete 24-hour view for UI/API
```text

### System Startup Flow

```text

1. Component Initialization

   └── Load configuration and settings
   └── Initialize all managers and controllers

2. Historical Reconstruction

   └── SensorCollector queries InfluxDB for today's data
   └── Rebuild HistoricalDataStore with actual measurements

3. Schedule Recovery

   └── Determine current hour and battery state
   └── Run optimization for remaining hours
   └── Apply current schedule to hardware

4. Service Start

   └── Begin hourly update cycle
   └── Start power monitoring and charging adjustment
```text

## Key Algorithms

### Energy Flow Calculation

The system calculates detailed energy flows using physical constraints:

```python

# Home load priority - consume solar directly first

solar_to_home = min(solar_production, home_consumption)

# Remaining solar allocated to battery then grid

solar_to_battery = min(remaining_solar, battery_charged)
solar_to_grid = remaining_solar - solar_to_battery

# Grid fills remaining consumption and battery charging

grid_to_home = max(0, home_consumption - solar_to_home)
grid_to_battery = max(0, battery_charged - solar_to_battery)
```text

### Strategic Intent Detection

The system infers strategic intent from sensor measurements:

- **GRID_CHARGING**: Battery charging while grid imports exceed consumption
- **SOLAR_CHARGING**: Battery charging during solar production periods
- **PEAK_EXPORT**: Battery discharging during high-price periods
- **LOAD_SUPPORT**: Battery discharging to reduce grid imports

### Decision Intelligence

Each optimization provides detailed economic reasoning:

- **Immediate Value**: Direct economic impact of each hour's decisions
- **Future Value**: Expected benefits from strategic energy storage
- **Economic Chain**: Step-by-step profit/loss calculation explanation
- **Alternative Analysis**: Why other strategies were not chosen

## Configuration and Settings

### Battery Configuration

```yaml
battery:
  total_capacity: 30.0          # kWh
  min_soc: 10.0                # %
  max_soc: 100.0               # %
  max_charge_discharge_power: 15.0  # kW
  cycle_cost: 0.40             # SEK/kWh
```text

### Price Configuration

```yaml
electricity_price:
  area: "SE4"                  # Nordpool area
  markup_rate: 0.08            # SEK/kWh
  vat_multiplier: 1.25         # 25% VAT
  additional_costs: 1.03       # Grid charges
  tax_reduction: 0.6518        # Export compensation
```text

### Sensor Configuration

```yaml
sensors:
  battery_soc: "sensor.battery_level"
  grid_import_power: "sensor.grid_import"
  solar_production: "sensor.solar_production"

  # ... additional sensor mappings

```text

## Health Monitoring

The system includes comprehensive health checking:

- **Sensor Validation**: Required vs optional sensors, data quality checks
- **Component Status**: Each manager reports operational status
- **Energy Balance**: Physics validation of measured energy flows
- **Optimization Health**: Algorithm convergence and result validation
- **Hardware Connection**: Inverter communication and control verification

## API Architecture

### Dashboard API (`/api/dashboard`)

- Complete daily energy flow data (96 quarterly periods or 24 hourly aggregated)
- Resolution parameter: `quarter-hourly` or `hourly`
- Real-time power monitoring
- Economic analysis and savings breakdown
- Battery status and schedule information

### Decision Intelligence API (`/api/decision-intelligence`)

- Quarterly and hourly decision analysis with economic reasoning
- Strategic intent explanation and flow patterns
- Alternative scenario analysis
- Confidence metrics and prediction accuracy

### Settings APIs (`/api/settings/battery`, `/api/settings/electricity`)

- Runtime configuration management
- Validation and error handling
- Live updates without system restart

### Inverter Control APIs (`/api/growatt/*`)

- Real-time inverter status
- Detailed schedule management
- TOU interval configuration
- Strategic intent monitoring

## Quarterly Resolution Architecture

### System Architecture Diagram

The system operates on **quarterly resolution (15-minute periods)** throughout the entire stack:

```text
┌─────────────────────────────────────────────────────────────────┐
│                      Nordpool API                               │
│           Provides: 96 quarterly prices (15-min)                │
│           Format: Arrays indexed 0-95 for today                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PriceManager                               │
│  - get_available_prices() → (buy[96], sell[96])                 │
│  - Uses Nordpool quarterly data directly (no expansion)         │
│  - DST-aware: validates 92-100 periods                          │
│  - Simple array indexing: index 0 = today 00:00-00:15           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                 BatterySystemManager                            │
│  - Optimization: 96 quarterly periods                           │
│  - Storage: record_period(period_index, period_data)            │
│  - Collection: Uses period indices (0-95 normal, 0-91/99 DST)   │
│  - InfluxDB: Queries at 15-minute boundaries                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│  HistoricalDataStore     │  │    ScheduleStore         │
│  dict[int, PeriodData]   │  │  Optimization results    │
│  - Stores actual data    │  │  - Predicted data        │
│  - Period index keys     │  │  - Strategic intents     │
│  - 92-100 periods/day    │  │  - Battery actions       │
└──────────────────────────┘  └──────────────────────────┘
                │                         │
                └────────────┬────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   DailyViewBuilder                              │
│  - Merges actual (past) + predicted (future)                    │
│  - Returns 96 quarterly PeriodData items                        │
│  - Simple logic: if i < current_period: actual, else: predicted │
│  - Calculates summary statistics                                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API Layer (FastAPI)                         │
│  - GET /api/dashboard?resolution=quarter-hourly → 96 periods    │
│  - GET /api/dashboard?resolution=hourly → 24 aggregated         │
│  - Internal data: Always quarterly (96 periods)                 │
│  - Aggregation: Display-only feature for UI                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (React)                             │
│  - EnergyFlowChart: Displays quarterly (96) or hourly (24)      │
│  - EnergyFlowCards: Shows totals with flow breakdowns           │
│  - Resolution toggle: User display preference                   │
│  - All calculations use actual quarterly data                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

**Quarterly-First Architecture**:

- All internal data structures use 96 quarterly periods
- No hourly resolution at core level - only for display
- Simple integer indices (0-95 for normal day)
- Array-based operations (slicing, summing, mapping)

**DST Handling**:

- Period count varies: 92 (spring), 96 (normal), 100 (fall)
- All components handle variable period counts
- No hardcoded 24-hour assumptions
- Validation uses ranges (92-100) not fixed values

**Data Flow**:

- **Nordpool**: Provides 96 quarterly prices directly
- **Optimization**: Operates on 96-period arrays
- **Storage**: Indexes by period_index (0-95)
- **InfluxDB**: Queries at 15-minute boundaries
- **API**: Returns quarterly, aggregates only for display
- **Frontend**: Displays both resolutions as user preference

**Simplifications from Quarterly Design**:

- No complex interval metadata
- No triple data models (hourly/quarterly/metadata)
- No hour-to-period conversions in core logic
- Reduced code size by ~70% compared to previous design
- Simple continuous indexing eliminates edge cases

## Development and Testing

### Component Testing

- **Unit Tests**: Individual component validation with synthetic data
- **Integration Tests**: End-to-end workflow testing with real scenarios
- **Optimization Tests**: Algorithm correctness with various market conditions
- **Hardware Tests**: Inverter integration and sensor validation
- **Quarterly Tests**: DST transitions and period boundary handling

### Test Data

- **Historical Scenarios**: Real price data from high-volatility days
- **Synthetic Patterns**: EV charging, seasonal variations, extreme conditions
- **Edge Cases**: Sensor failures, price anomalies, hardware issues, DST transitions

### Quality Assurance

- **Code Quality**: Ruff, Black, Pylance compliance
- **Type Safety**: Strict typing with union operators (`|`)
- **Documentation**: Comprehensive docstrings and design documentation
- **Performance**: Optimization runtime and memory usage monitoring
- **Period Validation**: No hardcoded 24/96 checks, DST-aware throughout

This design reflects the current quarterly-native implementation as of the latest refactoring, focusing on simplicity and correctness across all time-based operations.
