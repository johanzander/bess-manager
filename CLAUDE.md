# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BESS Battery Manager is a Home Assistant add-on for optimizing battery energy storage systems. It provides price-based optimization, solar integration, and comprehensive web interface for managing battery schedules and monitoring energy flows.

## Development Commands

### Backend (Python)

```bash

# Install dependencies

pip install -r backend/requirements.txt

# Run development server

./dev-run.sh

# Run tests

pytest
pytest core/bess/tests/unit/
pytest core/bess/tests/integration/
pytest --cov=core.bess

# Code quality

black .
ruff check --fix .
mypy .
```text

### Frontend (React/TypeScript)

```bash
cd frontend

# Install dependencies

npm install

# Development server

npm run dev

# Build production

npm run build

# Generate API client from OpenAPI spec

npm run generate-api
```text

### Docker Development

```bash

# Start both backend and frontend

docker-compose up -d

# View logs

docker-compose logs -f
```text

### Build Add-on

```bash
chmod +x package-addon.sh
./package-addon.sh
```text

### Quality Checks

```bash

# Run comprehensive quality checks

./scripts/quality-check.sh

# Individual checks

black .                    # Format Python code
ruff check --fix .        # Fix Python linting issues
cd frontend && npm run lint:fix  # Fix TypeScript issues
```text

## Architecture Overview

### High-Level System Design

- **Backend**: FastAPI application (`backend/app.py`) with scheduled optimization jobs
- **Core**: Battery optimization engine (`core/bess/`) with modular components
- **Frontend**: React SPA with real-time dashboard and management interface
- **Integration**: Home Assistant add-on with sensor collection and device control

### Key Components

#### Core BESS System (`core/bess/`)

- **BatterySystemManager**: Main orchestrator managing optimization lifecycle
- **DP Battery Algorithm**: Dynamic programming optimization engine for cost minimization
- **HomeAssistantAPIController**: Centralized interface to HA with sensor abstraction
- **SensorCollector**: Aggregates real-time energy data from HA sensors
- **GrowattScheduleManager**: Converts optimization results to Growatt inverter commands
- **PriceManager**: Handles Nordpool electricity pricing with markup calculations
- **HealthCheck**: Comprehensive system and sensor validation

#### Data Flow

1. **Hourly Updates**: Scheduler triggers optimization every hour
2. **Sensor Collection**: Real-time data from HA sensors (battery, solar, grid, consumption)
3. **Price Integration**: Nordpool spot prices with VAT/markup calculations
4. **Optimization**: DP algorithm generates 24-hour battery schedule
5. **Schedule Deployment**: TOU intervals sent to Growatt inverter
6. **Monitoring**: Dashboard displays real-time status and historical analysis

#### API Structure (`backend/api.py`)

- **Settings Endpoints**: Battery and electricity price configuration
- **Dashboard API**: Unified data for energy flows, savings, and real-time monitoring
- **Decision Intelligence**: Detailed hourly strategy analysis and economic reasoning
- **Inverter Control**: Growatt-specific status and schedule management
- **System Health**: Component diagnostics and sensor validation

### Frontend Architecture (`frontend/src/`)

#### Pages

- **DashboardPage**: Live monitoring and daily overview
- **SavingsPage**: Financial analysis and historical reports
- **InverterPage**: Battery schedule management and inverter status
- **InsightsPage**: Decision intelligence and strategy analysis
- **SystemHealthPage**: Component health and diagnostics

#### Key Components

- **EnergyFlowChart**: Recharts-based visualization of hourly energy flows
- **SystemStatusCard**: Real-time power monitoring with live data
- **InverterStatusDashboard**: Battery status and schedule visualization
- **DecisionFramework**: Strategic decision analysis with economic reasoning

#### State Management

- **useSettings**: Global battery and price settings management
- **API Integration**: Axios-based API client with Home Assistant ingress support
- **Real-time Updates**: Polling-based data refresh for live monitoring

## Coding Guidelines

### Core Development Principles

#### Mandatory Codebase Review Before Refactoring

**CRITICAL**: Before starting any refactoring, architectural changes, or adding new functionality, you MUST perform a comprehensive codebase analysis to understand existing patterns and avoid duplication.

**Required Analysis Steps**:

1. **Search for Existing Implementations**:
   ```bash
   # Search for similar functionality
   grep -r "dataclass\|serialization\|formatting" --include="*.py"
   grep -r "HealthStatus\|SystemHealth" --include="*.ts" --include="*.tsx" 
   find . -name "*api*" -name "*model*" -name "*conversion*"
   ```

