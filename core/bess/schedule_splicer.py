"""Splices a windowed exact solver's (#450) chosen actions back into the
grid DP's full schedule. See core.bess.tie_detection for window discovery
and core.bess.pwl_window_dp for how a window's actions are computed."""

from core.bess.dp_battery_algorithm import PeriodFlows
from core.bess.tie_detection import Window


def splice_schedule(
    actions: list[float],
    soe_trajectory: list[float],
    flows_trajectory: list[PeriodFlows],
    windows: list[Window],
    window_resolutions: dict[int, list[tuple[float, float, PeriodFlows]]],
) -> tuple[list[float], list[float], list[PeriodFlows]]:
    """Splice re-solved windows into the grid DP's action, SOE and flow
    trajectories.

    The flow record travels with its action deliberately (P4): the accounting
    replay then prices the record the solver that chose the action actually
    produced, instead of re-deriving physics from the spliced trajectory --
    a re-derivation that would silently diverge if the replay were ever
    handed different caps than the solve ran under.
    """
    spliced_actions = list(actions)
    spliced_soe = list(soe_trajectory)
    spliced_flows = list(flows_trajectory)

    for window in windows:
        resolution = window_resolutions[window.start]
        for offset, (action, next_soe, flows) in enumerate(resolution):
            period = window.start + offset
            spliced_actions[period] = action
            spliced_soe[period + 1] = next_soe
            spliced_flows[period] = flows

    return spliced_actions, spliced_soe, spliced_flows
