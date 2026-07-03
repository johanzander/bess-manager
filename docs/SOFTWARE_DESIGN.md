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

1. **Discretization**: Battery state of energy (SOE) and power levels are discretized into fine-grained steps (0.1 kWh / 0.2 kW)
2. **Backward Induction**: Starting from the last period, work backwards evaluating all feasible actions (charge/discharge/idle) at each (period, SOE) cell
3. **Reward + Future Value**: For each action, compute the immediate reward (grid cost savings minus cycle cost) plus the optimal future value from the resulting SOE state
4. **Policy Extraction**: Forward-simulate from the initial SOE, following the optimal action at each step to produce the final schedule
5. **Profitability Gate**: Reject the schedule in favour of all-IDLE if total savings fall below a horizon-scaled minimum threshold

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

**Base class** `InverterController` provides shared intent-to-control mapping, hourly settings aggregation, and the abstract schedule interface. Four subclasses implement hardware-specific logic:

- **GrowattMinController** — Growatt MIN/MID/MOD (AC-coupled, cloud). Groups quarterly periods into TOU intervals (max 9 segments). Only creates segments for battery-first/grid-first; idle periods use load-first default. Writes via `growatt_server.update_time_segment` service call.
- **GrowattSolaxModbusController** — Growatt MIN/MID/MOD (AC-coupled, local Modbus). Subclasses `GrowattMinController` — identical scheduling algorithm. Overrides only the I/O layer: writes via `select.select_option` (4 per slot) + `button.press` (1 per slot). Reads via entity state queries.
- **GrowattSphController** — Growatt SPH (DC-coupled). Uses separate charge/discharge period lists (max 3 each) with global power and SOC settings per write call. Writes via `growatt_server.write_ac_charge_times` / `write_ac_discharge_times`.
- **SolaxController** — SolaX (Modbus VPP). Issues per-period active-power commands instead of storing a persistent TOU schedule. Idle/solar periods disable VPP; charge/discharge periods set a watt target with autorepeat.

**Per-period control** (shared across all platforms): At each 15-minute period boundary, `_write_period_to_hardware()` issues generic HA entity calls:
- `switch.turn_on` / `switch.turn_off` — grid charge enable/disable
- `number.set_value` — charge/discharge power rate

These resolve to platform-specific entities via the sensor config (e.g. `grid_charge` → `switch.rkm…_charge_from_grid` on Growatt cloud, or `switch.solax_charger_switch` on solax_modbus).

**Entity suffix maps** (`ENTITY_SUFFIX_MAP` and `SOLAX_ENTITY_SUFFIX_MAP` in `ha_api_controller.py`) define the full mapping from unique_id suffixes to BESS sensor keys. See `docs/INVERTER_PLATFORMS.md` for the user-facing entity reference.

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

- **Immediate Value**: Direct economic impact of each period's decisions
- **Future Value**: Expected benefits from strategic energy storage
- **Economic Chain**: Step-by-step profit/loss calculation explanation

### Battery Action Intent Detection

The system classifies battery action intent using the battery power action as the primary discriminator, with energy flows as secondary input. Classification is performed by `classify_strategic_intent(power, energy_data)` in `decision_intelligence.py`:

- **Discharging** (power < −0.1 kW):
  - **BATTERY_EXPORT**: `battery_to_grid > 0.1 kWh`
  - **LOAD_SUPPORT**: otherwise (discharge serves home load)
- **Charging** (power > 0.1 kW):
  - **GRID_CHARGING**: `grid_to_battery > solar_to_battery` (grid is dominant charge source)
  - **SOLAR_STORAGE**: otherwise (solar is dominant charge source)
- **Near-zero power** (fallthrough for passive flows):
  - **SOLAR_STORAGE**: `battery_charged > 0.01 kWh` (passive solar charging)
  - **LOAD_SUPPORT**: `battery_discharged > 0.01 kWh` (small residual discharge)
  - **SOLAR_EXPORT**: `grid_exported > 0.01 kWh` and `solar_to_grid > 0.01 kWh` (solar surplus exporting, battery idle)
  - **IDLE**: no significant battery activity

### TOU Schedule Generation

The InverterController converts action intents into hardware-specific schedules. Each intent maps to an inverter battery mode and control parameters (shown below for Growatt MIN; other inverters use the same intent mapping with different hardware commands):

