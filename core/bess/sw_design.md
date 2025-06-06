# Battery Energy Storage System (BESS) Design Documentation

## 1. System Overview

The Battery Energy Storage System (BESS) manages a home battery installation to optimize electricity costs and maximize the value of solar and grid interactions. The system provides:

1. **Globally optimal battery scheduling** over a 24-hour or longer horizon, considering all technical and economic constraints.
2. **Integrated economic modeling** that values solar, grid, and battery wear costs, dynamically adapting to price and solar forecasts.
3. **Real-time adaptation** to actual measurements, with the ability to re-optimize as new data arrives.
4. **Advanced reporting and visualization** for both technical and economic performance.
5. **Modular, extensible architecture** to support future enhancements such as multi-day optimization, machine learning-based forecasting, and grid export strategies.

## 2. System Architecture

The system follows a modular design with clear separation of concerns:

```text
┌───────────────────┐
│  BESS Controller  │  Main entry point (pyscript file in Home Assistant)
│    (pyscript)     │  Schedules and triggers system operations
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│                   │  Core facade that coordinates all components
│ BatterySystemMgr  │  Manages the battery optimization process
│                   │  Maintains system state and settings
└─────────┬─────────┘
          │
          ├─────────────────┬───────────────────┬───────────────┐
          │                 │                   │               │
          ▼                 ▼                   ▼               ▼
┌─────────────────┐ ┌───────────────┐ ┌──────────────┐ ┌───────────────┐
│ Home Assistant  │ │               │ │              │ │ Schedule &    │
│   Controller    │ │ EnergyManager │ │ PriceManager │ │ GrowattMgr    │
│                 │ │               │ │              │ │               │
└─────────┬───────┘ └───────┬───────┘ └──────┬───────┘ └───────┬───────┘
          │                 │                │                 │
          ▼                 │                │                 │
┌─────────────────┐         │                │                 │
│ Home Assistant  │         │                │                 │
│ Services & API  │         │                │                 │
└─────────┬───────┘         │                │                 │
          │                 │                │                 │
          ▼                 │                │                 │
┌─────────────────┐         │                │                 │
│                 │         │                │                 │
│ Battery/Inverter│◄────────┴────────────────┴─────────────────┘
│                 │        Indirect interaction via HA Controller
└─────────────────┘
```

## 2. Core Components

### 2.1 BatterySystemManager

**Purpose:** Main facade that coordinates all components and provides the primary API.

**Key Responsibilities:**

- Initialize and configure system components
- Create and update battery schedules
- Apply scheduled settings to the physical battery system
- Coordinate hourly updates and adaptations
- Manage system settings

**Key Methods:**

- `update_schedule(hour)`: Update system state for current hour
- `create_schedule(price_entries, price_date)`: Generate optimal schedule
- `apply_hourly_schedule(hour)`: Apply settings for specific hour
- `apply_todays_schedule()`: Apply schedule for current day
- `apply_next_day_schedule()`: Apply schedule for next day
- `adjust_charging_power()`: Adapt charging power based on home consumption

### 2.2 EnergyManager

**Purpose:** Centralized management of all energy-related data and predictions.

**Key Responsibilities:**

- Directly collect energy measurements from sensors
- Track historical energy flows with hourly granularity
- Validate energy balance and detect inconsistencies
- Provide combined historical/forecast data for optimization
- Log energy balance reports and statistics

**Key Methods:**

- `update_hour_data(hour)`: Update energy data for completed hour
- `get_combined_energy_data(current_hour)`: Get combined actual/predicted energy profile
- `set_consumption_predictions(values)`: Set hourly consumption predictions
- `set_solar_predictions(values)`: Set hourly solar predictions
- `log_energy_balance()`: Log comprehensive energy balance report

### 2.3 Schedule

**Purpose:** Represent battery charge/discharge schedule with hourly granularity.

**Key Responsibilities:**

- Store optimization results (actions, state of energy)
- Calculate costs and savings
- Format data for display and API
- Provide interface for controller access

**Key Methods:**

- `set_optimization_results(actions, state_of_energy, prices, ...)`: Initialize with optimization results
- `get_hour_settings(hour)`: Get settings for specific hour
- `get_schedule_data()`: Get complete formatted schedule data
- `log_schedule()`: Print formatted schedule table

### 2.4 PriceManager

**Purpose:** Manage electricity price data from various sources.

**Key Responsibilities:**

- Fetch price data from configured source
- Calculate retail buy/sell prices
- Format price data for optimization

**Key Methods:**

- `get_today_prices()`: Get prices for current day
- `get_tomorrow_prices()`: Get prices for next day
- `calculate_prices(base_price)`: Apply markup, VAT, etc.

### 2.5 GrowattScheduleManager

**Purpose:** Convert generic schedule to Growatt-specific format.

**Key Responsibilities:**

- Convert hourly schedule to Growatt TOU intervals
- Manage grid charge and discharge rate settings
- Format schedules for the Growatt inverter

**Key Methods:**

- `create_schedule(schedule)`: Process generic schedule into Growatt format
- `get_daily_TOU_settings()`: Get battery-first TOU intervals
- `get_hourly_settings(hour)`: Get settings for specific hour

### 2.6 HomePowerMonitor

**Purpose:** Monitor home power consumption and adjust battery charging.

**Key Responsibilities:**

- Monitor current draw on electrical phases
- Calculate available charging power
- Adjust battery charging power to prevent overload

**Key Methods:**

- `calculate_available_charging_power()`: Calculate safe charging power
- `adjust_battery_charging()`: Apply calculated charging power

## 3. Data Models

### 3.1 Battery State

**Battery Energy State:**

