# Issue #387: InfluxDB-free runtime power gap-fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix issue #387 (runtime energy collection has no correction for zero-resolution cumulative-counter periods) without adding a new InfluxDB dependency to the 15-minute production collection path.

**Architecture:** A new `PowerSampleBuffer` accumulates live power-sensor readings (Watts) every minute via a new scheduler job. `SensorCollector.collect_energy_data()`'s runtime branch consumes that period's buffered samples (averaged, integrated to kWh) to gap-fill any period where the cumulative energy counters read exactly zero — replacing the InfluxDB-based gap-fill that path never should have used. The historical-backfill branch is reverted to its original InfluxDB-gated gap-fill, unchanged in behavior.

**Tech Stack:** Python 3.12, pytest, APScheduler (`CronTrigger`), existing `HomeAssistantAPIController`/`SensorCollector` classes.

## Global Constraints

- No new InfluxDB dependency anywhere in the runtime (15-minute) collection path — this is the entire point of the redesign. (Spec: "Constraint: no new InfluxDB dependency")
- Historical-backfill's existing InfluxDB-based gap-fill must be restored to its pre-#387-fix behavior (gated by `is_historical_backfill`), unchanged otherwise. (Spec: "Design > Historical-backfill branch")
- Buffer is in-memory only; a restart mid-period silently loses that period's samples — no persistence, no new failure mode beyond today's existing "no correction available" no-op. (Spec: "Error handling")
- W→kWh conversion must be `mean_watts * 0.25 / 1000.0`, matching the existing InfluxDB path's constant in `influxdb_helper._parse_power_batch_response`. (Spec: "Components > PowerSampleBuffer.consume")
- New scheduler job runs every minute (`CronTrigger(minute="*")`), matching the existing `apply_discharge_inhibit` cadence tier. (Spec: "Components > New scheduler job")
- `sample_live_power()` must use one bulk `_fetch_all_states()` call, not 6 separate per-sensor requests. (Spec: "Components > SensorCollector.sample_live_power()")
- Comparison logging (counter vs. buffer estimate on non-gap-fill periods) is DEBUG-level only — no new storage, no dashboard surface. (Spec: "Out of scope")

---

### Task 1: `PowerSampleBuffer` — rolling in-memory sample store

**Files:**
- Create: `core/bess/power_sample_buffer.py`
- Test: `core/bess/tests/unit/test_power_sample_buffer.py`

**Interfaces:**
- Produces: `PowerSampleBuffer` class with `record(period: int, readings: dict[str, float]) -> None` and `consume(period: int) -> dict[str, float] | None`. `readings` and the return value of `consume` are keyed by flow name — the 6 keys used throughout `sensor_collector.py`'s `power_sensor_flow_map` values: `"solar_production"`, `"load_consumption"`, `"import_from_grid"`, `"export_to_grid"`, `"battery_charged"`, `"battery_discharged"`. Values are Watts for `record`, kWh for `consume`'s return.

- [ ] **Step 1: Write the failing tests**

