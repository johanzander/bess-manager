"""Rolling in-memory buffer of live power-sensor samples, per period.

Sampled every minute (`SensorCollector.sample_live_power`) and consumed once
at each period boundary (`SensorCollector.collect_energy_data`) to gap-fill
periods where the cumulative energy counters read exactly zero (#387),
without depending on InfluxDB.
"""


class PowerSampleBuffer:
    """Averages Watt samples per period and converts to kWh on consume."""

    MAX_BUCKET_AGE_PERIODS = 2

    def __init__(self) -> None:
        self._samples: dict[int, dict[str, list[float]]] = {}

    def record(self, period: int, readings: dict[str, float]) -> None:
        """Append one poll's readings (Watts) into this period's bucket."""
        bucket = self._samples.setdefault(period, {})
        for flow_name, watts in readings.items():
            bucket.setdefault(flow_name, []).append(watts)
        self._prune(period)

    def consume(self, period: int) -> dict[str, float] | None:
        """Average and convert this period's samples to kWh, then clear it.

        Returns None if no samples were recorded for this period.
        """
        bucket = self._samples.pop(period, None)
        if not bucket:
            return None
        return {
            flow_name: (sum(values) / len(values)) * 0.25 / 1000.0
            for flow_name, values in bucket.items()
            if values
        }

    def _prune(self, current_period: int) -> None:
        stale = [
            period
            for period in self._samples
            if period < current_period - self.MAX_BUCKET_AGE_PERIODS
        ]
        for period in stale:
            del self._samples[period]