- State of Charge (SOC): Percentage (0-100%)
- State of Energy (SOE): Absolute energy (kWh)
- Reserved Capacity: Minimum energy to maintain (kWh)
- Total Capacity: Maximum energy capacity (kWh)

**Actions:**

- Positive values: Charging (kWh)
- Negative values: Discharging (kWh)
- Zero: Standby (no action)

### 3.2 Energy Flows

**Measured Values:**

- Grid Import: Energy from grid (kWh)
- Solar Generation: Energy from solar (kWh)
- Battery SOC: Current battery level (%)

**Calculated Values:**

- Home Consumption: Energy used in home (kWh)
- Battery Change: Net energy change in battery (kWh)
- Solar to Battery: Solar energy directed to battery (kWh)

### 3.3 Electricity Prices

**Price Components:**

- Base Price: Raw Nordpool spot price (SEK/kWh)
- Buy Price: Retail price with markup, VAT (SEK/kWh)
- Sell Price: Price received when selling back (SEK/kWh)

**Time Structure:**

- 24 hourly prices per day
- Today's prices: Available early morning
- Tomorrow's prices: Available around 13:00

### 3.4 Settings

**Battery Settings:**

- Total Capacity: Maximum battery energy (kWh)
- Min/Max SOC: Allowable state of charge range (%)
- Max Charge/Discharge Power: Power limits (kW)
- Charge Cycle Cost: Battery wear cost (SEK/kWh)
- Charging Power Rate: Maximum power percentage (%)

**Price Settings:**

- Area Code: Price area (SE1-SE4)
- Markup Rate: Additional supplier cost (SEK/kWh)
- VAT Multiplier: Value-added tax (typically 1.25)
- Additional Costs: Fixed grid charges (SEK/kWh)
- Tax Reduction: For selling back to grid (SEK/kWh)
- Min Profit: Threshold for trading (SEK/kWh)

**Home Settings:**

- Max Fuse Current: Circuit breaker limit (A)
- Voltage: Line voltage (V)
- Safety Margin: For power calculations (%)

## 4. Key Algorithms

### 4.1 Battery Optimization Algorithm

**Purpose:** Optimize battery charging/discharging to maximize profit.

**Inputs:**

- Hourly electricity prices
- Battery parameters (capacity, reserved, cycle cost)
- Hourly consumption predictions
- Current battery state (SOC)
- Solar charging predictions
- Cost basis of stored energy

**Algorithm Flow:**

1. **Initialize** state with current battery SOC
2. **Apply solar charging** first (free energy)
3. **Value current stored energy** based on charging history
4. **Find profitable trades** (charge hour, discharge hour pairs)
5. **Sort trades by profit per kWh** (most profitable first)
6. **Execute trades while respecting constraints:**
   - Battery capacity limits
   - Charging power limits
   - Discharge limited by consumption
   - Maintain energy balance
   - Only execute profitable trades

### 4.2 Solar Detection Algorithm

**Purpose:** Detect solar energy charging the battery.

**Method:**

1. Compare actual battery change with planned action
2. If actual > planned, excess is likely solar:

   ```python
   solar_to_battery = min(
       actual_change - planned_action,
       measured_solar_generation
   )
   ```

3. Track solar charging for optimization and reporting

### 4.3 Energy Balance Validation

**Purpose:** Ensure energy accounting is accurate.

**Energy Balance Equation:**

```python
grid_import + solar_generation = home_consumption + battery_change
```

**Validation Process:**

1. Track all energy flows
2. Calculate consumption from other measurements
3. Ensure consumption is non-negative (adjust if needed)
4. Periodically verify total energy balance (in = out)

### 4.4 Schedule Adaptation

**Purpose:** Determine when to update the battery schedule.

**Decision Criteria:**

1. Always update at hour 0 (midnight)
2. Update if solar charging differs significantly
3. Update if TOU intervals differ
4. Update if hourly settings for future hours differ

## 5. Control Flow

### 5.1 Hourly Update Flow

**Purpose:** Adapt the schedule based on real-time measurements.

**Process:**

1. **Collect Measurements**
   - Battery SOC
   - Grid import
   - Solar generation

2. **Update Energy Monitor**
   - Track energy flows
   - Detect solar charging
   - Validate energy balance

3. **Prepare Optimization Data**
   - Combine actual past data with predictions
   - Calculate cost basis of stored energy
   - Preserve past schedule (can't change the past)

4. **Run Optimization**
   - Optimize future hours only
   - Consider current battery state
   - Value existing stored energy
   - Account for detected solar

5. **Compare & Apply**
   - Compare new schedule with current
   - Apply if different (or hour 0)
   - Update controller settings

### 5.2 Daily Schedule Creation

**Purpose:** Prepare optimal schedule for a new day.

**Process:**

1. **Fetch Price Data**
   - Get today's or tomorrow's prices
   - Calculate buy/sell prices

2. **Configure Optimization**
   - Set battery parameters
   - Use consumption predictions
   - Set solar predictions
   - Use current battery SOC

3. **Run Optimization**
   - Generate optimal actions
   - Calculate costs and savings

4. **Apply Schedule**
   - Convert to Growatt format
   - Configure TOU intervals
   - Set initial hour settings

### 5.3 Real-time Power Monitoring

**Purpose:** Adjust charging power based on home consumption.

**Process:**

1. **Monitor Phase Loads**
   - Check current on each phase
   - Convert to power (W)
   - Identify most loaded phase

2. **Calculate Available Capacity**
   - Determine percentage of capacity used
   - Calculate safe charging percentage
   - Apply safety margin

3. **Adjust Charging Power**
   - Change charging power in small steps
   - Stay within calculated safe limit
   - Only active when grid charging enabled