```python
"""PowerSampleBuffer: rolling in-memory power-sensor samples, per period.

Sampled every minute and consumed once at each period boundary to gap-fill
zero-delta cumulative-counter periods without an InfluxDB dependency (#387).
"""

from core.bess.power_sample_buffer import PowerSampleBuffer


class TestRecordAndConsume:
    def test_consume_averages_multiple_samples_in_the_same_period(self):
        buffer = PowerSampleBuffer()
        buffer.record(10, {"battery_discharged": 100.0})
        buffer.record(10, {"battery_discharged": 200.0})
        buffer.record(10, {"battery_discharged": 300.0})

        result = buffer.consume(10)

        # mean(100, 200, 300) = 200 W -> 200 * 0.25 / 1000 = 0.05 kWh
        assert result == {"battery_discharged": 0.05}

    def test_consume_converts_watts_to_kwh_for_a_single_sample(self):
        buffer = PowerSampleBuffer()
        buffer.record(5, {"solar_production": 1000.0})

        result = buffer.consume(5)

        # 1000 W * 0.25 h / 1000 = 0.25 kWh
        assert result == {"solar_production": 0.25}

    def test_consume_clears_the_period_bucket(self):
        buffer = PowerSampleBuffer()
        buffer.record(3, {"pv_power": 400.0})

        buffer.consume(3)
        second_call = buffer.consume(3)

        assert second_call is None

    def test_consume_on_unknown_period_returns_none(self):
        buffer = PowerSampleBuffer()

        assert buffer.consume(42) is None

    def test_consume_on_empty_bucket_after_no_records_returns_none(self):
        buffer = PowerSampleBuffer()

        assert buffer.consume(0) is None

    def test_record_tracks_multiple_flow_keys_independently(self):
        buffer = PowerSampleBuffer()
        buffer.record(7, {"battery_charged": 400.0, "solar_production": 800.0})
        buffer.record(7, {"battery_charged": 600.0, "solar_production": 1200.0})

        result = buffer.consume(7)

        assert result == {
            "battery_charged": 0.125,  # mean(400,600)=500W -> 0.125 kWh
            "solar_production": 0.25,  # mean(800,1200)=1000W -> 0.25 kWh
        }


class TestPruning:
    def test_record_prunes_buckets_older_than_two_periods(self):
        buffer = PowerSampleBuffer()
        buffer.record(0, {"pv_power": 100.0})

        # Advancing past period 0 + MAX_BUCKET_AGE_PERIODS (2) should prune it.
        buffer.record(3, {"pv_power": 100.0})

        assert buffer.consume(0) is None

    def test_record_does_not_prune_recent_buckets(self):
        buffer = PowerSampleBuffer()
        buffer.record(5, {"pv_power": 100.0})

        buffer.record(6, {"pv_power": 200.0})

        assert buffer.consume(5) == {"pv_power": 0.025}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_power_sample_buffer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.bess.power_sample_buffer'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_power_sample_buffer.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Format, lint, commit**

```bash
.venv/bin/black core/bess/power_sample_buffer.py core/bess/tests/unit/test_power_sample_buffer.py
.venv/bin/ruff check --fix core/bess/power_sample_buffer.py core/bess/tests/unit/test_power_sample_buffer.py
git add core/bess/power_sample_buffer.py core/bess/tests/unit/test_power_sample_buffer.py
git commit -m "feat: add PowerSampleBuffer for InfluxDB-free power gap-fill (#387)"
```

---

### Task 2: `SensorCollector.sample_live_power()` — the polling side

**Files:**
- Modify: `core/bess/sensor_collector.py` (`__init__` around line 22-72, new method near `_get_period_readings_from_live_sensors` at line 603)
- Test: `core/bess/tests/unit/test_sensor_collector_live_power_sampling.py`

**Interfaces:**
- Consumes: `PowerSampleBuffer` (Task 1) — `self._power_sample_buffer.record(period, readings)`.
- Consumes: `SensorCollector._build_power_entity_to_flow_map(self) -> dict[str, str]` (already exists, `sensor_collector.py:511-522`) — returns `{"sensor.<entity_id>": flow_name, ...}`.
- Consumes: `self.ha_controller._fetch_all_states() -> list[dict]` (already exists, `ha_api_controller.py:2570-2587`) — each dict has `entity_id` and `state` keys (matches production usage at `ha_api_controller.py:2684-2699`).
- Produces: `SensorCollector.sample_live_power(self) -> None`, and `self._power_sample_buffer` attribute (initialized in `__init__`), for Task 4 to consume from.

- [ ] **Step 1: Write the failing tests**

```python
"""SensorCollector.sample_live_power(): the polling half of the #387 fix.

Called every minute by a new scheduler job (Task 5) to record live power
readings into the rolling buffer that collect_energy_data's runtime branch
(Task 4) later consumes for gap-fill.
"""

from unittest.mock import MagicMock

from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings


def _entity_map():
    return {
        "lifetime_battery_charged": "battery_charged_entity",
        "lifetime_battery_discharged": "battery_discharged_entity",
        "lifetime_solar_energy": "solar_entity",
        "lifetime_import_from_grid": "import_entity",
        "lifetime_export_to_grid": "export_entity",
        "battery_soc": "soc_entity",
        "pv_power": "pv_power_entity",
        "local_load_power": "load_power_entity",
        "import_power": "import_power_entity",
        "export_power": "export_power_entity",
        "battery_charge_power": "charge_power_entity",
        "battery_discharge_power": "discharge_power_entity",
    }


def _make_collector():
    entity_map = _entity_map()
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
    battery_settings = BatterySettings(total_capacity=30.0)
    return SensorCollector(ha, battery_settings)


