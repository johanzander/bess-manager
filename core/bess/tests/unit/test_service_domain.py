"""Tests for the configurable vendor service domain (inverter.service_domain).

BESS makes service calls into two vendor integration domains: huawei_solar
(set_tou_periods) and growatt_server (TOU segment / AC charge-discharge
times). Every other service call infers its domain from the entity_id
prefix; these two target a *device*, so there's no prefix to read and the
domain was hardcoded. A compatible integration exposing the same services
under a different domain name (e.g. huawei_emma_management, see PR #412)
therefore could not be used without adding a whole new platform.

``inverter.service_domain`` overrides that domain per install. Empty means
"use the platform's standard domain".
"""

from unittest.mock import patch

import pytest

from core.bess.exceptions import SystemConfigurationError
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.settings_store import PLATFORM_SERVICE_DOMAIN, SettingsStore


class TestSettingsStoreResolution:
    """inverter.service_domain resolves against the configured platform."""

    def _store(self, inverter: dict) -> SettingsStore:
        store = SettingsStore()
        store.data = {"inverter": inverter}
        return store

    def test_empty_override_resolves_to_platform_default_for_huawei(self) -> None:
        store = self._store({"platform": "huawei_solar_luna2000", "service_domain": ""})
        assert store.get_service_domain() == "huawei_solar"

    def test_empty_override_resolves_to_platform_default_for_growatt_cloud(
        self,
    ) -> None:
        store = self._store({"platform": "growatt_server_min", "service_domain": ""})
        assert store.get_service_domain() == "growatt_server"

    def test_override_wins_over_platform_default(self) -> None:
        store = self._store(
            {
                "platform": "huawei_solar_luna2000",
                "service_domain": "huawei_emma_management",
            }
        )
        assert store.get_service_domain() == "huawei_emma_management"

    def test_missing_key_resolves_to_platform_default(self) -> None:
        """Existing installs predate the field — no migration should be needed."""
        store = self._store({"platform": "growatt_server_sph"})
        assert store.get_service_domain() == "growatt_server"

    def test_platform_without_vendor_service_calls_resolves_empty(self) -> None:
        """Modbus platforms drive entities directly — no vendor domain at all."""
        store = self._store({"platform": "solax_modbus_native"})
        assert store.get_service_domain() == ""

    def test_unconfigured_install_resolves_empty(self) -> None:
        store = self._store({"platform": "", "service_domain": ""})
        assert store.get_service_domain() == ""

    def test_every_valid_platform_has_a_mapping(self) -> None:
        """A new platform must declare its vendor domain (or "" explicitly),
        so adding one can't silently inherit another platform's domain."""
        from core.bess.settings_store import VALID_PLATFORMS

        assert set(PLATFORM_SERVICE_DOMAIN) == set(VALID_PLATFORMS)


class TestHuaweiTouWriteUsesConfiguredDomain:
    def _controller(self, service_domain: str) -> HomeAssistantAPIController:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            huawei_device_id="dev-123",
            service_domain=service_domain,
        )
        ctrl.test_mode = False
        return ctrl

    def test_write_tou_periods_targets_configured_domain(self) -> None:
        ctrl = self._controller("huawei_emma_management")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.write_huawei_tou_periods("06:00-08:00/1234567/+")
            path = mock_request.call_args[0][1]
            assert path == "/api/services/huawei_emma_management/set_tou_periods"

    def test_write_tou_periods_still_targets_huawei_solar_by_default(self) -> None:
        ctrl = self._controller("huawei_solar")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.write_huawei_tou_periods("06:00-08:00/1234567/+")
            path = mock_request.call_args[0][1]
            assert path == "/api/services/huawei_solar/set_tou_periods"


