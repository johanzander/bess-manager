"""Unit tests for debug-export scrubbing helpers and WS discovery dump.

Coverage focus is the privacy/safety surface: anything that could leak a
credential, MAC, or serial through the debug export. Plus the WS dump
itself, which closes the loop on issue #91 (wrong Nordpool area discovered
because BESS never saw the actual config-entry shape).
"""

import logging
from datetime import timedelta
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.bess import time_utils
from core.bess.daily_view_builder import DailyView
from core.bess.debug_data_exporter import (
    _LOG_KEY_PATTERNS,
    _REDACTED,
    DebugDataAggregator,
    _is_secret_key,
    _redact_identifiers,
    _redact_secrets,
    _scrub_config_entry,
    _scrub_device,
)
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.models import EnergyData, PeriodData
from core.bess.settings import BatterySettings
from core.bess.settings_store import SettingsStore


class TestCompactLogRetainsEveryHardwareWrite:
    """#886: every write BESS sends to the inverter must survive compact-log
    trimming, whatever platform issued it. #717 kept writes by listing each
    platform's wording in the filter, and the Growatt VPP, SolaX VPP and
    export-limit writes were never added -- so a compact bundle could not show
    what BESS commanded on those platforms. These tests drive the real write
    methods and check the compacted log, so a new write path is covered without
    anyone editing the filter."""

    SENSORS: ClassVar[dict[str, str]] = {
        "growatt_vpp_remote_control": "select.vpp_remote_control",
        "growatt_vpp_power": "number.vpp_power",
        "growatt_vpp_time": "number.vpp_time",
        "growatt_vpp_status": "select.vpp_status",
        "growatt_vpp_allow_ac_charging": "select.vpp_allow_ac_charging",
        "solax_power_control_mode": "select.solax_power_control",
        "solax_active_power": "number.solax_active_power",
        "solax_autorepeat_duration": "number.solax_autorepeat",
        "solax_power_control_trigger": "button.solax_trigger",
        "growatt_export_limit_mode": "select.export_limit_mode",
        "growatt_export_limit_value": "number.export_limit_value",
        "grid_charge": "switch.grid_charge",
    }

    @pytest.fixture
    def ctrl(self) -> HomeAssistantAPIController:
        store = SettingsStore()
        store.data["sensors"] = dict(self.SENSORS)
        c = HomeAssistantAPIController(
            ha_url="http://ha.local:8123",
            token="test-token",
            settings_store=store,
            service_domain="solax_modbus",
        )
        c.max_attempts = 1
        c.retry_base_delay = 0
        return c

    @staticmethod
    def _kept(caplog: pytest.LogCaptureFixture) -> list[str]:
        """The captured log lines, formatted as the app writes them, that the
        compact export keeps."""
        lines = [
            f"2026-11-10 23:37:01 | {r.levelname: <5} | {r.name} - {r.getMessage()}"
            for r in caplog.records
        ]
        return [line for line in lines if _LOG_KEY_PATTERNS.search(line)]

    def _assert_writes_kept(
        self,
        ctrl: HomeAssistantAPIController,
        caplog: pytest.LogCaptureFixture,
        expected: list[tuple[str, str]],
    ) -> None:
        kept = self._kept(caplog)
        for entity_id, value in expected:
            assert any(
                entity_id in line and value in line for line in kept
            ), f"write {entity_id}={value} missing from compact log:\n" + "\n".join(
                kept
            )

    def test_growatt_vpp_period_writes_are_kept(
        self, ctrl: HomeAssistantAPIController, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(ctrl, "_api_request", return_value=None),
            caplog.at_level(logging.INFO),
        ):
            ctrl.set_growatt_vpp_period(True, 100, 20)
            ctrl.set_growatt_vpp_period(False, 0, 20)
            ctrl.set_growatt_vpp_status(True)
            ctrl.set_growatt_vpp_allow_ac_charging(True)
        self._assert_writes_kept(
            ctrl,
            caplog,
            [
                ("number.vpp_power", "100"),
                ("number.vpp_time", "20"),
                ("select.vpp_remote_control", "Enabled"),
                ("select.vpp_remote_control", "Disabled"),
                ("number.vpp_power", "0"),
                ("select.vpp_status", "Enabled"),
                ("select.vpp_allow_ac_charging", "Enabled"),
            ],
        )

    def test_solax_vpp_writes_are_kept(
        self, ctrl: HomeAssistantAPIController, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(ctrl, "_api_request", return_value=None),
            caplog.at_level(logging.INFO),
        ):
            ctrl.set_solax_active_power_control(-2500)
            ctrl.set_solax_vpp_disabled()
        self._assert_writes_kept(
            ctrl,
            caplog,
            [
                ("select.solax_power_control", "Enabled Battery Control"),
                ("number.solax_active_power", "-2500"),
                ("button.solax_trigger", "press"),
                ("select.solax_power_control", "Disabled"),
            ],
        )

    def test_export_limit_and_grid_charge_writes_are_kept(
        self, ctrl: HomeAssistantAPIController, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(ctrl, "_api_request", return_value=None),
            caplog.at_level(logging.INFO),
        ):
            ctrl.set_growatt_export_limit(True)
            ctrl.set_grid_charge(True)
        self._assert_writes_kept(
            ctrl,
            caplog,
            [
                ("select.export_limit_mode", "Meter 1"),
                ("number.export_limit_value", "0"),
                ("switch.grid_charge", "turn_on"),
            ],
        )

    def test_reads_failures_and_test_mode_log_no_write(
        self, ctrl: HomeAssistantAPIController, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only a write that reached the inverter is recorded as one."""
        with caplog.at_level(logging.INFO):
            with patch.object(ctrl, "_api_request", return_value={"x": 1}):
                ctrl._service_call_with_retry(
                    "nordpool", "get_prices_for_date", config_entry="abc"
                )
            with (
                patch.object(
                    ctrl, "_api_request", side_effect=requests.ConnectionError()
                ),
                pytest.raises(requests.ConnectionError),
            ):
                ctrl.set_growatt_vpp_status(True)
            ctrl.test_mode = True
            ctrl.set_growatt_vpp_allow_ac_charging(True)
        assert not [r for r in caplog.records if "HARDWARE:" in r.getMessage()]


class TestIsSecretKey:
    def test_password_variants_match(self):
        for k in ["password", "Password", "old_password", "PASSWORD_HASH"]:
            assert _is_secret_key(k), k

    def test_token_variants_match(self):
        for k in [
            "api_key",
            "apiKey",
            "access_token",
            "refresh_token",
            "Authorization",
        ]:
            assert _is_secret_key(k), k

    def test_secret_substring_match(self):
        assert _is_secret_key("client_secret")
        assert _is_secret_key("MY_SECRET")

    def test_innocuous_keys_pass(self):
        for k in ["area", "areas", "currency", "name", "title", "state"]:
            assert not _is_secret_key(k), k


class TestRedactSecrets:
    def test_top_level_secret_redacted(self):
        out = _redact_secrets({"area": "SE3", "api_key": "abc123"})
        assert out == {"area": "SE3", "api_key": _REDACTED}

    def test_nested_secret_redacted(self):
        inp = {"outer": {"inner": {"access_token": "xyz", "name": "ok"}}}
        out = _redact_secrets(inp)
        assert out == {"outer": {"inner": {"access_token": _REDACTED, "name": "ok"}}}

    def test_secret_inside_list_redacted(self):
        inp = {"items": [{"api_key": "x"}, {"name": "ok"}]}
        out = _redact_secrets(inp)
        assert out["items"][0] == {"api_key": _REDACTED}
        assert out["items"][1] == {"name": "ok"}

    def test_non_dict_passthrough(self):
        assert _redact_secrets("plain") == "plain"
        assert _redact_secrets(42) == 42
        assert _redact_secrets(None) is None


class TestSerializeAddonOptions:
    """Settings go through the same redaction pass as the export's other
    sections, with InfluxDB's two fields still stripped by name.
    """

    def _serialize(self, settings: dict) -> dict:
        aggregator = DebugDataAggregator(MagicMock(), settings_data=settings)
        return aggregator._serialize_addon_options()

    def test_secret_named_value_is_redacted(self):
        out = self._serialize(
            {"some_section": {"api_key": "value-here", "enabled": True}}
        )
        assert out["some_section"]["api_key"] == _REDACTED
        assert out["some_section"]["enabled"] is True

    def test_influxdb_credentials_still_stripped_url_kept(self):
        out = self._serialize(
            {
                "influxdb": {
                    "url": "http://homeassistant.local:8086",
                    "username": "u",
                    "password": "p",
                }
            }
        )
        assert out["influxdb"] == {"url": "http://homeassistant.local:8086"}

    def test_non_secret_settings_survive_unchanged(self):
        settings = {
            "sensors": {"shared": {"current_l1": "sensor.l1"}},
            "home": {"max_fuse_current": 20},
        }
        assert self._serialize(settings) == settings

    def test_caller_settings_not_mutated(self):
        settings = {"some_section": {"api_key": "value-here"}}
        self._serialize(settings)
        assert settings["some_section"]["api_key"] == "value-here"


class TestRedactIdentifiers:
    def test_serial_reduced_to_last_four(self):
        out = _redact_identifiers([["growatt_server", "ABCDE12345"]])
        assert out == [["growatt_server", "***2345"]]

    def test_short_value_fully_masked(self):
        out = _redact_identifiers([["x", "ab"]])
        assert out == [["x", "***"]]

    def test_non_list_input_returns_empty(self):
        assert _redact_identifiers(None) == []
        assert _redact_identifiers("ABCDE12345") == []

    def test_malformed_pair_skipped(self):
        out = _redact_identifiers([["only-one"], ["a", "b", "c"], ["ok", "1234567"]])
        assert out == [["ok", "***4567"]]


class TestScrubConfigEntry:
    def test_nordpool_keeps_area_and_areas(self):
        entry = {
            "entry_id": "01ABCDEF",
            "domain": "nordpool",
            "title": "Nordpool",
            "state": "loaded",
            "version": 1,
            "data": {"areas": ["SE3"], "currency": "SEK"},
            "options": {"area": "SE3"},
        }
        out = _scrub_config_entry(entry)
        assert out["entry_id"] == "01ABCDEF"
        assert out["data"] == {"areas": ["SE3"], "currency": "SEK"}
        assert out["options"] == {"area": "SE3"}

    def test_nordpool_drops_unknown_data_keys(self):
        entry = {
            "domain": "nordpool",
            "data": {"areas": ["SE3"], "internal_uuid": "leak-me"},
            "options": {},
        }
        out = _scrub_config_entry(entry)
        assert "internal_uuid" not in out["data"]
        assert out["data"] == {"areas": ["SE3"]}

    def test_unknown_domain_data_dropped_to_summary(self):
        entry = {
            "domain": "octopus_energy",
            "data": {"api_key": "secret", "account_id": "A-123", "email": "x@y.z"},
            "options": {"poll_interval": 30},
        }
        out = _scrub_config_entry(entry)
        assert "api_key" not in str(out["data"])
        assert "<filtered>" in out["data"]
        assert "<filtered>" in out["options"]

    def test_secret_key_under_allowlisted_domain_still_redacted(self):
        # Defence-in-depth: even if a secret-named key sneaks through the
        # allowlist (e.g. via a future allowlist edit), the value must be
        # redacted by the secondary key-name pass.
        entry = {
            "domain": "nordpool",
            "data": {"area": "SE3", "name": {"api_key": "leak"}},
            "options": {},
        }
        out = _scrub_config_entry(entry)
        assert out["data"]["name"] == {"api_key": _REDACTED}


class TestScrubDevice:
    def test_keeps_basic_fields_and_redacts_identifiers(self):
        device = {
            "id": "dev123",
            "name": "Inverter",
            "manufacturer": "Growatt",
            "model": "MIN 6000",
            "identifiers": [["growatt_server", "SN1234567890"]],
            "config_entries": ["leak-me"],
            "via_device_id": "leak-me",
        }
        out = _scrub_device(device)
        assert out == {
            "id": "dev123",
            "name": "Inverter",
            "manufacturer": "Growatt",
            "model": "MIN 6000",
            "identifiers": [["growatt_server", "***7890"]],
        }


class TestSerializeHaWsDiscovery:
    def _make_aggregator(self, controller):
        agg = DebugDataAggregator.__new__(DebugDataAggregator)
        agg.system = MagicMock()
        agg.system._controller = controller
        return agg

    def test_no_controller_returns_error(self):
        agg = self._make_aggregator(None)
        out = agg._serialize_ha_ws_discovery()
        assert out == {"error": "controller not initialized"}

    def test_ws_query_exception_captured(self):
        controller = MagicMock()
        controller._ws_query.side_effect = RuntimeError("auth failed")
        agg = self._make_aggregator(controller)
        out = agg._serialize_ha_ws_discovery()
        assert "WS query failed" in out["error"]

    def test_filters_to_target_domains(self):
        controller = MagicMock()
        controller._ws_query.return_value = [
            [
                {
                    "domain": "nordpool",
                    "entry_id": "n1",
                    "state": "loaded",
                    "data": {"areas": ["SE3"]},
                    "options": {},
                },
                {  # unrelated domain — must be dropped
                    "domain": "spotify",
                    "entry_id": "s1",
                    "data": {"refresh_token": "leak"},
                },
                {
                    "domain": "growatt_server",
                    "entry_id": "g1",
                    "state": "loaded",
                    "data": {},
                    "options": {},
                },
            ],
            [],
            {},
        ]
        controller.discover_ha_metadata.return_value = {
            "nordpool_area": "SE3",
            "nordpool_config_entry_id": "n1",
        }
        agg = self._make_aggregator(controller)

        out = agg._serialize_ha_ws_discovery()

        domains = [e["domain"] for e in out["config_entries"]]
        assert "spotify" not in domains
        assert sorted(domains) == ["growatt_server", "nordpool"]
        assert out["resolved"]["nordpool_area"] == "SE3"

    def test_growatt_devices_filtered_by_identifier(self):
        controller = MagicMock()
        controller._ws_query.return_value = [
            [],
            [
                {
                    "id": "d1",
                    "name": "Inverter",
                    "identifiers": [["growatt_server", "SN1234567890"]],
                },
                {
                    "id": "d2",
                    "name": "Other",
                    "identifiers": [["zigbee", "0x00"]],
                },
            ],
            {},
        ]
        controller.discover_ha_metadata.return_value = {}
        agg = self._make_aggregator(controller)

        out = agg._serialize_ha_ws_discovery()

        assert len(out["devices"]) == 1
        assert out["devices"][0]["id"] == "d1"
        assert out["devices"][0]["identifiers"] == [["growatt_server", "***7890"]]

    def test_services_dump_only_target_domains_keys(self):
        controller = MagicMock()
        controller._ws_query.return_value = [
            [],
            [],
            {
                "growatt_server": {"update_time_segment": {}, "read_time_segments": {}},
                "nordpool": {"get_prices_for_date": {}},
                "weather": {"get_forecast": {}},
            },
        ]
        controller.discover_ha_metadata.return_value = {}
        agg = self._make_aggregator(controller)

        out = agg._serialize_ha_ws_discovery()

        assert set(out["services"].keys()) == {"growatt_server", "nordpool"}
        assert out["services"]["growatt_server"] == [
            "read_time_segments",
            "update_time_segment",
        ]


def _make_energy() -> EnergyData:
    return EnergyData(
        solar_production=0.0,
        home_consumption=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )


class TestSerializeBatterySettings:
    def _make_aggregator(self, battery_settings, export_curtailment_active):
        agg = DebugDataAggregator.__new__(DebugDataAggregator)
        agg.system = MagicMock()
        agg.system.battery_settings = battery_settings
        agg.system.export_curtailment_active = export_curtailment_active
        return agg

    def test_includes_resolved_export_curtailment_active(self):
        # enabled=True but the platform can't curtail: the exported dict must
        # carry the resolved flag so from_debug_log.py doesn't have to guess
        # it from the enabled bit.
        settings = BatterySettings(export_curtailment_enabled=True)
        agg = self._make_aggregator(settings, export_curtailment_active=False)
        out = agg._serialize_battery_settings()
        assert out["export_curtailment_enabled"] is True
        assert out["export_curtailment_active"] is False

    def test_active_true_when_enabled_and_supported(self):
        settings = BatterySettings(export_curtailment_enabled=True)
        agg = self._make_aggregator(settings, export_curtailment_active=True)
        out = agg._serialize_battery_settings()
        assert out["export_curtailment_active"] is True


class TestSerializePreviousDays:
    def _make_aggregator(self, daily_view_store):
        agg = DebugDataAggregator.__new__(DebugDataAggregator)
        agg.system = MagicMock()
        agg.system.daily_view_store = daily_view_store
        return agg

    def test_includes_yesterdays_persisted_view(self):
        yesterday = time_utils.today() - timedelta(days=1)
        view = DailyView(
            date=yesterday,
            periods=[PeriodData(period=0, energy=_make_energy())],
            total_savings=12.5,
            actual_count=1,
            predicted_count=0,
        )
        store = MagicMock()
        store.load_day.side_effect = lambda day: view if day == yesterday else None
        agg = self._make_aggregator(store)

        out = agg._serialize_previous_days()

        assert len(out) == 1
        assert out[0]["date"] == yesterday
        assert out[0]["total_savings"] == 12.5

    def test_no_persisted_views_returns_empty_list(self):
        store = MagicMock()
        store.load_day.return_value = None
        agg = self._make_aggregator(store)

        assert agg._serialize_previous_days() == []

    def test_store_exception_returns_empty_list(self):
        store = MagicMock()
        store.load_day.side_effect = RuntimeError("disk error")
        agg = self._make_aggregator(store)

        assert agg._serialize_previous_days() == []


class TestSerializeEntitySnapshot:
    """Regression coverage: the entity snapshot used to only walk
    METHOD_SENSOR_MAP (a curated subset for health-check display), missing
    entities read via other paths that are only registered in
    controller.sensors — e.g. per-slot TOU segment entities and Growatt VPP
    registers, both resolved via _get_entity_for_service/_resolve_entity_id,
    which look up controller.sensors directly, bypassing METHOD_SENSOR_MAP.
    Fixed by capturing controller.sensors directly instead. (controller.sensors
    is a live SettingsStore view, see #334 — the exporter can rely on it
    without needing its own freshness plumbing.)
    """

    def _make_aggregator(self, controller):
        agg = DebugDataAggregator.__new__(DebugDataAggregator)
        agg.system = MagicMock()
        agg.system._controller = controller
        agg.system._energy_provider_config = {"provider": "nordpool_official"}
        return agg

    def test_no_controller_returns_empty(self):
        agg = self._make_aggregator(None)
        assert agg._serialize_entity_snapshot() == {}

    def test_captures_every_entity_in_controller_sensors(self):
        controller = MagicMock()
        controller.sensors = {
            "battery_soc": "sensor.battery_soc",
            # TOU segment sub-entity — not in METHOD_SENSOR_MAP, only ever
            # resolved via _get_entity_for_service("tou_time_3_end").
            "tou_time_3_end": "select.pv_growatt_time_3_end",
            # Growatt VPP register — same gap, resolved via _get_raw_state.
            "growatt_vpp_status": "select.pv_growatt_vpp_status",
        }
        controller.get_entity_state_raw.side_effect = (
            lambda entity_id, optional=False: {
                "entity_id": entity_id,
                "state": "42",
            }
        )
        agg = self._make_aggregator(controller)

        out = agg._serialize_entity_snapshot()

        assert set(out.keys()) == {
            "sensor.battery_soc",
            "select.pv_growatt_time_3_end",
            "select.pv_growatt_vpp_status",
        }

    def test_fetch_failure_for_one_entity_does_not_drop_others(self):
        controller = MagicMock()
        controller.sensors = {
            "battery_soc": "sensor.battery_soc",
            "broken": "sensor.broken",
        }

        def fake_get(entity_id: str, optional: bool = False) -> dict:
            if entity_id == "sensor.broken":
                raise RuntimeError("HA unreachable")
            return {"entity_id": entity_id, "state": "1"}

        controller.get_entity_state_raw.side_effect = fake_get
        agg = self._make_aggregator(controller)

        out = agg._serialize_entity_snapshot()

        assert out == {
            "sensor.battery_soc": {"entity_id": "sensor.battery_soc", "state": "1"}
        }

    def test_entities_without_ha_state_are_summarised_not_logged_one_by_one(
        self, caplog: Any
    ) -> None:
        """#863: a persisted sensor map can reference user-disabled registry
        entries (no state in HA). Each used to log an ERROR plus a warning;
        now they are probed as optional and reported in one line."""
        import logging

        import requests

        controller = MagicMock()
        controller.sensors = {
            "battery_soc": "sensor.battery_soc",
            "tou_time_8_update": "button.inv_time_8_update",
            "tou_time_9_update": "button.inv_time_9_update",
        }

        def fake_get(entity_id: str, optional: bool = False) -> dict:
            if "time_" in entity_id:
                assert optional, "missing-entity probe must be optional"
                resp = MagicMock()
                resp.status_code = 404
                raise requests.HTTPError(response=resp)
            return {"entity_id": entity_id, "state": "1"}

        controller.get_entity_state_raw.side_effect = fake_get
        agg = self._make_aggregator(controller)

        with caplog.at_level(logging.WARNING):
            out = agg._serialize_entity_snapshot()

        assert set(out) == {"sensor.battery_soc"}
        warnings = [r.getMessage() for r in caplog.records]
        assert not any("Failed to fetch entity" in m for m in warnings)
        summary = [m for m in warnings if "no state in HA" in m]
        assert len(summary) == 1
        assert "button.inv_time_8_update" in summary[0]
        assert "button.inv_time_9_update" in summary[0]


class TestSerializeConsumptionOverlay:
    """#863: the bundle must say why the declared-vs-measured comparison is
    missing rather than omit it, and must never break the rest of the export."""

    def _agg(self, system: Any) -> Any:
        agg = DebugDataAggregator.__new__(DebugDataAggregator)
        agg.system = system
        return agg

    def test_returns_manager_view(self) -> None:
        system = MagicMock()
        system.get_consumption_overlay_for_debug_export.return_value = {
            "configured": True,
            "blocks": [],
            "managed_load_sensors": [],
            "hourly": [],
        }
        assert self._agg(system)._serialize_consumption_overlay()["configured"]

    def test_failure_is_reported_in_the_section(self) -> None:
        system = MagicMock()
        system.get_consumption_overlay_for_debug_export.side_effect = RuntimeError(
            "recorder down"
        )
        assert self._agg(system)._serialize_consumption_overlay() == {
            "error": "recorder down"
        }

    def test_manager_reports_unconfigured_overlay(self) -> None:
        from core.bess.battery_system_manager import BatterySystemManager

        fake = MagicMock()
        fake._controller.sensors = {}
        assert BatterySystemManager.get_consumption_overlay_for_debug_export(fake) == {
            "configured": False
        }


class TestFormatConsumptionOverlay:
    def _fmt(self, overlay: Any) -> str:
        from core.bess.debug_report_formatter import DebugReportFormatter

        export = MagicMock()
        export.consumption_overlay = overlay
        return DebugReportFormatter()._format_consumption_overlay(export)

    def test_table_rows(self) -> None:
        out = self._fmt(
            {
                "configured": True,
                "blocks": [
                    {"start": "s", "end": "e", "energy_kwh": 2.0, "mode": "add"}
                ],
                "managed_load_sensors": ["sensor.ev"],
                "hourly": [
                    {"hour": "H1", "declared_kwh": 1.0, "measured_kwh": 0.75},
                    {"hour": "H2", "declared_kwh": 1.0, "measured_kwh": None},
                ],
            }
        )
        assert "| H1 | 1.00 | 0.75 |" in out
        assert "| H2 | 1.00 | — |" in out

    def test_error_and_unconfigured_are_explicit(self) -> None:
        assert "Unavailable: boom" in self._fmt({"error": "boom"})
        assert "No planned consumption entity configured" in self._fmt(
            {"configured": False}
        )