class TestSampleLivePower:
    def test_records_all_configured_power_sensors_into_the_buffer(self):
        collector = _make_collector()
        collector.ha_controller._fetch_all_states.return_value = [
            {"entity_id": "sensor.pv_power_entity", "state": "1000.0"},
            {"entity_id": "sensor.load_power_entity", "state": "1500.0"},
            {"entity_id": "sensor.import_power_entity", "state": "0.0"},
            {"entity_id": "sensor.export_power_entity", "state": "0.0"},
            {"entity_id": "sensor.charge_power_entity", "state": "0.0"},
            {"entity_id": "sensor.discharge_power_entity", "state": "500.0"},
            {"entity_id": "sensor.some_unrelated_entity", "state": "42.0"},
        ]

        collector.sample_live_power()
        result = collector._power_sample_buffer.consume(_current_period())

        assert result["solar_production"] == 0.25  # 1000W -> 0.25 kWh
        assert result["battery_discharged"] == 0.125  # 500W -> 0.125 kWh

    def test_skips_entities_with_non_numeric_state_without_raising(self):
        collector = _make_collector()
        collector.ha_controller._fetch_all_states.return_value = [
            {"entity_id": "sensor.pv_power_entity", "state": "unavailable"},
            {"entity_id": "sensor.discharge_power_entity", "state": "500.0"},
        ]

        collector.sample_live_power()  # must not raise
        result = collector._power_sample_buffer.consume(_current_period())

        assert "solar_production" not in result
        assert result["battery_discharged"] == 0.125

    def test_noop_when_no_power_sensors_configured(self):
        ha = MagicMock()
        ha.resolve_sensor_for_influxdb.return_value = None
        collector = SensorCollector(ha, BatterySettings(total_capacity=30.0))

        collector.sample_live_power()

        ha._fetch_all_states.assert_not_called()

    def test_noop_when_fetch_all_states_raises(self):
        collector = _make_collector()
        collector.ha_controller._fetch_all_states.side_effect = RuntimeError("boom")

        collector.sample_live_power()  # must not raise

        assert collector._power_sample_buffer.consume(_current_period()) is None


def _current_period() -> int:
    from core.bess import time_utils

    now = time_utils.now()
    return now.hour * 4 + now.minute // 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_sensor_collector_live_power_sampling.py -v`
Expected: FAIL with `AttributeError: 'SensorCollector' object has no attribute 'sample_live_power'`

- [ ] **Step 3: Wire the buffer into `__init__` and add `sample_live_power`**

In `core/bess/sensor_collector.py`, add the import near the top (after the existing `from .influxdb_helper import ...` line):

```python
from .power_sample_buffer import PowerSampleBuffer
```

In `SensorCollector.__init__`, after the existing `self._power_batch_cache_loaded_on: dict = {}` line (end of `__init__`, currently line 72), add:

```python
        # Live power-sample buffer for InfluxDB-free runtime gap-fill (#387)
        self._power_sample_buffer = PowerSampleBuffer()
```

