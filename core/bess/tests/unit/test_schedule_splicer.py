from core.bess.schedule_splicer import splice_schedule
from core.bess.tie_detection import Window


def test_splice_replaces_only_window_periods():
    actions = [1.0, 1.0, 1.0, 1.0, 1.0]
    soe_trajectory = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]  # length horizon+1
    windows = [Window(start=1, end=3)]
    window_resolutions = {1: [(9.0, 2.9), (9.0, 3.8)]}  # replaces periods 1,2

    spliced_actions, spliced_soe = splice_schedule(
        actions, soe_trajectory, windows, window_resolutions
    )

    assert spliced_actions == [1.0, 9.0, 9.0, 1.0, 1.0]
    assert spliced_soe == [2.0, 2.5, 2.9, 3.8, 4.0, 4.5]


def test_splice_with_no_windows_is_a_no_op():
    actions = [1.0, 2.0, 3.0]
    soe_trajectory = [0.0, 1.0, 2.0, 3.0]
    spliced_actions, spliced_soe = splice_schedule(actions, soe_trajectory, [], {})
    assert spliced_actions == actions
    assert spliced_soe == soe_trajectory