| Intent | Battery Mode | Grid Charge | Discharge Rate |
|---|---|---|---|
| GRID_CHARGING | battery_first | On | 0% |
| SOLAR_STORAGE | load_first | Off | 0% |
| LOAD_SUPPORT | load_first | Off | action-derived |
| BATTERY_EXPORT | grid_first | Off | action-derived |
| SOLAR_EXPORT | load_first | Off | 0% |
| IDLE | load_first | Off | 0% |

**Why SOLAR_STORAGE and IDLE share the same inverter settings**: Both use `load_first` because solar energy serving the home directly is always more valuable than routing it through the battery (which incurs cycle cost). If prices are cheap enough to justify prioritizing battery charging over home load, the DP algorithm uses `GRID_CHARGING` instead, which enables AC grid-to-battery charging via `battery_first` mode. Using `battery_first` without `grid_charge` would cause unnecessary grid imports by routing solar to the battery first while the grid serves the home.

**Why SOLAR_EXPORT uses load_first (not grid_first)**: Solar exports naturally in `load_first` when generation exceeds consumption — no special inverter mode is needed. `SOLAR_EXPORT` exists as a distinct intent purely for UI display (distinguishing "solar actively exporting" from "nothing happening"). Using `grid_first` for battery-idle periods would lock the inverter in a mode that prevents the battery from supporting house load during temporary solar deficits.

**Why BATTERY_EXPORT requires grid_first**: The inverter must route battery discharge toward the grid rather than the home. In `load_first`, discharge would serve home load first; only `grid_first` guarantees battery energy reaches the grid.

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

The system supports multiple inverter platforms, each with a dedicated controller subclass:

| Platform ID | Inverter | HA Integration | Control Method | Controller Class |
|---|---|---|---|---|
| `growatt_min` | Growatt MIC/MIN/MOD/MID | `growatt_server` (cloud) | TOU service calls | `GrowattMinController` |
| `growatt_solax_modbus` | Growatt MIC/MIN/MOD/MID | `solax_modbus` (local Modbus) | TOU entity writes | `GrowattSolaxModbusController` |
| `growatt_sph` | Growatt SPH | `growatt_server` (cloud) | AC charge/discharge periods | `GrowattSphController` |
| `solax` | SolaX | `solax_modbus` (local Modbus) | VPP active-power commands | `SolaxController` |

The active platform is stored in `inverter.platform`. Switching platform at runtime calls `BatterySystemManager.switch_inverter_platform()`, which destroys the current `InverterController` and creates the correct subclass. No restart is required.

`GrowattSolaxModbusController` subclasses `GrowattMinController` — the scheduling algorithm (9 TOU slots, differential updates, corruption recovery) is identical. Only the hardware I/O differs: `growatt_server` uses a single service call per slot, while `solax_modbus` uses 4 entity writes (`select.select_option`) plus a button press per slot.

### Platform Capabilities

Different inverter platforms support different hardware features. The class hierarchy handles **behavioral** differences (TOU scheduling vs. period lists vs. VPP commands — genuinely different algorithms). Capabilities handle the narrower question: what does code *outside* the controller need to know about the platform?

Currently only one capability exists: `charge_rate_control`. It is declared as a `ClassVar[bool]` on `InverterController` (default `True`) and overridden to `False` by subclasses whose hardware lacks per-period charge/discharge rate registers (SPH, SolaX native). BSM checks this flag to decide whether to initialize the power monitor and whether `adjust_charging_power()` should run.

```python
# inverter_controller.py (base class)
supports_charge_rate_control: ClassVar[bool] = True

# growatt_sph_controller.py
supports_charge_rate_control: ClassVar[bool] = False

# solax_controller.py
supports_charge_rate_control: ClassVar[bool] = False
```

| Capability | Description | MIN | SPH | SolaX Native | Modbus Growatt MIN |
|---|---|---|---|---|---|
| `supports_charge_rate_control` | Per-period charge/discharge rate register | Yes | **No** | **No** | Yes |

SPH controls charge power globally via `write_ac_charge_times(charge_power=100%)`. SolaX native uses VPP active-power commands. Neither has a per-period register that the power monitor can read/write, so fuse protection cannot function.

