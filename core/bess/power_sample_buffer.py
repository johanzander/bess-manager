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
        # No `if values` guard: `record` appends on the same call that creates
        # the list, so a flow present in the bucket always has >=1 sample.
        return {
            flow_name: (sum(values) / len(values)) * 0.25 / 1000.0
            for flow_name, values in bucket.items()
        }

    def _prune(self, current_period: int) -> None:
        # Periods run 0..95 and wrap at midnight, so "age" has to be computed
        # modulo 96 - a plain `period < current_period - MAX_BUCKET_AGE`
        # comparison never fires across the day boundary (e.g. current_period
        # resets to 0/1/2 while a stale bucket 95 from the previous day is
        # still sitting there), letting that bucket survive and accumulate
        # indefinitely (#387 final review).
        stale = [
            period
            for period in self._samples
            if (current_period - period) % 96 > self.MAX_BUCKET_AGE_PERIODS
        ]
        for period in stale:
            del self._samples[period]