Add the new method after `_get_period_readings_from_live_sensors` (after line 654's `return self._normalize_sensor_readings(readings)`, before `warm_readings_cache`):

```python
    def sample_live_power(self) -> None:
        """Record one live power-sensor sample into the rolling buffer.

        Called every minute by the scheduler. No-ops if no power sensors are
        configured. A missing/invalid individual entity is skipped without
        raising - the buffer just records whichever sensors succeeded this
        poll.
        """
        if not self.power_sensors:
            return

        entity_to_flow = self._build_power_entity_to_flow_map()
        if not entity_to_flow:
            return

        try:
            states = self.ha_controller._fetch_all_states()
        except Exception as e:
            logger.warning("Failed to fetch live states for power sampling: %s", e)
            return

        readings: dict[str, float] = {}
        for state in states:
            entity_id = state.get("entity_id")
            flow_name = entity_to_flow.get(entity_id)
            if not flow_name:
                continue
            try:
                readings[flow_name] = float(state.get("state"))
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping power sample for %s: invalid state %r",
                    entity_id,
                    state.get("state"),
                )

        if not readings:
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15
        self._power_sample_buffer.record(current_period, readings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_sensor_collector_live_power_sampling.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full fast suite to check for regressions**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: all pass (existing `test_sensor_collector_gapfill.py` runtime test still passes here — it's untouched until Task 3/4)

- [ ] **Step 6: Format, lint, commit**

```bash
.venv/bin/black core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_live_power_sampling.py
.venv/bin/ruff check --fix core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_live_power_sampling.py
git add core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_live_power_sampling.py
git commit -m "feat: add SensorCollector.sample_live_power for live power polling (#387)"
```

---

### Task 3: Revert the InfluxDB unconditional gate; add historical-backfill regression test

**Files:**
- Modify: `core/bess/sensor_collector.py:231-256` (the gap-fill block committed in the first attempt at this fix)
- Modify: `core/bess/tests/unit/test_sensor_collector_gapfill.py` (replace the runtime-via-InfluxDB test with a historical-backfill-only test; the runtime case is re-added properly in Task 4 using the buffer)

**Interfaces:**
- Consumes: nothing new — this is a revert to `sensor_collector.py`'s pre-#387-fix gap-fill gate, restoring `is_historical_backfill` as the historical-only condition for the InfluxDB-based `_get_power_based_flows` call.

- [ ] **Step 1: Write the replacement test (historical-backfill only)**

Replace the entire contents of `core/bess/tests/unit/test_sensor_collector_gapfill.py` with:

```python
"""Historical backfill gap-fills zero-energy periods from InfluxDB power sensors.

Cumulative HA counters (e.g. Growatt lifetime discharge energy) only tick in
0.1 kWh steps. When a real discharge happens but is too small to register in
a period's window, the counter delta reads exactly zero. The historical/
backfill collection path corrects this via InfluxDB power-sensor data
(`sensor_collector.py:244-256`). Runtime (live) collection gets its own,
InfluxDB-free correction via PowerSampleBuffer - see
test_sensor_collector_runtime_gapfill.py (#387).
"""

from datetime import date
from unittest.mock import MagicMock, patch

from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings


def _entity_map():
    return {
        "lifetime_battery_charged": "battery_charged_entity",
        "lifetime_battery_discharged": "battery_discharged_entity",
        "lifetime_solar_energy": "solar_entity",
        "lifetime_import_from_grid": "import_entity",
        "lifetime_export_to_grid": "export_entity",
        "battery_soc": "soc_entity",
        "pv_power": "pv_power_entity",
        "local_load_power": "load_power_entity",
        "import_power": "import_power_entity",
        "export_power": "export_power_entity",
        "battery_charge_power": "charge_power_entity",
        "battery_discharge_power": "discharge_power_entity",
    }


def _make_ha_controller():
    entity_map = _entity_map()
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
    ha._resolve_entity_id.return_value = ("soc_entity", None)
    return ha


class TestHistoricalBackfillGapFill:
    def test_historical_backfill_gap_fills_zero_discharge_from_influxdb(self):
        ha = _make_ha_controller()
        battery_settings = BatterySettings(total_capacity=30.0)
        collector = SensorCollector(ha, battery_settings)

        # Historical path queries InfluxDB for both current and previous
        # period readings - make them identical (zero delta) for period 5.
        identical_readings = {
            "battery_charged_entity": 100.0,
            "battery_discharged_entity": 50.0,
            "solar_entity": 200.0,
            "import_entity": 300.0,
            "export_entity": 10.0,
            "soc_entity": 45.0,
        }

        power_batch_result = {
            "status": "success",
            "data": {5: {"sensor.discharge_power_entity": 0.35}},
        }

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            patch(
                "core.bess.sensor_collector.get_power_sensor_data_batch",
                return_value=power_batch_result,
            ),
        ):
            mock_time_utils.now.return_value.hour = 3
            mock_time_utils.now.return_value.minute = 0  # current_period = 12
            mock_time_utils.today.return_value = date(2026, 7, 25)

            collector._get_period_readings = MagicMock(
                return_value=dict(identical_readings)
            )

            # period=5 < current_period(12)-1 -> historical backfill branch.
            energy_data = collector.collect_energy_data(5)

        assert energy_data.battery_discharged == 0.35

    def test_runtime_collection_does_not_call_influxdb(self):
        """Runtime collection must never depend on InfluxDB (#387 constraint)."""
        ha = _make_ha_controller()
        ha.get_battery_charged_lifetime.return_value = 100.0
        ha.get_battery_discharged_lifetime.return_value = 50.0
        ha.get_solar_production_lifetime.return_value = 200.0
        ha.get_grid_import_lifetime.return_value = 300.0
        ha.get_grid_export_lifetime.return_value = 10.0
        ha.get_battery_soc.return_value = 45.0

        battery_settings = BatterySettings(total_capacity=30.0)
        collector = SensorCollector(ha, battery_settings)
        collector._last_readings = {
            "battery_charged_entity": 100.0,
            "battery_discharged_entity": 50.0,
            "solar_entity": 200.0,
            "import_entity": 300.0,
            "export_entity": 10.0,
            "soc_entity": 45.0,
        }

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            patch(
                "core.bess.sensor_collector.get_power_sensor_data_batch"
            ) as mock_influxdb_power_batch,
        ):
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45  # current_period = 11
            mock_time_utils.today.return_value = date(2026, 7, 25)

            collector.collect_energy_data(10)  # period=10, runtime branch

        mock_influxdb_power_batch.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail as expected**

Run: `.venv/bin/pytest core/bess/tests/unit/test_sensor_collector_gapfill.py -v`
Expected: `test_historical_backfill_gap_fills_zero_discharge_from_influxdb` PASSES already (historical path untouched); `test_runtime_collection_does_not_call_influxdb` FAILS, because the currently-committed code still calls `get_power_sensor_data_batch` unconditionally for any `all_energy_zero` period, including runtime ones.