1. **Examine Related Files**:
   - `backend/api_dataclasses.py` - existing API models
   - `backend/api_conversion.py` - serialization utilities  
   - `frontend/src/types.ts` - TypeScript interfaces
   - `core/bess/` - domain models and services
   - Any files matching the functionality you plan to add

1. **Understand Existing Patterns**:
   - How does the codebase currently handle the problem you're solving?
   - What naming conventions and architectural patterns are used?
   - Are there existing utilities, services, or models you should extend?

1. **Document Existing Infrastructure**:
   - List what already exists and works
   - Identify what's actually missing vs what you assumed was missing
   - Plan minimal additions that integrate with existing code

**Red Flags That Indicate Insufficient Analysis**:

- Creating files with names similar to existing files (`api_models.py` when `api_dataclasses.py` exists)
- Recreating functionality that already exists (serialization, enum definitions)
- Writing code that doesn't follow existing patterns
- Adding new dependencies when existing ones could be used

**Example of Proper Analysis**:

```markdown
## Codebase Analysis for Sensor Formatting

### Existing Infrastructure Found:
- ✅ API Dataclasses: `backend/api_dataclasses.py` 
- ✅ Serialization: `backend/api_conversion.py`
- ✅ Health Types: `frontend/src/types.ts`
- ✅ Health Endpoint: `/api/system-health` in `backend/api.py`

### What's Actually Missing:
- ❌ Centralized sensor unit formatting (only frontend string matching exists)
- ❌ Unit metadata in METHOD_SENSOR_MAP

### Minimal Required Changes:
1. Add unit metadata to existing METHOD_SENSOR_MAP
2. Create SensorFormattingService 
3. Integrate with existing health check system
```

**Consequences of Skipping This Analysis**:

- Duplicate code that needs to be removed
- Inconsistent architecture
- Wasted development time
- Technical debt creation
- Loss of user trust

#### Code Preservation and Evolution

- **Never remove or modify existing functionality or comments** unless explicitly asked to
- **Produce code without reference to older versions** - don't write "UPDATED ALGORITHM" or reference previous implementations
- **Always check the code, don't make assumptions** - if you don't understand something, ask for clarification

#### Deterministic System Design

- **Never use hasattr, fallbacks or default values** - use error/assert instead
- **We are developing a deterministic system** - methods and functionality should not disappear or degrade gracefully
- **Explicit failures over silent failures** - better to crash with clear error than continue with undefined behavior

#### Architectural Consistency

- **Think about current software design** when adding new functionality
- **Extend existing components** instead of creating parallel implementations
- **You are not allowed to create new classes without approval** - work within existing design patterns
- **Never repeat code** - apply DRY principle rigorously

#### Modern Python Standards

- **Use union operator `|` instead of `Optional`** from typing module
- **Always ensure code passes Ruff, black, pylance** - code quality is non-negotiable
- **Follow existing type annotations** and maintain strict typing discipline

#### File Quality Standards

- **Never create files that generate IDE problems or linter errors**
- **All markdown files must pass markdownlint validation**
- **All Python files must pass Ruff, Black, and Pylance without warnings**
- **All TypeScript files must pass ESLint and TypeScript compiler checks**
- **Check Problems tab before committing - zero tolerance for preventable issues**

#### Markdown Formatting Rules

- **Blank lines around headers**: Always add blank line before and after headers
- **Proper list spacing**: Add blank line before lists, none between list items
- **No trailing spaces**: Remove all trailing whitespace
- **Single blank lines**: Never use multiple consecutive blank lines
- **Consistent heading levels**: Don't skip heading levels (no h1 → h3)

```markdown

# Good Example

## Header with proper spacing

This paragraph has proper spacing around it.

### Sub-header

- List item 1
- List item 2
- List item 3

Another paragraph after the list.

## Bad Example

###Missing blank lines

- List immediately after header
- No spacing


Too many blank lines above.
```text

#### Pre-Commit Quality Checklist

Before creating or modifying any files, ALWAYS:

1. **Check Problems Tab**: View → Problems in VS Code - must show zero errors/warnings for modified files
2. **Run Code Formatters**:
   - Python: `black .` and `ruff check --fix .`
   - TypeScript: `npm run lint:fix` in frontend directory
   - Markdown: Use markdownlint extension to fix formatting
3. **Validate File Extensions**: Ensure proper file extensions (.py, .ts, .tsx, .md, .json)
4. **Check File Encoding**: Use UTF-8 encoding for all text files
5. **Remove Temporary Files**: Never commit .tmp, .bak, or editor swap files

