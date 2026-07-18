"""Unit tests for debug-export scrubbing helpers and WS discovery dump.

Coverage focus is the privacy/safety surface: anything that could leak a
credential, MAC, or serial through the debug export. Plus the WS dump
itself, which closes the loop on issue #91 (wrong Nordpool area discovered
because BESS never saw the actual config-entry shape).
"""

from unittest.mock import MagicMock

from core.bess.debug_data_exporter import (
    _REDACTED,
    DebugDataAggregator,
    _is_secret_key,
    _redact_identifiers,
    _redact_secrets,
    _scrub_config_entry,
    _scrub_device,
)


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


class TestSerializeEntitySnapshot:
    """Regression coverage: the entity snapshot used to only walk
    METHOD_SENSOR_MAP (a curated subset for health-check display), missing
    entities read via other paths that are only registered in
    controller.sensors — e.g. per-slot TOU segment entities and Growatt VPP
    registers, both resolved via _get_entity_for_service/_resolve_entity_id,
    which look up controller.sensors directly, bypassing METHOD_SENSOR_MAP.
    Fixed by capturing controller.sensors directly instead. (controller.sensors
    itself is kept fresh by BESSController.refresh_active_sensors(), see #332
    — the exporter can rely on it without needing its own freshness plumbing.)
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
        controller.get_entity_state_raw.side_effect = lambda entity_id: {
            "entity_id": entity_id,
            "state": "42",
        }
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

        def fake_get(entity_id):
            if entity_id == "sensor.broken":
                raise RuntimeError("HA unreachable")
            return {"entity_id": entity_id, "state": "1"}

        controller.get_entity_state_raw.side_effect = fake_get
        agg = self._make_aggregator(controller)

        out = agg._serialize_entity_snapshot()

        assert out == {
            "sensor.battery_soc": {"entity_id": "sensor.battery_soc", "state": "1"}
        }
