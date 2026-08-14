"""Tests for OfficialNordpoolSource error classification and health reporting.

Issue #583: a transient 500 from the HA Nordpool integration was reported to the
user as ``⚠️ Please fix sensor configuration for full functionality.`` because
``perform_health_check`` could not distinguish "the integration is not
configured" from "the service call transiently failed".
"""

from unittest.mock import MagicMock

import pytest
import requests

from core.bess import time_utils
from core.bess.exceptions import (
    PriceDataUnavailableError,
    SystemConfigurationError,
)
from core.bess.official_nordpool_source import OfficialNordpoolSource


def _source(ha_controller=None, config_entry_id="01K3Y99FD3MDZYVFX2XSWR4888"):
    return OfficialNordpoolSource(
        ha_controller=ha_controller or MagicMock(),
        config_entry_id=config_entry_id,
        vat_multiplier=1.25,
        area="SE4",
    )


def _http_500():
    """The exact failure from the issue #583 debug bundle."""
    response = MagicMock()
    response.status_code = 500
    return requests.HTTPError(
        "500 Server Error: Internal Server Error for url: "
        "http://supervisor/core/api/services/nordpool/get_prices_for_date",
        response=response,
    )


class TestErrorClassification:
    def test_service_call_failure_raises_price_data_unavailable(self):
        """A 500 from the HA service call is an availability problem, not a
        configuration problem — callers must be able to tell them apart."""
        controller = MagicMock()
        controller._service_call_with_retry.side_effect = _http_500()

        with pytest.raises(PriceDataUnavailableError):
            _source(controller).get_prices_for_date(time_utils.today())

    def test_missing_config_entry_raises_system_configuration_error(self):
        """A missing config entry genuinely is a configuration problem."""
        source = _source(config_entry_id="")

        with pytest.raises(SystemConfigurationError):
            source.get_prices_for_date(time_utils.today())


class TestHealthCheckStatus:
    def test_transient_service_failure_is_reported_as_unavailable_not_misconfigured(
        self,
    ):
        """Issue #583: the system really does have no prices, so the status stays
        ERROR — but the operator-facing text must say the source is temporarily
        unavailable and will be retried, not imply the config is wrong."""
        controller = MagicMock()
        controller._service_call_with_retry.side_effect = _http_500()

        result = _source(controller).perform_health_check()

        assert result["status"] == "ERROR"
        service_check = next(
            c for c in result["checks"] if c["name"] == "Nordpool Service Call"
        )
        assert service_check["status"] == "ERROR"
        error = service_check["error"].lower()
        # Says it will retry (the #583 case) ...
        assert "retry" in error
        # ... and names what to check if it does not heal, because HA answers a
        # stale config entry with an identical 500 and we cannot tell them apart.
        assert "setup wizard" in error
        # But claims neither cause as fact.
        assert "temporarily unavailable" not in error

    def test_missing_config_entry_error_names_the_configuration_problem(self):
        """The two failures share a status, so the text is the only thing that
        distinguishes them — assert what it says, not what it omits."""
        result = _source(config_entry_id="").perform_health_check()

        config_check = result["checks"][0]
        assert config_check["status"] == "ERROR"
        assert "config entry" in config_check["error"].lower()
        assert config_check["value"] == "Missing"

    def test_missing_config_entry_still_reports_error(self):
        """The real misconfiguration must keep its ERROR status — the fix must
        not blunt the signal it exists for."""
        result = _source(config_entry_id="").perform_health_check()

        assert result["status"] == "ERROR"
        assert result["checks"][0]["status"] == "ERROR"

    def test_successful_call_reports_ok(self):
        controller = MagicMock()
        controller._service_call_with_retry.return_value = {
            "service_response": {"SE4": [{"price": 500.0}, {"price": 250.0}]}
        }

        result = _source(controller).perform_health_check()

        assert result["status"] == "OK"
        service_check = next(
            c for c in result["checks"] if c["name"] == "Nordpool Service Call"
        )
        assert service_check["value"] == "2 hourly prices available"
