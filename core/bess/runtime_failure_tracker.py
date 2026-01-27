"""Runtime API failure tracking for BESS Manager.

This module provides in-memory tracking of API operation failures that occur
after retry exhaustion. Failures are displayed to users in the UI and can be
dismissed individually or in bulk.

Design:
- In-memory only (cleared on restart)
- Max 100 failures (FIFO eviction of oldest dismissed)
- Thread-safe for concurrent access
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class RuntimeFailure:
    """Runtime API operation failure record.

    Attributes:
        id: Unique identifier for this failure (UUID)
        timestamp: When the failure occurred
        category: Failure category for grouping (TOU_SEGMENT, POWER_RATE, etc.)
        operation: Human-readable operation description
        error_message: Full exception message for debugging
        dismissed: Whether user has dismissed this notification
        context: Additional context data (segment_id, service params, etc.)
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    category: str = ""
    operation: str = ""
    error_message: str = ""
    dismissed: bool = False
    context: dict = field(default_factory=dict)


class RuntimeFailureTracker:
    """Thread-safe in-memory tracker for runtime API failures.

    Captures and stores API operation failures that occur after retry exhaustion.
    Provides methods to retrieve active failures and dismiss notifications.

    Max Size: 100 failures. When exceeded, oldest dismissed failures are evicted first.
    """

    MAX_FAILURES = 100

    def __init__(self):
        """Initialize empty failure tracker."""
        self._failures: list[RuntimeFailure] = []
        self._lock = Lock()
        logger.info("RuntimeFailureTracker initialized")

    def record_failure(
        self,
        category: str,
        operation: str,
        error: Exception,
        context: dict | None = None,
    ) -> RuntimeFailure:
        """Record a new API failure.

        Args:
            category: Failure category (TOU_SEGMENT, POWER_RATE, etc.)
            operation: Human-readable operation description
            error: The exception that was raised
            context: Optional additional context data

        Returns:
            The created RuntimeFailure object
        """
        failure = RuntimeFailure(
            category=category,
            operation=operation,
            error_message=str(error),
            context=context or {},
        )

        with self._lock:
            self._failures.append(failure)
            self._enforce_max_size()

        logger.warning(
            f"Runtime failure recorded [{category}]: {operation} - {error}"
        )

        return failure

    def get_active_failures(self) -> list[RuntimeFailure]:
        """Get all non-dismissed failures, sorted by timestamp (newest first).

        Returns:
            List of active RuntimeFailure objects
        """
        with self._lock:
            active = [f for f in self._failures if not f.dismissed]
            return sorted(active, key=lambda f: f.timestamp, reverse=True)

    def dismiss_failure(self, failure_id: str) -> None:
        """Dismiss a failure by ID.

        Args:
            failure_id: UUID of the failure to dismiss

        Raises:
            ValueError: If failure ID not found
        """
        with self._lock:
            for failure in self._failures:
                if failure.id == failure_id:
                    failure.dismissed = True
                    logger.info(f"Dismissed runtime failure: {failure_id}")
                    return

        raise ValueError(f"Failure not found: {failure_id}")

    def dismiss_all(self) -> int:
        """Dismiss all active failures.

        Returns:
            Number of failures dismissed
        """
        with self._lock:
            count = 0
            for failure in self._failures:
                if not failure.dismissed:
                    failure.dismissed = True
                    count += 1

            if count > 0:
                logger.info(f"Dismissed {count} runtime failures (bulk action)")

            return count

    def _enforce_max_size(self) -> None:
        """Enforce max failure limit with FIFO eviction of dismissed failures.

        Called internally after adding new failures. Removes oldest dismissed
        failures first to stay within MAX_FAILURES limit.
        """
        if len(self._failures) <= self.MAX_FAILURES:
            return

        # Separate active and dismissed
        active = [f for f in self._failures if not f.dismissed]
        dismissed = [f for f in self._failures if f.dismissed]

        # Sort dismissed by timestamp (oldest first for removal)
        dismissed.sort(key=lambda f: f.timestamp)

        # Calculate how many to remove
        to_remove = len(self._failures) - self.MAX_FAILURES

        # Remove oldest dismissed failures
        if to_remove > 0:
            dismissed = dismissed[to_remove:]
            self._failures = active + dismissed
            logger.debug(f"Evicted {to_remove} old dismissed failures (max size enforcement)")