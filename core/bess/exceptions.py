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


class PWLWindowUnderRefinedError(RuntimeError):
    """The windowed PWL solve hit one of its own accuracy budgets, so the
    value table it would return is an approximation of unknown quality.

    Distinct from the *infeasible* case (`pwl_window_is_feasible`), which is
    an ordinary physical outcome the solver reports honestly. This one means
    the solver cannot certify its own answer at all: the only reason the
    hybrid path (#450) re-solves a window is that the grid DP's result on it
    is not trustworthy to within tie-margin accuracy, so handing back a
    result of *unknown* accuracy and letting it be spliced in as if exact
    would replace one silent inaccuracy with another -- precisely the
    fallback `docs/agents/rules.md` forbids. Raising instead makes the
    condition impossible to miss.

    It DOES fire in practice, and the budgets are not the knob. #624 hit it
    in the field on a nine-period merged tie window: the preimage cross
    product compounds per backward step, so the reachable horizon is ~8
    periods and no budget raise extends it (`measure_tie_coverage.py`).
    `dp_battery_algorithm`'s Step 2b therefore catches this exception --
    alone among the raises here -- and bisects the window, re-solving each
    half under this same certification. Reaching a caller means either a
    horizon-1 window that still cannot certify (not a sizing problem) or a
    solve outside that path.
    """


class PWLEndSoeOutOfRangeError(ValueError):
    """The pinned `end_soe_target` lies outside `[min_soe_kwh, max_soe_kwh]`,
    so no terminal row can be built for it.

    A `ValueError` subclass so existing callers and tests that catch
    `ValueError` are unaffected; the distinct type exists so a caller that
    legitimately expects this specific condition (the #450 coverage suite hits
    it on below-min-SOE recovery trajectories) can select for it by type
    instead of matching a substring of this module's prose error message.
    """


class ConsumptionOverlayError(BESSException):
    """The Planned Consumption Changes entity could not be read as blocks.

    Raised rather than skipping the offending block: a user who declared an
    EV session and got half of it applied is worse off than one told their
    template is wrong.
    """


class ManagedLoadsError(BESSException):
    """A managed-load sensor's historical statistics could not be fetched.

    Raised rather than silently forecasting on the un-subtracted baseline: a
    user who excluded their EV charger from "normal" load and got no
    subtraction applied is worse off than one told their sensor is
    unreadable, since the forecast would silently overstate consumption by
    the missing residual.
    """