#### Automated Quality Check

Run the quality check script before committing:

```bash
./scripts/quality-check.sh
```text

This script automatically checks:

- Python formatting (Black) and linting (Ruff)
- TypeScript compilation and ESLint in frontend
- Markdown formatting issues (trailing spaces, blank lines)
- File encoding and common problems

#### Common Issues to Avoid

- **Markdown**: Missing blank lines around headers, trailing spaces, multiple consecutive blank lines
- **Python**: Type hints using Optional instead of `|`, missing docstrings, unused imports
- **TypeScript**: `any` types, missing interfaces, inconsistent naming conventions
- **JSON**: Trailing commas, incorrect indentation, missing quotes
- **General**: Mixed line endings (LF vs CRLF), BOM markers, trailing whitespace

### Existing Patterns to Follow

#### Component Integration

- **Search before implementing**: Use existing utilities and patterns before writing new code
- **Use existing controller methods** instead of creating wrappers (e.g., `controller.get_battery_soc()`)
- **Apply health check patterns**: `perform_health_check()` with standardized parameters
- **All sensor access** goes through `ha_api_controller` centralized mapping
- **Use `_get_sensor_key(method_name)`** for entity ID resolution instead of manual extraction

#### Architecture Patterns

- **Health Check System**: Use `perform_health_check()` for all validations
  - Define `required_methods` (critical) vs `optional_methods`
  - Return lists of health check dictionaries, not individual results
- **Sensor Management**: All access through centralized mapping, never hardcode device names
- **Error Handling**: Use existing validation, don't duplicate upstream error checking
- **Settings**: Use dataclass-based configuration with `update()` methods

#### Error Handling Standards

- **NEVER use string matching on exception messages** for flow control (e.g., `if "price data" in str(e)`)
- **Use specific exception types** instead of generic ValueError/Exception catching
- **Create proper exception classes** when needed rather than parsing error message strings
- **String-based error detection is brittle** and breaks when error messages change
- **Example of bad pattern**: `except ValueError as e: if "No price data" in str(e): ...`
- **Example of good pattern**: `except PriceDataUnavailableError: ...`

#### Anti-Patterns to Avoid

1. **Reinventing the wheel**: Creating new methods when existing ones work
2. **Inconsistent patterns**: Using different approaches for the same operation type
3. **Overengineering**: Adding unnecessary complexity to simple operations
4. **Hardcoding**: Using device-specific names instead of centralized mapping
5. **Code duplication**: Copy-pasting logic instead of using shared functions

#### Code Examples

```python

# Good: Use existing controller method

soc_value = self.ha_controller.get_battery_soc()

# Bad: Manual sensor key extraction

sensor_info = self.ha_controller.METHOD_SENSOR_MAP["get_battery_soc"]
soc_sensor_key = sensor_info.get("entity_id")

# Good: Use centralized health check

return perform_health_check(
    component_name="Battery Monitoring",
    description="Real-time battery state monitoring",
    is_required=True,
    controller=self.ha_controller,
    all_methods=battery_methods,
    required_methods=required_battery_methods
)

# Bad: Custom health check logic with hardcoded thresholds

working_count = sum(1 for method in methods if test_method(method))
if working_count >= 3:
    return "OK"
elif working_count >= 1:
    return "WARNING"
else:
    return "ERROR"
```text

#### API Conventions

- **CamelCase Conversion**: All API responses use `convert_keys_to_camel_case()`
- **Unified Data Models**: Use `APIBatterySettings`, `APIPriceSettings` for consistency
- **Error Responses**: Always include meaningful error messages and HTTP status codes
- **Real-time Data**: Use `APIRealTimePower.from_controller()` for live power monitoring

## Testing Strategy

### Unit Tests (`core/bess/tests/unit/`)

- **Scenario Testing**: JSON test data files for various conditions
- **Algorithm Validation**: DP optimization correctness and edge cases
- **Settings Management**: Configuration validation and updates
- **Data Models**: Energy balance validation and economic calculations

### Integration Tests (`core/bess/tests/integration/`)

- **System Workflow**: End-to-end optimization and schedule deployment
- **Cost Savings Flow**: Multi-scenario economic validation
- **Battery Management**: State tracking and capacity management
- **Schedule Management**: TOU interval generation and validation

### Test Data

- **Synthetic Scenarios**: EV charging, high solar export, extreme volatility
- **Historical Data**: Real price data from specific high-spread days
- **Seasonal Patterns**: Spring/summer/winter consumption profiles

