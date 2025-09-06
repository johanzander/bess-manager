# BESS Manager Documentation

This directory contains comprehensive documentation for developers and contributors working on the BESS Manager project.

## Documentation Overview

### For Developers

- **[CLAUDE.md](../CLAUDE.md)** - Essential guide for Claude Code development including commands, architecture, and coding guidelines
- **[SOFTWARE_DESIGN.md](../SOFTWARE_DESIGN.md)** - Comprehensive software architecture and design documentation
- **[DEVELOPMENT.md](../DEVELOPMENT.md)** - Development environment setup and workflow guide
- **[TODO.md](../TODO.md)** - Prioritized list of improvements and future features

### For Users

- **[README.md](../README.md)** - Project overview, features, and quick start guide
- **[DEPLOYMENT.md](../DEPLOYMENT.md)** - Installation and deployment instructions for Home Assistant

## Quick Navigation

### Getting Started

1. **New Contributors**: Start with [DEVELOPMENT.md](../DEVELOPMENT.md) for environment setup
2. **Claude Code Users**: Read [CLAUDE.md](../CLAUDE.md) for development guidelines and commands
3. **Architecture Understanding**: Review [SOFTWARE_DESIGN.md](../SOFTWARE_DESIGN.md) for system design

### Development Workflow

1. Set up development environment following [DEVELOPMENT.md](../DEVELOPMENT.md)
2. Review coding guidelines in [CLAUDE.md](../CLAUDE.md)
3. Check [TODO.md](../TODO.md) for current priorities and improvements
4. Follow architectural patterns described in [SOFTWARE_DESIGN.md](../SOFTWARE_DESIGN.md)

### Code Quality Standards

- **Python**: Ruff, Black, Pylance compliance required
- **TypeScript**: Standard ESLint and Prettier formatting
- **Documentation**: Comprehensive docstrings and type annotations
- **Testing**: Unit and integration tests for all new features

## Architecture Quick Reference

### Core Components

- **BatterySystemManager**: Main coordinator and API facade
- **SensorCollector**: Energy data collection and validation from HA sensors
- **DynamicProgramming**: Optimization engine for battery scheduling
- **DailyViewBuilder**: Combines actual and predicted data for UI
- **HistoricalDataStore**: Immutable storage of actual energy events
- **ScheduleStore**: Versioned optimization results and schedules

### Key APIs

- `/api/dashboard` - Complete daily energy flow and savings data
- `/api/decision-intelligence` - Detailed optimization reasoning and analysis
- `/api/settings/*` - Battery and electricity price configuration
- `/api/growatt/*` - Inverter status and schedule management
- `/api/system-health` - Component health and sensor validation

### Data Flow

```text
Sensor Collection → Historical Storage → Optimization → Schedule Application → Hardware Control
        ↓                    ↓              ↓               ↓                     ↓
   Energy Validation → Daily View Builder → Decision Analysis → UI/API Response
```text

## Contributing Guidelines

### Before Contributing

1. Read the coding guidelines in [CLAUDE.md](../CLAUDE.md)
2. Understand the deterministic system principles (no hasattr, explicit failures)
3. Review the architectural patterns in [SOFTWARE_DESIGN.md](../SOFTWARE_DESIGN.md)
4. Check [TODO.md](../TODO.md) for current priorities

### Code Contribution Process

1. **Never remove or modify existing functionality** unless explicitly requested
2. **Extend existing components** rather than creating new parallel implementations
3. **Use explicit error handling** - no fallbacks or default values
4. **Follow existing patterns** for health checks, sensor access, and API responses
5. **Ensure all code passes** Ruff, Black, and Pylance validation

### Testing Requirements

- Unit tests for all new components with synthetic test data
- Integration tests for end-to-end workflows
- Real-world scenario testing with historical price data
- Performance validation for optimization algorithms

## Support and Resources

### Getting Help

- Review existing documentation in this directory
- Check [GitHub Issues](https://github.com/johanzander/bess-manager/issues) for known problems
- Follow development patterns established in the codebase

### Technical Resources

- **Home Assistant Integration**: Sensor configuration and device control patterns
- **Dynamic Programming**: Battery optimization algorithm implementation
- **React/TypeScript**: Frontend component patterns and state management
- **FastAPI**: Backend API design and error handling patterns

This documentation structure ensures that developers have clear guidance for working effectively with the BESS Manager codebase while maintaining code quality and architectural consistency.
