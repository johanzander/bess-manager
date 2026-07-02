"""Custom exception classes for BESS system components.

This module provides specific exception types to replace generic ValueError
usage with string-based error detection patterns.
"""


class BESSException(Exception):
    """Base exception for all BESS system components."""

    pass


class PriceDataUnavailableError(BESSException):
    """Raised when electricity price data is not available for the requested time period."""

    def __init__(self, date=None, message=None):
        if message is None:
            if date:
                message = f"No price data available for {date}"
            else:
                message = "Price data is not available"
        super().__init__(message)
        self.date = date


class SystemConfigurationError(BESSException):
    """Raised when there are configuration or system setup issues."""

    def __init__(self, component=None, message=None):
        if message is None:
            if component:
                message = f"Configuration error in {component}"
            else:
                message = "System configuration error"
        super().__init__(message)
        self.component = component


class HAStatisticsUnavailableError(BESSException):
    """Raised when HA Statistics API is unavailable or returns no data."""

    def __init__(self, message: str | None = None):
        super().__init__(message or "HA Statistics data is not available")


class HistoricalDataUnavailableError(BESSException):
    """Raised when InfluxDB historical energy-flow data is unavailable.

    Historical reconstruction is an optional enhancement (it backfills actuals
    for the daily/savings view); it is never required to run the optimization,
    which uses live SOC plus the configured forecast. Callers should treat this
    as a recoverable, surfaced condition rather than aborting the schedule.
    """

    def __init__(self, message: str | None = None):
        super().__init__(message or "Historical energy-flow data is not available")