- [ ] **Step 3: Revert the gate in `sensor_collector.py`**

In `core/bess/sensor_collector.py`, find the gap-fill block (currently around line 231-256):

```python
        # Gap-filling: when cumulative sensors show zero energy (due to 0.1 kWh resolution),
        # use power (W) sensors which report every ~5 minutes for much higher resolution.
        # Applies to both historical backfill and runtime collection (#387) - a real tick
        # that's too small to register in this period's counter delta produces a "0 ->
        # double" pattern in the following period regardless of which path collected it.
        # _get_power_based_flows degrades gracefully (returns None) when InfluxDB/power
        # sensors aren't configured, so this is a no-op for deployments without them.
        energy_flow_keys = [
            "solar_production",
            "load_consumption",
            "import_from_grid",
            "export_to_grid",
            "battery_charged",
            "battery_discharged",
        ]
        all_energy_zero = all(
            abs(flow_dict.get(key, 0.0)) < 0.001 for key in energy_flow_keys
        )
        if all_energy_zero:
            target_date = time_utils.today()
            power_flows = self._get_power_based_flows(period, target_date)
            if power_flows:
                for key in energy_flow_keys:
                    if key in power_flows and power_flows[key] > 0.001:
                        flow_dict[key] = power_flows[key]
                logger.info(
                    "Period %d: Gap-filled from power sensors: %s",
                    period,
                    {k: f"{v:.4f}" for k, v in power_flows.items() if v > 0.001},
                )
```

Replace it with:

```python
        # Gap-filling: when cumulative sensors show zero energy (due to 0.1 kWh resolution),
        # use power (W) sensors which report every ~5 minutes for much higher resolution.
        # Historical backfill sources this from InfluxDB (below); runtime collection uses
        # a live PowerSampleBuffer instead (see the runtime branch further down in this
        # method) so the 15-minute production path never depends on InfluxDB (#387).
        energy_flow_keys = [
            "solar_production",
            "load_consumption",
            "import_from_grid",
            "export_to_grid",
            "battery_charged",
            "battery_discharged",
        ]
        all_energy_zero = all(
            abs(flow_dict.get(key, 0.0)) < 0.001 for key in energy_flow_keys
        )
        if all_energy_zero and is_historical_backfill:
            target_date = time_utils.today()
            power_flows = self._get_power_based_flows(period, target_date)
            if power_flows:
                for key in energy_flow_keys:
                    if key in power_flows and power_flows[key] > 0.001:
                        flow_dict[key] = power_flows[key]
                logger.info(
                    "Period %d: Gap-filled from InfluxDB power sensors: %s",
                    period,
                    {k: f"{v:.4f}" for k, v in power_flows.items() if v > 0.001},
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_sensor_collector_gapfill.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: all pass

- [ ] **Step 6: Format, lint, commit**

```bash
.venv/bin/black core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_gapfill.py
.venv/bin/ruff check --fix core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_gapfill.py
git add core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_gapfill.py
git commit -m "revert: restore is_historical_backfill gate on InfluxDB gap-fill (#387)

Superseded by PowerSampleBuffer-based runtime gap-fill (next commit) so
the 15-minute production path doesn't depend on InfluxDB."
```

---

### Task 4: Wire `PowerSampleBuffer` into `collect_energy_data`'s runtime branch

**Files:**
- Modify: `core/bess/sensor_collector.py` (runtime branch, after the historical/runtime `if`/`else` block, before the shared gap-fill block modified in Task 3)
- Test: Create `core/bess/tests/unit/test_sensor_collector_runtime_gapfill.py`

**Interfaces:**
- Consumes: `self._power_sample_buffer.consume(period) -> dict[str, float] | None` (Task 1/2).
- Consumes: `energy_flow_keys`, `all_energy_zero`, `flow_dict` (all already local variables in `collect_energy_data`, defined just above the gap-fill block).

- [ ] **Step 1: Write the failing tests**

```python
"""Runtime collection gap-fills zero-energy periods from the live power buffer.

Extends the historical-only gap-fill (test_sensor_collector_gapfill.py) with
the InfluxDB-free runtime path: PowerSampleBuffer accumulates live power
samples every minute (SensorCollector.sample_live_power), and
collect_energy_data's runtime branch consumes that period's buffer to
correct a "0 -> double" cumulative-counter misattribution (#387), or to log
a DEBUG comparison when the counter already had a real nonzero delta.
"""

import logging
from datetime import date
from unittest.mock import MagicMock, patch

from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings


def _entity_map():
    return {
        "lifetime_battery_charged": "battery_charged_entity",
        "lifetime_battery_discharged": "battery_discharged_entity",
        "lifetime_solar_energy": "solar_entity",
        "lifetime_import_from_grid": "import_entity",
        "lifetime_export_to_grid": "export_entity",
        "battery_soc": "soc_entity",
        "pv_power": "pv_power_entity",
        "local_load_power": "load_power_entity",
        "import_power": "import_power_entity",
        "export_power": "export_power_entity",
        "battery_charge_power": "charge_power_entity",
        "battery_discharge_power": "discharge_power_entity",
    }


def _make_runtime_collector():
    entity_map = _entity_map()
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
    ha.get_battery_charged_lifetime.return_value = 100.0
    ha.get_battery_discharged_lifetime.return_value = 50.0
    ha.get_solar_production_lifetime.return_value = 200.0
    ha.get_grid_import_lifetime.return_value = 300.0
    ha.get_grid_export_lifetime.return_value = 10.0
    ha.get_battery_soc.return_value = 45.0

    battery_settings = BatterySettings(total_capacity=30.0)
    collector = SensorCollector(ha, battery_settings)
    collector._last_readings = {
        "battery_charged_entity": 100.0,
        "battery_discharged_entity": 50.0,
        "solar_entity": 200.0,
        "import_entity": 300.0,
        "export_entity": 10.0,
        "soc_entity": 45.0,
    }
    return collector


class TestRuntimeGapFillFromBuffer:
    def test_gap_fills_zero_discharge_from_the_live_power_buffer(self):
        collector = _make_runtime_collector()
        collector._power_sample_buffer.record(10, {"battery_discharged": 1400.0})

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45  # current_period = 11
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        # 1400W * 0.25h / 1000 = 0.35 kWh
        assert energy_data.battery_discharged == 0.35

    def test_stays_zero_when_buffer_is_empty(self):
        collector = _make_runtime_collector()
        # No buffer.record() call for period 10 - buffer empty.

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        assert energy_data.battery_discharged == 0.0

    def test_nonzero_counter_delta_wins_over_buffer_and_logs_debug_comparison(
        self, caplog
    ):
        collector = _make_runtime_collector()
        # Give the current live reading a real nonzero discharge delta.
        collector.ha_controller.get_battery_discharged_lifetime.return_value = 55.0
        collector._power_sample_buffer.record(10, {"battery_discharged": 1000.0})

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            caplog.at_level(logging.DEBUG, logger="core.bess.sensor_collector"),
        ):
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        # Counter delta (55 - 50 = 5 kWh) wins, not the buffer's 0.25 kWh estimate.
        assert energy_data.battery_discharged == 5.0
        assert any(
            "counter vs power-sample estimate" in record.message
            for record in caplog.records
        )

    def test_buffer_is_always_cleared_after_collect_energy_data(self):
        collector = _make_runtime_collector()
        collector._power_sample_buffer.record(10, {"battery_discharged": 1400.0})

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            collector.collect_energy_data(10)

        assert collector._power_sample_buffer.consume(10) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest core/bess/tests/unit/test_sensor_collector_runtime_gapfill.py -v`
Expected: `test_gap_fills_zero_discharge_from_the_live_power_buffer` and `test_buffer_is_always_cleared_after_collect_energy_data` FAIL (buffer never consumed, `battery_discharged` stays `0.0`); `test_stays_zero_when_buffer_is_empty` passes vacuously already; `test_nonzero_counter_delta_wins...` FAILS (no DEBUG log emitted).

- [ ] **Step 3: Add the runtime buffer consumption to `collect_energy_data`**

In `core/bess/sensor_collector.py`, the runtime (`else`) branch currently ends with (around what was originally line 220-222, now shifted slightly by earlier tasks — locate by the comment `# Use cached readings from previous period (START of period)`):

```python
            else:
                # Use cached readings from previous period (START of period)
                previous_readings = self._last_readings
```

Immediately after that `else:` branch closes (i.e., right after the `if/else` for `is_historical_backfill` that started around the historical-vs-runtime branching, and before the `# Calculate energy flows using existing calculator` comment), the method already has this line:

```python
        # Calculate energy flows using existing calculator
        flow_dict = self.energy_flow_calculator.calculate_period_flows(
            current_readings, previous_readings
        )
```

Leave that alone. Instead, modify the gap-fill block from Task 3 (currently ending after the historical `if all_energy_zero and is_historical_backfill:` block) by appending an `else` runtime branch immediately after it:

```python
        if all_energy_zero and is_historical_backfill:
            target_date = time_utils.today()
            power_flows = self._get_power_based_flows(period, target_date)
            if power_flows:
                for key in energy_flow_keys:
                    if key in power_flows and power_flows[key] > 0.001:
                        flow_dict[key] = power_flows[key]
                logger.info(
                    "Period %d: Gap-filled from InfluxDB power sensors: %s",
                    period,
                    {k: f"{v:.4f}" for k, v in power_flows.items() if v > 0.001},
                )
        elif not is_historical_backfill:
            buffer_estimate = self._power_sample_buffer.consume(period)
            if all_energy_zero:
                if buffer_estimate:
                    for key in energy_flow_keys:
                        if key in buffer_estimate and buffer_estimate[key] > 0.001:
                            flow_dict[key] = buffer_estimate[key]
                    logger.info(
                        "Period %d: Gap-filled from live power-sample buffer: %s",
                        period,
                        {
                            k: f"{v:.4f}"
                            for k, v in buffer_estimate.items()
                            if v > 0.001
                        },
                    )
            elif buffer_estimate:
                logger.debug(
                    "Period %d: counter vs power-sample estimate: %s",
                    period,
                    {
                        k: f"{flow_dict.get(k, 0.0):.4f} vs {buffer_estimate.get(k, 0.0):.4f}"
                        for k in energy_flow_keys
                        if k in buffer_estimate
                    },
                )
```

This calls `self._power_sample_buffer.consume(period)` on every runtime collection (whether or not `all_energy_zero`), so the buffer for that period is always cleared, matching the design's "always clears on read" requirement.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest core/bess/tests/unit/test_sensor_collector_runtime_gapfill.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: all pass, including `test_sensor_collector_gapfill.py` (Task 3) and `test_sensor_collector_live_power_sampling.py` (Task 2)

- [ ] **Step 6: Format, lint, commit**

```bash
.venv/bin/black core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_runtime_gapfill.py
.venv/bin/ruff check --fix core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_runtime_gapfill.py
git add core/bess/sensor_collector.py core/bess/tests/unit/test_sensor_collector_runtime_gapfill.py
git commit -m "feat: gap-fill runtime collection from PowerSampleBuffer, not InfluxDB (#387)"
```

---

### Task 5: Wire the scheduler job

**Files:**
- Modify: `backend/app.py:315-370` (`_init_scheduler_jobs`)
- Test: Create `backend/tests/test_scheduler_jobs.py`

**Interfaces:**
- Consumes: `SensorCollector.sample_live_power` (Task 2), reached via `self.system.sensor_collector.sample_live_power` (confirmed attribute name: `battery_system_manager.py:134`, `self.sensor_collector = SensorCollector(...)`).

- [ ] **Step 1: Write the failing test**

```python
"""New scheduler job: sample live power sensors every minute (#387).

Feeds PowerSampleBuffer so collect_energy_data's runtime branch can gap-fill
zero-delta cumulative-counter periods without an InfluxDB dependency.
"""

from unittest.mock import MagicMock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.app import BESSController


def _make_controller_for_scheduler_test():
    controller = BESSController.__new__(BESSController)
    controller.system = MagicMock()
    controller.scheduler = BackgroundScheduler()
    return controller


class TestSchedulerJobs:
    def test_registers_a_per_minute_power_sampling_job(self):
        controller = _make_controller_for_scheduler_test()

        controller._init_scheduler_jobs()

        power_sampling_jobs = [
            job
            for job in controller.scheduler.get_jobs()
            if job.func == controller.system.sensor_collector.sample_live_power
        ]
        assert len(power_sampling_jobs) == 1
        trigger = power_sampling_jobs[0].trigger
        assert isinstance(trigger, CronTrigger)
        minute_field = next(f for f in trigger.fields if f.name == "minute")
        assert str(minute_field) == "*"

        controller.scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_scheduler_jobs.py -v`
Expected: FAIL — no job with `func == controller.system.sensor_collector.sample_live_power` is registered (0 jobs found).

- [ ] **Step 3: Add the job in `_init_scheduler_jobs`**

In `backend/app.py`, inside `_init_scheduler_jobs` (currently around line 315-370), add a new job alongside the existing `apply_discharge_inhibit` job (after it, before the "Health check refresh" job):