#### Frontend Gating

The frontend disables UI features based on **sensor presence**, which correlates with platform capabilities: if the platform lacks charge rate control, the corresponding sensor entity won't exist after discovery. This avoids needing a dedicated capabilities API endpoint — the sensor config already carries the signal.

- Fuse protection toggle: disabled when `battery_charging_power_rate` sensor is not configured
- InfluxDB consumption strategy: disabled when `local_load_power` sensor is not configured
- HA Statistics strategy: disabled when `lifetime_load_consumption` sensor is not configured

Sensor-based gating is the right default. A dedicated capabilities API should only be introduced when the frontend needs to gate on something that doesn't map to sensor presence.

#### Evolution Path

The single `ClassVar[bool]` is sufficient while capabilities are few and boolean. If the number of externally-queried capabilities grows beyond 2–3 flags, consolidate into a frozen `PlatformCapabilities` dataclass with typed fields (booleans, integers, Literals). The decision criteria: add a capability only when code **outside** the controller hierarchy needs to branch on it. Internal differences (schedule model, max slots, power control method) belong in the subclass, not the capability surface.

#### Adding a New Capability

1. Add `supports_foo: ClassVar[bool] = True` to `InverterController`
2. Override to `False` on subclasses that lack the feature
3. Gate the feature in BSM / frontend as appropriate

#### Adding a New Inverter Platform

1. Create an `InverterController` subclass implementing the abstract methods
2. Override any `supports_*` flags where the platform differs from defaults
3. Add the platform string to `VALID_PLATFORMS` and the factory in `_create_inverter_controller()`
4. Add entity suffix map entries to `ha_api_controller.py` for sensor discovery

### Auto-Detection and Integration Discovery

On first startup with no sensors configured, or when the user triggers discovery from the setup wizard or settings page, the system runs a multi-stage auto-detection process via `HAAPIController.discover_integrations()`.

#### Stage 1 — Integration Detection via Entity Registry

The HA WebSocket API (`config/entity_registry/list`) returns every registered entity with its `platform` field.

Detected integrations:

| Category  |   HA Platform       | Detected As |
|-----------|---------------------|-------------|
| Inverter  | `growatt_server`    | Growatt     |
| Inverter  | `solax_modbus`      | SolaX       |
| Price     | `nordpool`          | Nordpool    |
| Price     | `octopus_energy`    | Octopus Energy |
| Forecast  | `solcast_solar`     | Solcast solar forecast |
| Forecast  | `weather`           | Weather (temperature derating) |

**Nordpool: official vs HACS custom**

Both the official HA Nordpool integration and the older HACS custom component (`custom_components/nordpool`) register entities under the `nordpool` platform domain, so Stage 1 detection cannot distinguish them. The distinction is made as follows:

1. **Stage 3** checks `config_entries/get` for a loaded `nordpool` config entry. If found, the official integration is available and its `config_entry_id` is stored.
2. **The user selects** which provider to use in the Setup Wizard or Settings page (radio button: "Nord Pool (official HA integration)" vs "Nord Pool (HACS custom sensor)").
3. **At runtime**, the selected provider determines how prices are fetched:
   - `nordpool_official`: Calls `nordpool.get_prices_for_date` service action (requires `config_entry_id`)
   - `nordpool`: Reads hourly prices from sensor entity attributes (`today`/`tomorrow` lists on a single entity)

#### Stage 2 — Intermediate Identifiers from Entity IDs

The HA REST API `/api/states` provides all entity IDs and current values. BESS extracts intermediate identifiers from entity naming patterns — these are NOT the final IDs used in service calls, but are needed to look up the actual HA-internal IDs in Stage 3.

- **Growatt device serial number (SN)**: The `growatt_server` integration creates entity IDs with the inverter serial number as a prefix (e.g. `sensor.rkm0d7n04x_state_of_charge_soc`). BESS extracts this SN (`rkm0d7n04x`) via `_extract_growatt_device_sn()`. The SN is used in Stage 3 as a lookup key into the HA device registry to find the actual `device_id` (a hex string like `fbafceb07a1cc74c351ef4310fa430a0`) required by service calls.
- **Nordpool area**: Parsed from Nordpool entity IDs (e.g. `sensor.nordpool_kwh_se4_sek_...` → `SE4`)
- **Phase count**: Detected from phase current sensor entities (L1/L2/L3)

