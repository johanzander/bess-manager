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
