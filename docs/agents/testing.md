# Testing Guidelines

## The Core Rule

**Test behavior (what the system does), not implementation (how it does it).**

A test that breaks when you swap two equivalent algorithms is a bad test.
A test that passes after the swap — because the observable outcome is the same — is a good test.

## What to Test

### Business behavior

```python
# Good: test what users care about
def test_high_price_hour_triggers_discharge():
    strategic_intents[20] = "EXPORT_ARBITRAGE"
    scheduler.apply_schedule(strategic_intents)
    assert scheduler.is_hour_configured_for_export(20)
```

### Hardware constraints

```python
# Good: these rules must never break regardless of algorithm
assert scheduler.has_no_overlapping_intervals()
assert scheduler.intervals_are_chronologically_ordered()
```

### Integration outcomes

```python
# Good: end-to-end cost savings are positive given favorable prices
result = optimizer.run(prices=high_spread_prices, initial_soc=0.2)
assert result.total_savings > 0
```

## What NOT to Test

```python
# Bad: tests internal data structures
strategic_segments = [i for i in intervals if i.get("period_type") == "strategic"]
assert len(strategic_segments) == 1  # breaks when field is renamed

# Bad: tests algorithm-specific slot boundaries
assert slot_start_times == ["02:40", "05:20"]  # breaks when algorithm changes

# Bad: tests exact counts that are implementation-specific
assert len(intervals) == 9  # "9 fixed slots" — changes with algorithm
```

## Test Data

JSON scenario fixtures live in `core/bess/tests/unit/data/`.
Add new scenarios there rather than constructing complex objects inline.

Name scenarios descriptively: `high_solar_export.json`, `ev_charging_overnight.json`.

## Red Flags

A test has implementation coupling if:

- It checks specific internal field names (`period_type`, `segment_id`)
- It checks exact internal boundaries (`02:40–05:19`)
- It checks algorithm-specific counts (`len(intervals) == 9`)
- Its docstring mentions the implementation (`"Fixed slots approach"`)
- A comment says `"specific to current algorithm"`

## Running Tests

```bash
pytest                              # all tests
pytest core/bess/tests/unit/        # unit tests only (fast, no HA required)
pytest core/bess/tests/integration/ # integration tests
pytest --cov=core.bess              # with coverage
```

Tests must pass before any PR is merged. The issue fixer runs `pytest` after
making changes and will attempt to fix failures before opening a PR.