## Home Assistant Integration

### Sensor Requirements

- **Battery**: SOC, charge/discharge power, mode status
- **Solar**: Production, home consumption, grid import/export
- **Pricing**: Nordpool spot prices with area configuration
- **Grid**: Import/export power and energy totals

### Add-on Configuration

- **Battery Settings**: Capacity, power limits, cycle costs, SOC bounds
- **Price Settings**: Area, VAT, markup, additional costs, tax reduction
- **Home Settings**: Consumption patterns, electrical limits, safety margins

### Device Control

- **Growatt Integration**: TOU schedules, battery modes, power rate control
- **Schedule Deployment**: Automatic hourly schedule updates
- **Real-time Monitoring**: Live power flow tracking and status updates

## Common Development Tasks

### Adding New Sensors

1. Update `METHOD_SENSOR_MAP` in `ha_api_controller.py`
2. Add validation in relevant health check functions
3. Update API response models if needed
4. Test with synthetic and real data

### Modifying Optimization Algorithm

1. Update core logic in `dp_battery_algorithm.py`
2. Add test scenarios in `unit/data/` directory
3. Validate with `test_optimization_algorithm.py`
4. Update decision intelligence reasoning if needed

### Frontend Component Development

1. Follow existing component patterns and API integration
2. Use TypeScript interfaces matching backend data models
3. Implement error boundaries and loading states
4. Test with real API data and edge cases

### Adding New API Endpoints

1. Define endpoint in `backend/api.py` with proper error handling
2. Use `convert_keys_to_camel_case()` for response formatting
3. Add corresponding frontend API integration
4. Update OpenAPI spec and regenerate client types

## Configuration Files

- **pyproject.toml**: Python tooling (black, ruff, mypy) with BESS-specific settings
- **frontend/package.json**: React/TypeScript dependencies and build scripts
- **docker-compose.yml**: Development environment with HA integration
- **backend/config.yaml**: Add-on configuration schema and defaults

## Unit Testing Guidelines

**CRITICAL**: Always write tests that verify **BEHAVIOR**, not **IMPLEMENTATION**.

### ❌ BAD: Testing Implementation Details

```python
# Don't test internal data structures
strategic_segments = [i for i in intervals if i.get('period_type') == 'strategic']
assert len(strategic_segments) == 1
assert strategic_segments[0]['start_time'] == '20:00'

# Don't test algorithm-specific details
assert len(intervals) == 9  # Specific to "9 fixed slots" algorithm
assert slot_start_times == ['02:40', '05:20']  # Specific slot boundaries
```

### ✅ GOOD: Testing Business Behavior

```python
# Test what the system should DO, not HOW it does it
def test_export_arbitrage_enables_battery_discharge():
    strategic_intents[20] = 'EXPORT_ARBITRAGE'
    scheduler.apply_schedule(strategic_intents)
    
    # Test BEHAVIOR: Battery should discharge during target hour
    assert scheduler.is_hour_configured_for_export(20)
    
    # Test CONSTRAINTS: Hardware requirements must be met
    assert scheduler.has_no_overlapping_intervals()
    assert scheduler.intervals_are_chronologically_ordered()
```

### The Test Rewrite Principle

**When algorithms change, behavior-based tests should NOT break.** If your tests break when you swap algorithms, they were testing implementation, not requirements.

#### Test Categories

1. **Business Logic Tests**: Does the system do what users need?
   - Strategic intents execute correctly (charge/discharge at right times)
   - Energy optimization produces cost savings
   - Schedule adapts to price changes

2. **Constraint Tests**: Does the system meet technical requirements?
   - No overlapping intervals (hardware constraint)
   - Chronological ordering (hardware constraint)
   - Minimal inverter writes (operational efficiency)

3. **Integration Tests**: Do components work together?
   - Price data feeds into optimization
   - Optimization results control hardware
   - Sensor data updates system state

#### Red Flags in Tests

- Testing specific field names (`period_type`, `segment_id`)
- Testing exact internal boundaries (`02:40-05:19`)
- Testing algorithm-specific counts (`len(intervals) == 9`)
- Comments mentioning implementation (`"Fixed slots approach"`)
- Tests that break when equivalent algorithms are swapped

#### Writing Good Tests

1. **Start with requirements**: What should this system do?
2. **Test the interface**: What would a user/integrator observe?
3. **Test constraints**: What rules must never be broken?
4. **Make tests algorithm-agnostic**: Could a different implementation pass?

**Remember**: Good tests survive refactoring. Bad tests require updates when internal implementation changes.
