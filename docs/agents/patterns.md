# Code Patterns

Reference these patterns before writing any new code.

## Sensor Access

```python
# Good — use the controller method
soc_value = self.ha_controller.get_battery_soc()

# Bad — never extract entity IDs manually
sensor_info = self.ha_controller.METHOD_SENSOR_MAP["get_battery_soc"]
soc_sensor_key = sensor_info.get("entity_id")  # FORBIDDEN
```

## Adding a New Sensor

1. Add entry to `METHOD_SENSOR_MAP` in `ha_api_controller.py`
2. Add validation in the relevant `perform_health_check()` call
3. Update `APISystemHealth` in `api_dataclasses.py` if exposed via API
4. Add test in `core/bess/tests/unit/`

## Settings Updates

```python
# Good — use the dataclass update() method
self.settings.update(new_values_dict)

# Bad — never mutate settings fields directly
self.settings.battery_capacity = 10.0  # bypasses validation
```

## Exception Handling

```python
# Good — specific exception type
from core.bess.exceptions import PriceDataUnavailableError

try:
    prices = self.price_manager.get_prices()
except PriceDataUnavailableError:
    raise  # or handle specifically

# Bad — string matching on exception messages
try:
    prices = self.price_manager.get_prices()
except ValueError as e:
    if "No price data" in str(e):  # FORBIDDEN
        ...
```

## API Endpoint

```python
@router.get("/api/my-endpoint")
def my_endpoint() -> dict:
    raw = {
        "battery_soc": 80,
        "grid_import_power": 1200,
    }
    return convert_keys_to_camel_case(raw)  # always convert
```

## API Response Model

```python
# Good — use existing dataclasses from api_dataclasses.py
from backend.api_dataclasses import APIBatterySettings

def get_settings() -> APIBatterySettings:
    return APIBatterySettings.from_settings(self.settings)

# Bad — return raw dicts or create new ad-hoc models
return {"batteryCapacity": 10.0, "maxChargePower": 3000}  # use dataclass
```

## TypeScript Interface (Frontend)

Keep `frontend/src/types.ts` in sync with `backend/api_dataclasses.py`.
When adding a field to an API dataclass, add the corresponding field to the
TypeScript interface in the same PR.

## Anti-Patterns to Avoid

| Anti-Pattern | Correct Approach |
|-------------|------------------|
| `hasattr(obj, "field")` | Use `assert hasattr` or restructure |
| `getattr(obj, key, default)` | Access directly; crash on missing |
| Creating `SomethingManager2` | Extend `SomethingManager` |
| `Optional[X]` import | `X \| None` |
| New file `api_models.py` | Use `api_dataclasses.py` |
| Hardcoded `"sensor.battery_soc_..."` | `METHOD_SENSOR_MAP` lookup |
| `except Exception as e: log(e); pass` | Let it propagate |
| Adding a side effect to a method whose name doesn't cover it (e.g. a schedule-build call inside `_run_health_check()`) | Put the orchestration in the caller; the checked-thing's own method only does what its name says |
| New constructor parameter + default-fallback to route a shared dependency around an initialization-order problem (e.g. `def __init__(self, ..., tracker=None): self.tracker = tracker or Tracker()`) | Fix the ordering — construct/wire the single existing instance earlier, or expose it, instead of adding a second construction path |

### Worked examples: don't route around a problem instead of fixing it

These are concrete instances of `rules.md`'s Debugging Protocol self-review
step (Phase 2, step 8) — read that first. The point of putting real
incidents here is not to hand you a list of named patterns to match against;
the self-review *question* ("does this diff add a workaround next to the
problem, instead of fixing the problem?") is the actual rule. These two are
just what it caught this time — the next violation will have a different
shape, so re-ask the question, don't grep this list.

**Real incident (issue #399, caused by #394) — routing around a lifecycle
method by adding a second trigger.** A fix for "the dashboard stays stuck on
'initializing' after a transient sensor outage" was implemented by adding a
schedule-build retry directly inside `BatterySystemManager._run_health_check()`
— a method whose entire contract, by name, is "check health and report
results." `_run_health_check()` had a second, unrelated caller (`start()`,
during hardware startup) that never asked for a schedule-build side effect
and was actively harmed by getting one: it fired the process's first
hardware write before the startup sequence had read the inverter's actual
state, causing unconditional Growatt VPP register writes (flash wear) on
every restart. Self-review should have caught this: the new behavior didn't
fit `_run_health_check()`'s existing contract, so the fix needed a different
owner, not the convenient branch. The correct fix — what issue #399 shipped
— was to put the retry in the public `refresh_health_check()` wrapper
instead, the layer that actually owns "something outside asked for a fresh
check, react to what changed." `_run_health_check()` itself was restored to
doing only what its name says.

A violation like this is invisible to tests, because a test written against
the same method you just widened will happily assert the widened behavior
as if it were the contract — it only surfaces when a *different* caller of
that same method, elsewhere in the codebase, unexpectedly gets the
bolted-on side effect too. That's why this is a design-time and
review-time check, not a testing one.

**Real incident (issue #440) — routing around an ordering problem by adding
a second construction site.** The fix for "timezone silently falls back to
a hardcoded default when HA's `/api/config` is unreachable at startup" was
first drafted as: give `BatterySystemManager.__init__` a new
`runtime_failure_tracker: RuntimeFailureTracker | None = None` parameter,
construct a `RuntimeFailureTracker` earlier in `app.py` and pass it in,
falling back to `BatterySystemManager` constructing its own if none is
given. This looked reasonable — it "solved" the immediate problem (the
timezone fetch in `app.py` needed a wired `failure_tracker` before
`BatterySystemManager` itself had constructed one) — but it created two
possible construction sites for what should always be exactly one tracker
instance, with a fallback default that exists only to paper over the
ordering gap. Self-review should have caught this the same way as #399: the
proposed diff's only new piece (the fallback parameter) existed purely to
route around a timing problem, not to solve it. The actual root cause was
simpler — `app.py` called `get_ha_config()` for the timezone *before*
constructing `BatterySystemManager`, the single place that owns building
and wiring the `RuntimeFailureTracker`. The fix that shipped was to move the
timezone fetch to run *after* `BatterySystemManager` construction — no new
parameter, no second instance, no fallback.
