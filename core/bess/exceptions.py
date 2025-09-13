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