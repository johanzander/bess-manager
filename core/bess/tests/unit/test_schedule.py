from bess.schedule import Schedule


def test_schedule_creation():
    """Test basic schedule creation."""
    schedule = Schedule()
    schedule.set_optimization_results(
        actions=[1.0, 0.0, -1.0],
        state_of_energy=[3.0, 4.0, 4.0, 3.0],
        prices=[0.5, 1.0, 2.0],
        cycle_cost=0.1,
        hourly_consumption=[1.0, 1.0, 1.0]
    )

    # Test basic structure
    assert len(schedule.actions) == 3
    assert len(schedule.state_of_energy) == 4
    assert hasattr(schedule, 'optimization_results')

def test_schedule_intervals():
    """Test schedule interval creation."""
    schedule = Schedule()
    schedule.set_optimization_results(
        actions=[1.0, 0.0, -1.0],
        state_of_energy=[3.0, 4.0, 4.0, 3.0],
        prices=[0.5, 1.0, 2.0],
        cycle_cost=0.1,
        hourly_consumption=[1.0, 1.0, 1.0]
    )

    # Check intervals
    assert len(schedule.intervals) == 3
    assert schedule.intervals[0]["state"] == "charging"
    assert schedule.intervals[1]["state"] == "standby"
    assert schedule.intervals[2]["state"] == "discharging"

def test_get_hour_settings():
    """Test get_hour_settings functionality."""
    schedule = Schedule()
    schedule.set_optimization_results(
        actions=[1.0, 0.0, -1.0],
        state_of_energy=[3.0, 4.0, 4.0, 3.0],
        prices=[0.5, 1.0, 2.0],
        cycle_cost=0.1,
        hourly_consumption=[1.0, 1.0, 1.0]
    )

    # Test hour settings
    settings = schedule.get_hour_settings(0)
    assert settings["state"] == "charging"
    assert settings["action"] == 1.0
    assert settings["state_of_energy"] == 3.0

    settings = schedule.get_hour_settings(2)
    assert settings["state"] == "discharging"
    assert settings["action"] == -1.0
    assert settings["state_of_energy"] == 4.0
