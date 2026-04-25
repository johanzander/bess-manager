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

- Variable-length electricity price forecast at 15-minute resolution (from current period through end of available data; may span into the next day when tomorrow's prices are available)
- Battery parameters (capacity, limits, cycle cost)
- Consumption predictions (one entry per period, matching price array length)
- Solar production forecast (one entry per period, matching price array length)
- Current battery state and cost basis

**Outputs**:

- Battery actions (charge/discharge/idle) for each period in the horizon
- Expected battery SOC progression at 15-minute resolution
- Economic analysis (costs, savings, decision reasoning)

### DailyViewBuilder

**Purpose**: Creates complete daily views combining actual and predicted data at quarterly resolution.

**Key Responsibilities**:

- Merge historical actuals with current predictions
- Provide always-complete quarterly data for today (92–100 periods) for UI/API
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

### InverterController Hierarchy

**Purpose**: Converts optimization results to inverter-specific commands.

**Base class** `InverterController` provides shared intent-to-control mapping, hourly settings aggregation, and the abstract schedule interface. Three subclasses implement hardware-specific logic:

- **GrowattMinController** — Growatt MIN/MID/MOD (AC-coupled). Groups quarterly periods into TOU intervals (max 9 segments). Only creates segments for battery-first/grid-first; idle periods use load-first default.
- **GrowattSphController** — Growatt SPH (DC-coupled). Uses separate charge/discharge period lists (max 3 each) with global power and SOC settings per write call.
- **SolaxController** — SolaX (Modbus VPP). Issues per-period active-power commands instead of storing a persistent TOU schedule. Idle/solar periods disable VPP; charge/discharge periods set a watt target with autorepeat.

**Hardware Integration**:

- Each subclass formats schedules for its inverter's API
- Handles inverter-specific constraints and capabilities
- Manages schedule deployment and updates

### PriceManager

**Purpose**: Manages electricity price data and calculations.

**Key Responsibilities**:

- Fetch electricity spot prices for current day and next day (Nordpool or Octopus Energy)
- Calculate retail buy/sell prices with markup, VAT, additional costs
- Support multiple price areas (Nordpool SE1-SE4, Octopus Agile UK)
- Provide price forecasts for optimization

**Price Calculation**:

```python
buy_price = (spot_price + markup) * vat_multiplier + additional_costs
sell_price = spot_price * export_rate - tax_reduction
```

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

3. Optimization

   └── Run DP algorithm for remaining periods
   └── Store new schedule in ScheduleStore

4. Hardware Application

   └── InverterController converts to hardware-specific schedule
   └── Apply settings to inverter via HomeAssistantAPIController

5. View Generation

   └── DailyViewBuilder merges actual + predicted data
   └── Generate complete 24-hour view for UI/API
```

### System Startup Flow

```text

1. Component Initialization

   └── Load configuration and settings
   └── Initialize all managers and controllers

2. Historical Reconstruction

   └── SensorCollector queries InfluxDB for today's data
   └── Rebuild HistoricalDataStore with actual measurements

3. Initial Optimization

   └── First scheduled update runs fresh optimization
   └── Apply schedule to hardware

4. Service Start

   └── Begin hourly update cycle
   └── Start power monitoring and charging adjustment
```

## Key Algorithms

### Dynamic Programming Optimization

The DP algorithm uses **backward induction** to find the globally optimal battery schedule. Starting from the last period and working backwards, it evaluates all possible battery actions (charge/discharge/idle) at each period and selects the action that minimizes total electricity cost over the remaining horizon.

**State space**: Discretized battery state of energy (SOE) levels.

**Actions**: Discretized charge/discharge power levels, filtered by physical constraints (available energy, remaining capacity, power limits, temperature derating).

**Transition**: Each action updates SOE accounting for charging/discharging efficiency losses, and updates the cost basis of stored energy (FIFO accounting).

**Objective**: Minimize net electricity cost (grid import cost minus export revenue) while accounting for battery cycle degradation costs and a terminal value for energy remaining at end of horizon.

**Output**: For each period, the algorithm produces the optimal battery action, the resulting detailed energy flows (solar-to-home, grid-to-battery, etc.), economic data (costs, savings), and the strategic intent classification.

**Profit threshold**: After optimization, total savings are compared against a horizon-scaled minimum threshold. If savings are too low relative to remaining day fraction, the schedule is rejected in favor of all-IDLE to prevent excessive cycling for marginal gains.

### Energy Flow Calculation

The system decomposes measured energy totals into detailed flows (e.g., solar-to-home, grid-to-battery) using energy conservation constraints:

```python

# Home load priority - consume solar directly first

solar_to_home = min(solar_production, home_consumption)

# Remaining solar allocated to battery then grid

solar_to_battery = min(remaining_solar, battery_charged)
solar_to_grid = remaining_solar - solar_to_battery

# Grid fills remaining consumption and battery charging

grid_to_home = max(0, home_consumption - solar_to_home)
grid_to_battery = max(0, battery_charged - solar_to_battery)
```

### Decision Intelligence

Each optimization provides detailed economic reasoning:

- **Immediate Value**: Direct economic impact of each hour's decisions
- **Future Value**: Expected benefits from strategic energy storage
- **Economic Chain**: Step-by-step profit/loss calculation explanation
- **Alternative Analysis**: Why other strategies were not chosen

### Battery Action Intent Detection

The system infers battery action intent solely from the energy flows computed by the DP algorithm. After each period is solved, the detailed flows in `EnergyData` are derived automatically and used to classify intent:

- **EXPORT_ARBITRAGE**: `battery_to_grid > 0.1 kWh`
- **LOAD_SUPPORT**: `battery_to_home > 0.1 kWh` and `battery_to_grid <= 0.1 kWh`
- **GRID_CHARGING**: `grid_to_battery >= 0.1 kWh`
- **SOLAR_STORAGE**: `solar_to_battery > 0.1 kWh` and `grid_to_battery < 0.1 kWh`
- **IDLE**: No significant battery activity in any flow

### TOU Schedule Generation

The InverterController converts action intents into hardware-specific schedules. Each intent maps to an inverter battery mode and control parameters (shown below for Growatt MIN; other inverters use the same intent mapping with different hardware commands):

| Intent | Battery Mode | Grid Charge | Charge Rate | Discharge Rate |
|---|---|---|---|---|
| GRID_CHARGING | battery_first | On | 100% | 0% |
| SOLAR_STORAGE | load_first | Off | 100% | 0% |
| LOAD_SUPPORT | load_first | Off | 0% | 100% |
| EXPORT_ARBITRAGE | grid_first | Off | 0% | 100% |
| IDLE | load_first | Off | 100% | 0% |

**Why SOLAR_STORAGE and IDLE share the same inverter settings**: Both use `load_first` because solar energy serving the home directly is always more valuable than routing it through the battery (which incurs cycle cost). If prices are cheap enough to justify prioritizing battery charging over home load, the DP algorithm uses `GRID_CHARGING` instead, which enables AC grid-to-battery charging via `battery_first` mode. Using `battery_first` without `grid_charge` would cause unnecessary grid imports by routing solar to the battery first while the grid serves the home.

**Schedule generation**:

1. Group consecutive 15-minute periods that share the same battery mode
2. Only create TOU segments for strategic modes (battery_first, grid_first) — load_first is the inverter default and needs no segment
3. Enforce hardware constraints: max 9 TOU segments, chronological order, no overlaps
4. Preserve past intervals to minimize unnecessary inverter writes

## Configuration and Settings

Settings are managed through the web UI and persisted to `/data/bess_settings.json`. The only setting that remains in the HA Supervisor-controlled `config.yaml` (and thus `/data/options.json`) is the InfluxDB connection.

### InfluxDB Configuration (`config.yaml`)

```yaml
influxdb:
  url: "http://homeassistant.local:8086/api/v2/query"
  bucket: "home_assistant/autogen"
  username: "your_db_username_here"
  password: "your_db_password_here"
```

### Runtime Settings (`/data/bess_settings.json`)

All other settings are stored in this file and managed via the settings API. Top-level sections:

- **`battery`**: `total_capacity`, `min_soc`, `max_soc`, `max_charge_power_kw`, `max_discharge_power_kw`, `cycle_cost_per_kwh`, `min_action_profit_threshold`, `charging_power_rate`, `efficiency_charge`, `efficiency_discharge`
- **`electricity_price`**: `area`, `markup_rate`, `vat_multiplier`, `additional_costs`, `tax_reduction`, `min_profit`, `use_actual_price`
- **`home`**: `max_fuse_current`, `voltage`, `safety_margin`, `phase_count`, `default_hourly`, `currency`, `consumption_strategy`, `power_monitoring_enabled`
- **`growatt`**: Inverter device ID and integration settings
- **`sensors`**: Entity ID mappings for all Home Assistant sensors
- **`energy_provider`**: Price source selection (Nordpool or Octopus Energy) and area configuration

### Platform Selection

The system supports multiple inverter platforms, each with a dedicated controller subclass. The active platform is stored in `inverter.platform` as one of `"growatt_min"`, `"growatt_sph"`, or `"solax"`.

Switching platform at runtime calls `BatterySystemManager.switch_inverter_platform()`, which destroys the current `InverterController` and creates the correct subclass (`GrowattMinController`, `GrowattSphController`, or `SolaxController`). No restart is required.

### Auto-Detection and Integration Discovery

On first startup with no sensors configured, or when the user triggers discovery from the setup wizard or settings page, the system runs a multi-stage auto-detection process via `HAAPIController.discover_integrations()`.

#### Stage 1 — Integration Detection via Entity Registry

The HA WebSocket API (`config/entity_registry/list`) returns every registered entity with its `platform` field.

Detected integrations:

| Category  |   HA Platform    | Detected As |
|-----------|------------------|-------------|
| Inverter  | `growatt_server` | Growatt     |
| Inverter  | `solax_modbus`   | SolaX       |
| Price     | `nordpool`       | Nordpool    |
| Price     | `octopus_energy` | Octopus Energy |
| Forecast  | `solcast_solar`  | Solcast solar forecast |
| Forecast  | `weather`        | Weather (temperature derating) |

#### Stage 2 — Device Identifier Extraction

The HA REST API `/api/states` provides entity IDs and current values. The system uses naming patterns to extract device identifiers needed for service calls:

- **Growatt device SN**: Extracted from SOC sensor anchor entities matching `sensor.<sn>_state_of_charge_soc` or `sensor.<sn>_statement_of_charge_soc`
- **Nordpool area**: Extracted from the Nordpool entity ID or attributes
- **Phase count**: Detected from phase current sensor entities (L1/L2/L3)

#### Stage 3 — WebSocket Metadata Query

The HA WebSocket API provides internal IDs not available through REST:

- **Nordpool `config_entry_id`**: Required for the `nordpool.get_prices_for_date` service call
- **Growatt `device_id`**: Required for service calls like `growatt_server.update_time_segment`
- **Inverter type detection** (MIN vs SPH): Determined by which services are registered:
  - MIN: `growatt_server.update_time_segment`
  - SPH: `growatt_server.write_ac_charge_times`

#### Stage 4 — Sensor Mapping via Entity Registry

`discover_sensors_from_registry()` maps entity registry entries to BESS sensor keys. It filters entities by `platform` field (e.g. `growatt_server`), then matches the entity ID suffix against `ENTITY_SUFFIX_MAP` (Growatt) or `SOLAX_ENTITY_SUFFIX_MAP` (SolaX).

This approach uses two layers of filtering: first the `platform` field (immutable — set by HA core when the integration creates the entity), then suffix matching on the `entity_id`. Platform filtering ensures only genuine integration entities are considered, regardless of naming. Suffix matching works as long as the entity ID retains the original suffix (e.g. `_state_of_charge_soc`). Changing the friendly name/label in HA does not affect the entity ID, so discovery is unaffected. However, if a user changes the actual entity ID to remove the suffix, manual mapping via the wizard is required.

#### Derived Hints

After discovery, the system derives additional configuration hints:

- **Currency and VAT**: From the Nordpool area code prefix (SE → SEK/1.25, NO → NOK/1.25, DK → DKK/1.25, FI → EUR/1.255, etc.)
- **Phase count**: From detected phase current sensors
- **Inverter type**: From WebSocket service inspection (Growatt) or entity registry platform (SolaX)

#### Optional Sensor Discovery

Beyond core inverter and price sensors, discovery also detects:

- **Solcast solar forecast**: Entities matching `solcast_solar` platform with `forecast_today` / `forecast_tomorrow` in the entity ID
- **Weather**: Entities in the `weather.*` domain, preferring `weather.home` when multiple exist
- **Phase currents**: `current_l1`, `current_l2`, `current_l3`
- **EV charging inhibit**: Binary sensors ending with `_charging` or `_is_charging`
- **Consumption forecast**: Custom helper sensor for 48-hour average grid import

### Setup Wizard

The setup wizard is a 6-step flow for first-time configuration. It is triggered when no sensor entity IDs are configured.

#### Wizard API Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/setup/status` | Returns `wizard_needed` flag based on whether sensors are configured |
| `POST /api/setup/discover` | Runs full auto-discovery, returns sensors map, missing sensors, platform hints |
| `POST /api/setup/confirm` | Persists discovered sensor config to `/data/bess_discovered_config.json` and applies to live controller |
| `POST /api/setup/complete` | Atomic save of all wizard data across 6 settings sections |

#### Wizard Steps (Frontend: `SetupWizardPage.tsx`)

1. **Scan** — Calls `/api/setup/discover` to auto-detect integrations and sensors
2. **Review Sensors** — Displays discovered sensor mappings, allows manual correction, selects inverter platform
3. **Electricity Pricing** — Configure price area, provider (Nordpool/Octopus), markup, VAT (pre-filled from discovery hints)
4. **Battery** — Set capacity, SOC limits, power rating, cycle cost
5. **Home** — Set consumption, fuse current, voltage, phase count (pre-filled from detected phase count)
6. **Complete** — Calls `/api/setup/complete` for atomic save

#### Atomic Save (`/api/setup/complete`)

The complete endpoint performs a single atomic operation that:

1. Saves all 6 settings sections (`sensors`, `battery`, `home`, `electricity_price`, `energy_provider`, `inverter`/`growatt`) to `bess_settings.json` using read-modify-write to preserve non-wizard fields
2. Maps the UI inverter type (MIN/SPH/SOLAX) to canonical platform names and calls `switch_inverter_platform()`
3. Applies live updates to all running components (sensors, battery settings, home settings, price settings)
4. Spawns a background thread that backfills historical data from InfluxDB, builds the daily schedule, and re-runs the health check

#### Discovery-to-Completion Flow

```text
Frontend (SetupWizardPage)
    │
    ├── [1] POST /api/setup/discover
    │       └── HAAPIController.discover_integrations()
    │           ├── Entity Registry scan → platform detection
    │           ├── Entity States scan → device SN / prefix extraction
    │           ├── WebSocket query → internal IDs, inverter type
    │           └── Sensor mapping → ENTITY_SUFFIX_MAP matching
    │
    ├── [2] POST /api/setup/confirm
    │       └── Persist to /data/bess_discovered_config.json
    │       └── Apply sensor config to live ha_controller
    │
    ├── [3] User fills remaining wizard steps (pricing, battery, home)
    │
    └── [4] POST /api/setup/complete
            ├── SettingsStore.save_all() → atomic write of 6 sections
            ├── switch_inverter_platform() → recreate controller
            ├── update_settings() → apply live changes
            └── Background: backfill history + build schedule + health check
```

### Settings Page (Ongoing Platform Management)

After initial setup, the Settings page (`SettingsPage.tsx`) provides ongoing platform and sensor management through `PATCH /api/settings`.

**Platform switching**: When the user changes the inverter platform in the Sensors tab, the backend validates the platform string, calls `switch_inverter_platform()` to recreate the controller, and re-runs the health check. Both platform configurations can coexist in the settings file — only the active platform's sensors are used at runtime.

**Sensor editing**: Individual sensor entity IDs can be updated. The backend validates entity ID format (`[a-z]+\.[a-z0-9_]+`) before applying changes.

**Re-discovery**: The user can trigger a fresh auto-discovery from the Settings page to update sensor mappings without going through the full wizard again.

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
│             Price Provider (Nordpool / Octopus Energy)          │
│           Provides: 96 quarterly prices (15-min)                │
│           Format: Arrays indexed 0-95 for today                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PriceManager                               │
│  - get_available_prices() → (buy[N], sell[N])                   │
│  - Normalises provider data to quarterly arrays (no expansion)  │
│  - DST-aware: validates 92-100 periods                          │
│  - Simple array indexing: index 0 = today 00:00-00:15           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                 BatterySystemManager                            │
│  - Optimization: variable-length horizon (today + tomorrow)     │
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
│  - Returns 96 quarterly PeriodData items (today only)           │
│  - Simple logic: if i < current_period: actual, else: predicted │
│  - Calculates summary statistics                                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API Layer (FastAPI)                         │
│  - GET /api/dashboard?resolution=quarter-hourly → today's periods│
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

- Internal data structures use one entry per period (92–100 depending on DST)
- The DP optimizer operates on a variable-length horizon (today's remaining periods plus tomorrow's when available)
- Simple integer indices (0-95 for a normal day, 0-91/0-99 for DST transitions)
- Array-based operations (slicing, summing, mapping)

**DST Handling**:

- Period count varies: 92 (spring), 96 (normal), 100 (fall)
- All components handle variable period counts
- No hardcoded 24-hour assumptions
- Validation uses ranges (92-100) not fixed values

**Data Flow**:

- **Price Provider**: Nordpool or Octopus Energy provides quarterly prices
- **Optimization**: Operates on variable-length arrays (today's remaining periods + tomorrow's when available)
- **Storage**: Indexes by period_index (0-95)
- **InfluxDB**: Queries at 15-minute boundaries
- **API**: Returns quarterly, aggregates only for display
- **Frontend**: Displays both resolutions as user preference


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

### Mock HA Environment

The mock HA environment lets any user-reported issue be reproduced and debugged
locally, without access to the user's Home Assistant installation.

**Invariant**: `mock(debug_export)` must be indistinguishable from the real HA
installation at the moment the debug export was taken.

#### Workflow

```
/api/export-debug-data      ← debug export (markdown file)
from_debug_log.py           ← generates scenario JSON
mock-run.sh                 ← starts Docker Compose
  ├── mock-ha               (FastAPI, serves scenario data as HA REST API)
  └── bess-dev              (BESS backend, TZ + FAKETIME pinned to export time)
```

#### What the Debug Export Provides

| Field | Used for |
|---|---|
| `entity_snapshot` | Verbatim `/api/states/{entity_id}` responses for every sensor BESS reads |
| `historical_periods` | Actual measured energy flows — seeded directly into the historical store, no InfluxDB needed |
| `price_data` | Raw quarterly prices for `nordpool_official` service call responses |
| `addon_options` | Complete sensor entity IDs, inverter device ID, price provider config |
| `inverter_tou_segments` | Current inverter memory state for `read_time_segments` responses |
| `export_timestamp` + `timezone` | Pins `mock_time` so BESS computes the same optimization period |

#### Historical Seeding

At startup, `BatterySystemManager` checks for `BESS_HISTORICAL_SEED_FILE`. If
set, it loads `historical_periods` directly into the historical store and skips
InfluxDB backfill entirely. The sensor collector cache is then warmed from live
mock-HA values so runtime collections work correctly. The mock is fully
self-contained — no external database access required.

This design reflects the current quarterly-native implementation as of the latest refactoring, focusing on simplicity and correctness across all time-based operations.
