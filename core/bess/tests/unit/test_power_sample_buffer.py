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