```python
        # Live power-sample buffering for InfluxDB-free runtime gap-fill (#387)
        self.scheduler.add_job(
            self.system.sensor_collector.sample_live_power,
            CronTrigger(minute="*"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest backend/tests/test_scheduler_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Run the full fast suite**

Run: `.venv/bin/pytest -m "not slow" -q`
Expected: all pass

- [ ] **Step 6: Format, lint, commit**

```bash
.venv/bin/black backend/app.py backend/tests/test_scheduler_jobs.py
.venv/bin/ruff check --fix backend/app.py backend/tests/test_scheduler_jobs.py
git add backend/app.py backend/tests/test_scheduler_jobs.py
git commit -m "feat: schedule per-minute live power sampling job (#387)"
```

---

### Task 6: CHANGELOG, docs cross-check, and full quality gate

**Files:**
- Modify: `CHANGELOG.md` (replace the #387 entry added by the earlier, now-superseded commit)
- Modify: `docs/agents/bess-knowledge.md` (verify/update the `sensor_collector.py:231` line reference)

**Interfaces:** None — this task is documentation and verification only, no new code interfaces.

- [ ] **Step 1: Replace the CHANGELOG entry**

In `CHANGELOG.md`, find the `### Fixed` entry added for #387 (currently the first bullet under `### Fixed`, starting `**Runtime energy collection had no correction for zero-resolution cumulative-counter periods...**`). Replace its full text with:

```markdown
- **Runtime energy collection had no correction for zero-resolution cumulative-counter periods, unlike historical backfill** — cumulative HA counters (e.g. Growatt lifetime discharge energy) only tick in 0.1 kWh steps; when a real discharge happens but is too small to register within a given 15-minute period, its counter delta reads exactly zero and the energy shows up in the following period once the counter finally ticks — a "0 → double" attribution pattern (observed 3 times in one night's debug bundle, periods 5→6, 9→10, 25→26). This isn't cosmetic: it directly skews `_calculate_initial_cost_basis`'s running acquisition-cost estimate (fed into the DP's discharge cost floor for the rest of that day) and the user-facing realized-savings total, since misattributed energy gets priced at the wrong period's buy/sell rate. The historical/backfill path already corrected this by falling back to power (W) sensors when all cumulative-counter flows read zero, but that correction was gated to `is_historical_backfill` and never reached runtime (live) collection — the path exercised on every 15-minute schedule update. Runtime collection now gets its own, independent correction: a new `PowerSampleBuffer` accumulates live power-sensor readings every minute (a new scheduler job) and `collect_energy_data`'s runtime branch consumes that period's buffered samples to gap-fill, with **no InfluxDB dependency** — deliberately so, since the historical path's InfluxDB-based gap-fill queries the same underlying HA sensor data InfluxDB itself is built from, and would not have closed this gap even if extended to runtime. Independent investigation of the issue's original hypothesis (that runtime collection wasn't boundary-pinned like the historical path) found runtime collection is already boundary-aligned by construction (`CronTrigger(minute="0,15,30,45")`), so that framing wasn't the root cause — the actual gap was the missing correction, not a boundary-alignment defect. ([#387](https://github.com/johanzander/bess-manager/issues/387))
```

- [ ] **Step 2: Check `docs/agents/bess-knowledge.md` for the affected line reference**

```bash
grep -n "sensor_collector.py:231\|is_historical_backfill\|0.1 kWh resolution" docs/agents/bess-knowledge.md
```

The existing reference at `docs/agents/bess-knowledge.md:393` cites `sensor_collector.py:231` for the "documented 0.1 kWh resolution" fact — this fact itself is unchanged (cumulative counters still have 0.1 kWh resolution), but the line number may have drifted from the edits in Tasks 3-4. Run:

```bash
grep -n "0.1 kWh resolution" core/bess/sensor_collector.py
```

If the line number differs from 231, update the citation in `docs/agents/bess-knowledge.md:393` to the new line number. Do not change the surrounding prose — it describes the counter-resolution fact, not the gap-fill mechanism, and remains accurate.

- [ ] **Step 3: Run the full fast suite and slow suite**

```bash
.venv/bin/pytest -m "not slow" -q
.venv/bin/pytest -m slow -q
```

Expected: all pass (fast suite ~1278+ tests including the ~16 new tests from Tasks 1-5; slow suite unaffected, this change doesn't touch DP/scheduling algorithms).

- [ ] **Step 4: Run the full quality gate**

```bash
./scripts/quality-check.sh
```

Expected: PASS (black, ruff, fast suite, and any other configured checks all clean).

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md docs/agents/bess-knowledge.md
git commit -m "docs: update CHANGELOG and bess-knowledge.md for #387 InfluxDB-free gap-fill"
```

---

## After Task 6

Per the `implement-issue` skill this work is being driven from: Step 8 (local run & observe, never skippable) still applies — bring up the mock-HA + backend stack (`docker-compose.ci.yml`) and confirm `sample_live_power()` runs cleanly against a live mock-HA instance every minute (no exceptions, buffer populates), the way the earlier verify pass already did for the graceful-degradation case. Then proceed to Step 9 (commit + draft PR) using the existing worktree/branch (`fix/issue-387-runtime-gapfill`) — no new worktree needed, this plan's tasks are additional commits on that branch.
