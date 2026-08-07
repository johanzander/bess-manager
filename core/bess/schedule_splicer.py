"""Splices a windowed exact solver's (#450) chosen actions back into the
grid DP's full schedule. See core.bess.tie_detection for window discovery
and core.bess.pwl_window_dp for how a window's actions are computed."""

from core.bess.tie_detection import Window


def splice_schedule(
    actions: list[float],
    soe_trajectory: list[float],
    windows: list[Window],
    window_resolutions: dict[int, list[tuple[float, float]]],
) -> tuple[list[float], list[float]]:
    spliced_actions = list(actions)
    spliced_soe = list(soe_trajectory)

    for window in windows:
        resolution = window_resolutions[window.start]
        for offset, (action, next_soe) in enumerate(resolution):
            period = window.start + offset
            spliced_actions[period] = action
            spliced_soe[period + 1] = next_soe

    return spliced_actions, spliced_soe
