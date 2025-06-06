# Test Scenario Data

This directory contains JSON files representing test scenarios for the battery optimization algorithm.

## Scenario Types

### Historical Scenarios

- **Naming Convention**: `historical_YYYY_MM_DD_pattern_description.json`
- **Purpose**: Test the algorithm against known price patterns from specific dates with expected results
- **Content**: Includes `expected_results` field for validation
- **Examples**:
  - `historical_2024_08_16_high_spread_no_solar.json`: Historical high price spread on 2024-08-16, no solar
  - `historical_2025_01_05_no_spread_no_solar.json`: Historical flat prices on 2025-01-05, no solar

### Synthetic Historical Scenarios

- **Naming Convention**: `synthetic_historical_YYYY_MM_DD_pattern_description.json`
- **Purpose**: Test the algorithm with historical price data but synthetic solar production
- **Content**: Uses historical prices but synthetic solar data
- **Examples**:
  - `synthetic_historical_2024_08_16_high_spread_with_solar.json`: Historical prices with synthetic solar

### Synthetic Scenarios

- **Naming Convention**: `synthetic_category_description.json`
- **Purpose**: Test specific behaviors or edge cases (no validation against expected values)
- **Categories**:
  - `seasonal_`: Seasonal price and production patterns (winter, summer, spring)
  - `consumption_`: Different home consumption profiles
  - `extreme_`: Edge cases and extreme conditions
- **Examples**:
  - `synthetic_seasonal_winter.json`: Winter price and solar patterns
  - `synthetic_consumption_ev_charging.json`: Home with EV charging
  - `synthetic_extreme_volatility.json`: Highly volatile prices

### Sample Scenarios

- **Naming Convention**: `sample_scenario.json`
- **Purpose**: Basic test scenario for quick functionality checks

## File Structure

Each scenario JSON file includes the following fields:

- `name`: Scenario identifier (same as filename without extension)
- `description`: Brief description of the scenario
- `base_prices`: 24 hourly Nordpool electricity prices (SEK/kWh excl. VAT)
- `home_consumption`: 24 hourly home consumption values (kWh)
- `solar_production`: 24 hourly solar production values (kWh)
- `battery`: Battery parameters (capacity, efficiency, etc.)
- `expected_results`: Expected optimization results
