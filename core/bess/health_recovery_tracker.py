"""Health-check recovery tracking for BESS Manager.

Tracks components that transition from ERROR/WARNING back to OK between
health checks, so an intermittent sensor issue that self-resolves (e.g.
during a brief HA restart) leaves a trace even if nobody was looking at the
live status banner when it happened. See #215.

In-memory only, mirroring RuntimeFailureTracker's design (no full persistence
layer needed for a bounded, dismissible notice).
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class HealthRecovery:
    """A component that recovered from ERROR/WARNING back to OK.

    Attributes:
        id: Unique identifier for this recovery (UUID)
        timestamp: When the recovery was detected
        component: Health-check component name (e.g. "Battery SOC")
        previous_status: Status the component was in before recovering
        detail: The specific failing sensor(s)/entity that caused the
            previous status, e.g. "Battery Charging Power Rate
            (number.growatt_battery_charging_power_rate)". Empty if none
            could be identified.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    component: str = ""
    previous_status: str = ""
    detail: str = ""


class HealthRecoveryTracker:
    """Thread-safe in-memory tracker for health-check recoveries.

    Max Size: 50 recoveries. When exceeded, oldest entries are evicted.
    """

    MAX_RECOVERIES = 50

    def __init__(self):
        self._recoveries: list[HealthRecovery] = []
        self._lock = Lock()

    def record_recovery(
        self, component: str, previous_status: str, detail: str = ""
    ) -> HealthRecovery:
        """Record that a component recovered from an error/warning state."""
        recovery = HealthRecovery(
            component=component, previous_status=previous_status, detail=detail
        )
        with self._lock:
            self._recoveries.append(recovery)
            if len(self._recoveries) > self.MAX_RECOVERIES:
                self._recoveries = self._recoveries[-self.MAX_RECOVERIES :]
        logger.info(
            "Health recovery recorded: %s (%s -> OK)", component, previous_status
        )
        return recovery

    def get_recoveries(self) -> list[HealthRecovery]:
        """Get all pending (unacknowledged) recoveries, newest first."""
        with self._lock:
            return sorted(self._recoveries, key=lambda r: r.timestamp, reverse=True)

    def clear_for_component(self, component: str) -> None:
        """Drop any pending recovery for a component that is erroring again.

        Called when a component goes back to ERROR/WARNING — the live banner
        takes over for that component, so the stale "recovered" note no
        longer applies.
        """
        with self._lock:
            self._recoveries = [r for r in self._recoveries if r.component != component]

    def acknowledge_all(self) -> int:
        """Acknowledge (clear) all pending recoveries.

        Returns:
            Number of recoveries that were cleared.
        """
        with self._lock:
            count = len(self._recoveries)
            self._recoveries = []
        if count:
            logger.info("Acknowledged %d health recoveries", count)
        return count
