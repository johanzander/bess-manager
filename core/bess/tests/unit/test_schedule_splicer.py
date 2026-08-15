from core.bess.dp_battery_algorithm import PeriodFlows
from core.bess.schedule_splicer import splice_schedule
from core.bess.tie_detection import Window


def _flows(tag: float) -> PeriodFlows:
    """A flow record identifiable by one field, so these fixtures can assert
    *which* record landed in each slot without asserting physics -- what the
    splicer owns is placement, not derivation."""
    return PeriodFlows(
        solar_to_battery=0.0,
        grid_to_battery=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=tag,
        grid_exported=0.0,
        clipped_solar=0.0,
        energy_stored=0.0,
    )


def test_splice_replaces_only_window_periods():
    actions = [1.0, 1.0, 1.0, 1.0, 1.0]
    soe_trajectory = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]  # length horizon+1
    flows_trajectory = [_flows(float(i)) for i in range(5)]
    windows = [Window(start=1, end=3)]
    # replaces periods 1,2
    window_resolutions = {1: [(9.0, 2.9, _flows(91.0)), (9.0, 3.8, _flows(92.0))]}

    spliced_actions, spliced_soe, spliced_flows = splice_schedule(
        actions, soe_trajectory, flows_trajectory, windows, window_resolutions
    )

    assert spliced_actions == [1.0, 9.0, 9.0, 1.0, 1.0]
    assert spliced_soe == [2.0, 2.5, 2.9, 3.8, 4.0, 4.5]
    # The re-solved window's own records travel with its actions; everything
    # outside the window keeps the record the selection loop produced.
    assert [f.grid_imported for f in spliced_flows] == [0.0, 91.0, 92.0, 3.0, 4.0]


def test_splice_with_no_windows_is_a_no_op():
    actions = [1.0, 2.0, 3.0]
    soe_trajectory = [0.0, 1.0, 2.0, 3.0]
    flows_trajectory = [_flows(float(i)) for i in range(3)]
    spliced_actions, spliced_soe, spliced_flows = splice_schedule(
        actions, soe_trajectory, flows_trajectory, [], {}
    )
    assert spliced_actions == actions
    assert spliced_soe == soe_trajectory
    assert spliced_flows == flows_trajectory