#### Stage 3 — WebSocket Metadata Query

`discover_ha_metadata()` queries the HA WebSocket API to resolve the actual identifiers needed for service calls. These IDs are HA-internal and not available via the REST API. Four WebSocket commands are batched in a single connection:

| Command | Purpose |
|---------|---------|
| `config_entries/get` | Find config entry IDs by integration domain |
| `config/device_registry/list` | Resolve device SN → HA `device_id` |
| `get_services` | Detect inverter type from registered services |
| `config/entity_registry/list` | Extract Nordpool area from `unique_id` |

Resolved identifiers:

- **Growatt `device_id`** (e.g. `fbafceb07a1cc74c351ef4310fa430a0`): The HA device registry ID. All `growatt_server` service calls (e.g. `update_time_segment`) require this as their `device_id` parameter. Resolution strategy (first match wins):
  1. Match the SN from Stage 2 against device `identifiers` tuples (most reliable)
  2. Match by `config_entry_id` belonging to the `growatt_server` integration
  3. Match by device `name` equal to SN (legacy fallback)
- **Nordpool `config_entry_id`**: Required for `nordpool.get_prices_for_date` service calls. Found by scanning config entries for `domain == "nordpool"` with `state == "loaded"`.
- **Nordpool area** (fallback): If not resolved in Stage 2, extracted from entity registry `unique_id` values (format `"SE4-current_price"`).
- **Inverter type**: Determined from registered services and entity markers:
  - MIN: `growatt_server.update_time_segment` service present
  - SPH: `growatt_server.write_ac_charge_times` service present
  - GROWATT_MODBUS: `solax_modbus` entities with TOU time slot marker (`time_1_enabled` unique_id suffix — note: the entity_id contains `time_1_active` from the display name, but detection matches on unique_id)
  - SOLAX: `solax_modbus` entities with VPP marker (`remotecontrol_power_control` unique_id suffix)

#### Stage 4 — Sensor Mapping via Entity Registry

`discover_sensors_from_registry()` maps entity registry entries to BESS sensor keys **for each detected inverter integration**. It runs separately for each platform found in Stage 1 (e.g. `growatt_server` entities are mapped using `ENTITY_SUFFIX_MAP`, `solax_modbus` entities using `SOLAX_ENTITY_SUFFIX_MAP`). If both are detected, both sets are returned and the user selects which platform to use.

The mapping uses two layers of filtering:

1. **Platform field** (immutable — set by HA core when the integration creates the entity). Only entities belonging to the target integration are considered.
2. **`unique_id` suffix matching**. The `unique_id` is assigned by the integration at entity creation and never changes regardless of user renames. BESS matches suffixes like `_state_of_charge_soc` or `_battery_soc` against the suffix map to determine the BESS sensor key.

The result maps each BESS sensor key (e.g. `battery_soc`) to the corresponding HA `entity_id` (e.g. `sensor.rkm0d7n04x_state_of_charge_soc`). This entity_id is what the REST API uses to read state values at runtime.

Renaming entities in the HA UI (friendly name/label) does not affect discovery. However, if a user changes the actual entity_id and removes the original suffix, the `unique_id` still matches — so discovery still works. Only if the integration itself changes its `unique_id` scheme (across versions) would manual remapping via the wizard be needed.

#### Derived Hints

After discovery, the system derives additional configuration hints:

- **Currency and VAT**: From the Nordpool area code prefix (SE → SEK/1.25, NO → NOK/1.25, DK → DKK/1.25, FI → EUR/1.255, etc.)
- **Phase count**: From detected phase current sensors
- **Inverter type**: From WebSocket service inspection (Growatt MIN/SPH), entity registry TOU marker (Growatt via solax_modbus), or entity registry platform (SolaX)

#### Optional Sensor Discovery

Beyond core inverter and price sensors, discovery also detects:

- **Solcast solar forecast**: Entity registry entries on the `solcast_solar` platform, matched by `unique_id` suffix (robust against non-English HA locale renaming of the entity ID)
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
2. Maps the UI inverter type (MIN/GROWATT_MODBUS/SPH/SOLAX) to canonical platform names and calls `switch_inverter_platform()`
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
