"""Register write ordering for Growatt VPP periods (issue #593).

On Growatt VPP there is no separate trigger/commit register: enabling
``growatt_vpp_remote_control`` (30407) *is* the commit. So the power value
(30409) and the fallback timer (30408) must both be in place before remote
control is enabled, or the inverter arms against whatever the previous
active period left behind -- up to +/-100%, i.e. a full-rated spike on
every mode switch.

Why these assert on the service calls rather than on an outcome: this is a
write-sequencing defect, and no execution model covers write order.
``simulation/vpp_simulator.py`` derives one ``VppCommand`` per period and
models the resulting energy, so it cannot observe that two writes reached
the inverter in the wrong order -- by construction it sees the committed
pair. The ordering is only visible at the service-call layer, which is why
these live here and not as a plan-faithfulness scenario. No plan economics
change, so nothing in the DP/intent path moves.
"""

from unittest.mock import patch

import pytest

from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.settings_store import SettingsStore

_SENSORS = {
    "growatt_vpp_remote_control": "select.growatt_vpp_remote_control",
    "growatt_vpp_power": "number.growatt_vpp_power",
    "growatt_vpp_time": "number.growatt_vpp_time",
}


def _controller(sensors: dict | None = None) -> HomeAssistantAPIController:
    store = SettingsStore()
    store.data["sensors"] = dict(_SENSORS if sensors is None else sensors)
    ctrl = HomeAssistantAPIController(
        ha_url="http://ha.local", token="tok", settings_store=store
    )
    ctrl.test_mode = False
    return ctrl


def _writes(mock_request) -> list[tuple[str, str, object]]:
    """Reduce recorded _api_request calls to (path, entity_id, value)."""
    recorded = []
    for args, kwargs in mock_request.call_args_list:
        payload = kwargs["json"]
        recorded.append(
            (args[1], payload["entity_id"], payload.get("option", payload.get("value")))
        )
    return recorded


class TestActivationOrdering:
    """Arming (30407 -> Enabled) must come last, after power and timer."""

    def test_power_and_timer_are_written_before_remote_control_is_enabled(self) -> None:
        ctrl = _controller()
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.set_growatt_vpp_period(
                remote_control_enabled=True, power_pct=-40, fallback_minutes=30
            )

        assert _writes(mock_request) == [
            ("/api/services/number/set_value", "number.growatt_vpp_power", -40),
            ("/api/services/number/set_value", "number.growatt_vpp_time", 30),
            (
                "/api/services/select/select_option",
                "select.growatt_vpp_remote_control",
                "Enabled",
            ),
        ]

    def test_power_write_failure_leaves_remote_control_unarmed(self) -> None:
        """A failed power write must not leave the inverter executing a stale
        command. Arming last makes the failure degrade to load_first self-use.
        """
        ctrl = _controller()

        def _fail_only_the_power_write(*args, **kwargs):
            if kwargs["json"]["entity_id"] == "number.growatt_vpp_power":
                raise RuntimeError("HA unreachable")
            return {}

        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.side_effect = _fail_only_the_power_write
            with pytest.raises(RuntimeError):
                ctrl.set_growatt_vpp_period(
                    remote_control_enabled=True, power_pct=-100, fallback_minutes=30
                )

        armed = [
            w
            for w in _writes(mock_request)
            if w[1] == "select.growatt_vpp_remote_control" and w[2] == "Enabled"
        ]
        assert armed == []

    def test_missing_power_entity_raises_before_anything_is_written(self) -> None:
        """An unconfigured power entity must abort before the arming write.

        A mis-provisioned install must not arm the inverter and *then* throw,
        which would leave it on the previous period's power value until the
        next period retry.
        """
        sensors = dict(_SENSORS)
        del sensors["growatt_vpp_power"]
        ctrl = _controller(sensors)
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            with pytest.raises(ValueError):
                ctrl.set_growatt_vpp_period(
                    remote_control_enabled=True, power_pct=50, fallback_minutes=30
                )

        assert _writes(mock_request) == []


class TestReleaseOrdering:
    """Release (30407 -> Disabled) must come first, then power is zeroed."""

    def test_remote_control_is_disabled_before_power_is_zeroed(self) -> None:
        """Zeroing clears the latch for the next activation.

        Order matters the other way round here: a 0 written while remote
        control is still Enabled selects the documented grid_first hold, so
        it would change release behaviour on every load_first entry.
        Disabling first keeps release identical to today.
        """
        ctrl = _controller()
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.set_growatt_vpp_period(
                remote_control_enabled=False, power_pct=0, fallback_minutes=30
            )

        assert _writes(mock_request) == [
            (
                "/api/services/select/select_option",
                "select.growatt_vpp_remote_control",
                "Disabled",
            ),
            ("/api/services/number/set_value", "number.growatt_vpp_power", 0),
        ]

    def test_missing_power_entity_still_disables_remote_control(self) -> None:
        """Release must never be blocked by the power entity.

        Zeroing the latch is a courtesy to the *next* activation; getting the
        inverter back to load_first is the safety-critical part. So an
        unconfigured power entity must not stop the disable from landing --
        the failure has to come after it, not instead of it.
        """
        sensors = dict(_SENSORS)
        del sensors["growatt_vpp_power"]
        ctrl = _controller(sensors)
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            with pytest.raises(ValueError):
                ctrl.set_growatt_vpp_period(
                    remote_control_enabled=False, power_pct=0, fallback_minutes=30
                )

        assert _writes(mock_request) == [
            (
                "/api/services/select/select_option",
                "select.growatt_vpp_remote_control",
                "Disabled",
            ),
        ]

    def test_release_does_not_rewrite_the_fallback_timer(self) -> None:
        """Nothing is armed after release, so there is no timer to refresh."""
        ctrl = _controller()
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.set_growatt_vpp_period(
                remote_control_enabled=False, power_pct=0, fallback_minutes=30
            )

        assert not [
            w for w in _writes(mock_request) if w[1] == "number.growatt_vpp_time"
        ]
