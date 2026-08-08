"""Regression tests for perform_health_check()/determine_health_status()'s
handling of required-but-unmapped sensors (see TODO.md "Health check silently
skips genuinely-required-but-unmapped sensors")."""

from typing import ClassVar

from core.bess.health_check import determine_health_status, perform_health_check


class _FakeController:
    """Minimal stand-in for a real inverter/sensor controller."""

    METHOD_SENSOR_MAP: ClassVar[dict] = {}

    def __init__(
        self, method_status: dict[str, str], method_values: dict | None = None
    ):
        self._method_status = method_status
        self._method_values = method_values or {}

    def validate_methods_sensors(self, method_list: list) -> list:
        return [
            {
                "name": method,
                "method_name": method,
                "sensor_key": method,
                "entity_id": None,
                "status": self._method_status[method],
            }
            for method in method_list
        ]

    def get_battery_soc(self):
        return self._method_values.get("get_battery_soc", 50.0)

    def get_grid_power(self):
        return self._method_values.get("get_grid_power")

    def get_load_consumption_lifetime(self):
        return self._method_values.get("get_load_consumption_lifetime")


def test_determine_health_status_errors_on_required_sensor_marked_skipped():
    """One required sensor works and one required sensor is unmapped
    (SKIPPED). The unmapped one must not be silently excluded from the
    required-total count just because its status happens to be SKIPPED —
    otherwise the working sensor alone makes required_working==required_total
    and the missing required sensor goes unreported."""
    results = [
        {"method_name": "get_battery_soc", "status": "OK"},
        {"method_name": "get_grid_power", "status": "SKIPPED"},
    ]

    status = determine_health_status(
        results,
        working_sensors=1,
        required_methods=["get_battery_soc", "get_grid_power"],
    )

    assert status == "ERROR"


def test_perform_health_check_errors_when_required_sensor_is_unmapped():
    """perform_health_check(is_required=True, ...) must report ERROR, not OK,
    when one required sensor works but another required sensor is entirely
    unmapped (not_configured) and genuinely has no value to report."""
    controller = _FakeController(
        {"get_battery_soc": "ok", "get_grid_power": "not_configured"}
    )

    result = perform_health_check(
        component_name="Battery Monitoring",
        description="test",
        is_required=True,
        controller=controller,
        all_methods=["get_battery_soc", "get_grid_power"],
    )

    assert result["status"] == "ERROR"


def test_perform_health_check_ok_when_required_sensor_unmapped_but_derivable():
    """A required sensor whose primary mapping is not_configured can still
    succeed via an internal fallback (e.g. get_load_consumption_lifetime
    deriving from solar + grid sensors on platforms with no direct load
    register, such as solax_modbus_native or solis_modbus). The pre-check's
    "not_configured" verdict on the primary mapping must not short-circuit
    into a false ERROR when the method itself returns a real value."""
    controller = _FakeController(
        {"get_battery_soc": "ok", "get_load_consumption_lifetime": "not_configured"},
        method_values={"get_load_consumption_lifetime": 12.3},
    )

    result = perform_health_check(
        component_name="Energy Monitoring",
        description="test",
        is_required=True,
        controller=controller,
        all_methods=["get_battery_soc", "get_load_consumption_lifetime"],
    )

    assert result["status"] == "OK"


def test_perform_health_check_still_skips_unmapped_optional_sensor():
    """Optional (is_required=False) unmapped sensors keep reporting OK —
    only required sensors should escalate to ERROR."""
    controller = _FakeController({"get_battery_soc": "not_configured"})

    result = perform_health_check(
        component_name="Optional Component",
        description="test",
        is_required=False,
        controller=controller,
        all_methods=["get_battery_soc"],
    )

    assert result["status"] == "OK"


def test_perform_health_check_ok_when_required_sensor_configured_and_working():
    controller = _FakeController({"get_battery_soc": "ok"})

    result = perform_health_check(
        component_name="Battery Monitoring",
        description="test",
        is_required=True,
        controller=controller,
        all_methods=["get_battery_soc"],
    )

    assert result["status"] == "OK"
