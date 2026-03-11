"""Tests for improved runtime failure diagnostics.

Verifies that TOU segment failures include descriptive operation strings,
HTTP response bodies, and service call context in failure records.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.runtime_failure_tracker import RuntimeFailureTracker


@pytest.fixture
def controller_with_tracker():
    """Create a controller with failure tracker and minimal retries."""
    controller = HomeAssistantAPIController.__new__(HomeAssistantAPIController)
    controller.base_url = "http://test:8123"
    controller.token = "test-token"
    controller.session = MagicMock()
    controller.max_attempts = 1
    controller.retry_base_delay = 0
    controller.test_mode = False
    controller.failure_tracker = RuntimeFailureTracker()
    controller.growatt_device_id = "test_device_123"
    # run_request accesses http_method.__name__ for logging
    controller.session.post.__name__ = "post"
    controller.session.get.__name__ = "get"
    return controller


class TestTOUSegmentOperationDescription:
    """Verify that TOU segment write failures include descriptive operation strings."""

    def test_set_inverter_time_segment_records_descriptive_operation(
        self, controller_with_tracker
    ):
        controller = controller_with_tracker
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=mock_response
        )
        mock_response.text = ""
        mock_response.content = b""
        controller.session.post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            controller.set_inverter_time_segment(
                segment_id=3,
                batt_mode="load_first",
                start_time="04:00",
                end_time="06:00",
                enabled=True,
            )

        failures = controller.failure_tracker.get_active_failures()
        assert len(failures) == 1
        assert "TOU segment 3" in failures[0].operation
        assert "load_first" in failures[0].operation
        assert "04:00-06:00" in failures[0].operation
        assert "enabled" in failures[0].operation

    def test_disabled_segment_shows_disabled_in_operation(
        self, controller_with_tracker
    ):
        controller = controller_with_tracker
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=mock_response
        )
        mock_response.text = ""
        mock_response.content = b""
        controller.session.post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            controller.set_inverter_time_segment(
                segment_id=5,
                batt_mode="battery_first",
                start_time="20:00",
                end_time="22:00",
                enabled=False,
            )

        failures = controller.failure_tracker.get_active_failures()
        assert "disabled" in failures[0].operation


class TestHTTPErrorResponseBodyExtraction:
    """Verify that HTTP error response bodies are captured in failure context."""

    def test_http_error_response_body_included_in_context(
        self, controller_with_tracker
    ):
        controller = controller_with_tracker
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=mock_response
        )
        mock_response.text = '{"error": "Growatt cloud unreachable"}'
        mock_response.content = b""
        controller.session.post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            controller._api_request(
                "post",
                "/api/services/growatt_server/update_time_segment",
                operation="Test operation",
                category="inverter_control",
                context={"segment_id": 1},
            )

        failures = controller.failure_tracker.get_active_failures()
        assert len(failures) == 1
        assert (
            failures[0].context["response_body"]
            == '{"error": "Growatt cloud unreachable"}'
        )
        # Original context should be preserved
        assert failures[0].context["segment_id"] == 1

    def test_response_body_truncated_at_500_chars(self, controller_with_tracker):
        controller = controller_with_tracker
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=mock_response
        )
        mock_response.text = "x" * 1000
        mock_response.content = b""
        controller.session.post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            controller._api_request(
                "post",
                "/api/test",
                operation="Test",
                category="other",
            )

        failures = controller.failure_tracker.get_active_failures()
        assert len(failures[0].context["response_body"]) == 500

    def test_empty_response_body_not_added_to_context(self, controller_with_tracker):
        controller = controller_with_tracker
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=mock_response
        )
        mock_response.text = ""
        mock_response.content = b""
        controller.session.post.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            controller._api_request(
                "post",
                "/api/test",
                operation="Test",
                category="other",
            )

        failures = controller.failure_tracker.get_active_failures()
        assert "response_body" not in failures[0].context

    def test_non_http_error_does_not_add_response_body(self, controller_with_tracker):
        controller = controller_with_tracker
        controller.session.post.side_effect = requests.ConnectionError(
            "Connection refused"
        )

        with pytest.raises(requests.ConnectionError):
            controller._api_request(
                "post",
                "/api/test",
                operation="Test",
                category="other",
                context={"key": "value"},
            )

        failures = controller.failure_tracker.get_active_failures()
        assert len(failures) == 1
        assert "response_body" not in failures[0].context
        assert failures[0].context["key"] == "value"


class TestServiceCallOperationPassthrough:
    """Verify that _service_call_with_retry passes operation through to _api_request."""

    def test_custom_operation_passed_to_api_request(self, controller_with_tracker):
        controller = controller_with_tracker

        with patch.object(controller, "_api_request") as mock_api:
            controller._service_call_with_retry(
                "growatt_server",
                "update_time_segment",
                operation="Custom operation description",
                segment_id=1,
            )

            mock_api.assert_called_once()
            call_kwargs = mock_api.call_args
            assert call_kwargs.kwargs["operation"] == "Custom operation description"

    def test_default_operation_when_none_provided(self, controller_with_tracker):
        controller = controller_with_tracker

        with patch.object(controller, "_api_request") as mock_api:
            controller._service_call_with_retry(
                "switch",
                "turn_on",
                entity_id="switch.grid_charge",
            )

            mock_api.assert_called_once()
            call_kwargs = mock_api.call_args
            assert call_kwargs.kwargs["operation"] == "Call switch.turn_on"