class TestGrowattCallsUseConfiguredDomain:
    def _controller(self, service_domain: str) -> HomeAssistantAPIController:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            growatt_device_id="growatt-1",
            service_domain=service_domain,
        )
        ctrl.test_mode = False
        return ctrl

    def test_update_time_segment_targets_configured_domain(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.set_inverter_time_segment(1, "battery_first", "02:00", "03:00", True)
            path = mock_request.call_args[0][1]
            assert path == "/api/services/my_growatt_bridge/update_time_segment"

    def test_read_time_segments_targets_configured_domain(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {"service_response": {"time_segments": []}}
            ctrl.read_inverter_time_segments()
            path = mock_request.call_args[0][1]
            assert path.startswith("/api/services/my_growatt_bridge/read_time_segments")

    def test_unreadable_segments_raise_instead_of_reporting_empty(self) -> None:
        """A failed read must not be indistinguishable from an empty inverter.

        GrowattMinController diffs its TOU plan against this return value to
        decide what to write. Reporting failure as [] made it read "the
        inverter holds no segments" and rewrite every one blind — the
        duplicate writes Growatt rejects with a 500 (issue #551).
        """
        ctrl = self._controller("my_growatt_bridge")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {"unexpected": "shape"}
            with pytest.raises(ValueError, match="Unexpected response format"):
                ctrl.read_inverter_time_segments()

    def test_empty_segment_list_is_returned_as_a_valid_answer(self) -> None:
        """An inverter with nothing programmed is a state, not an error."""
        ctrl = self._controller("my_growatt_bridge")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {"service_response": {"time_segments": []}}
            assert ctrl.read_inverter_time_segments() == []

    def test_ac_charge_times_target_configured_domain(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl.write_ac_charge_times("01:00", "05:00", True)
            path = mock_request.call_args[0][1]
            assert path == "/api/services/my_growatt_bridge/write_ac_charge_times"


class TestSafeReadAllowlistFollowsConfiguredDomain:
    """The read services must keep return_response=true under a custom domain.

    Without this, a compatible integration implementing read_time_segments
    correctly would still get no data back — a failure that looks like the
    integration's fault rather than a BESS configuration issue.
    """

    def _controller(self, service_domain: str) -> HomeAssistantAPIController:
        return HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            growatt_device_id="growatt-1",
            service_domain=service_domain,
        )

    def test_custom_domain_read_still_requests_return_response(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        ctrl.test_mode = False
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl._service_call_with_retry(
                "my_growatt_bridge", "read_time_segments", None, device_id="growatt-1"
            )
            path = mock_request.call_args[0][1]
            assert "return_response=true" in path

    def test_custom_domain_read_permitted_in_test_mode(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        ctrl.test_mode = True
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl._service_call_with_retry(
                "my_growatt_bridge", "read_time_segments", None, device_id="growatt-1"
            )
            assert mock_request.called, "safe read was blocked by test mode"

    def test_custom_domain_write_still_blocked_in_test_mode(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        ctrl.test_mode = True
        with patch.object(ctrl, "_api_request") as mock_request:
            ctrl._service_call_with_retry(
                "my_growatt_bridge", "update_time_segment", None, device_id="growatt-1"
            )
            assert not mock_request.called

    def test_custom_domain_write_tracked_as_inverter_control(self) -> None:
        ctrl = self._controller("my_growatt_bridge")
        ctrl.test_mode = False
        with patch.object(ctrl, "_api_request") as mock_request:
            mock_request.return_value = {}
            ctrl._service_call_with_retry(
                "my_growatt_bridge", "update_time_segment", None, device_id="growatt-1"
            )
            assert mock_request.call_args[1]["category"] == "inverter_control"


class TestUnconfiguredDomainError:
    def test_error_message_is_not_mangled_into_the_component_slot(self) -> None:
        """SystemConfigurationError's first positional arg is ``component``,
        which it interpolates as "Configuration error in <component>" —
        passing the sentence positionally produces a garbled message."""
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            huawei_device_id="dev-1",
            service_domain="",
        )
        with pytest.raises(SystemConfigurationError) as exc:
            ctrl.write_huawei_tou_periods("06:00-08:00/1234567/+")
        assert not str(exc.value).startswith("Configuration error in No ")
        assert "No inverter service domain configured" in str(exc.value)


def _settings_store(sensors: dict) -> SettingsStore:
    store = SettingsStore()
    store.data["sensors"] = dict(sensors)
    return store


class TestSensorConfiguredPredicate:
    def test_reports_configured_sensor(self) -> None:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            settings_store=_settings_store(
                {"huawei_working_mode": "select.working_mode"}
            ),
        )
        assert ctrl.is_sensor_configured("huawei_working_mode") is True

    def test_reports_unmapped_sensor(self) -> None:
        ctrl = HomeAssistantAPIController(ha_url="http://ha.local", token="tok")
        assert ctrl.is_sensor_configured("huawei_working_mode") is False

    def test_reports_blank_entity_as_unconfigured(self) -> None:
        ctrl = HomeAssistantAPIController(
            ha_url="http://ha.local",
            token="tok",
            settings_store=_settings_store({"huawei_working_mode": ""}),
        )
        assert ctrl.is_sensor_configured("huawei_working_mode") is False


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("huawei_solar_luna2000", "huawei_solar"),
        ("growatt_server_min", "growatt_server"),
        ("growatt_server_sph", "growatt_server"),
        ("solax_modbus_native", ""),
        ("solax_modbus_growatt_min", ""),
        ("solax_modbus_growatt_sph", ""),
        ("solis_modbus", ""),
    ],
)
def test_platform_service_domain_map(platform: str, expected: str) -> None:
    assert PLATFORM_SERVICE_DOMAIN[platform] == expected
