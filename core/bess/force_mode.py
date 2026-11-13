"""User-set force mode: an override of the optimizer's plan, held until cleared.

The optimizer keeps planning every cycle; only what is commanded to the
inverter follows the override. The override is expressed in the vocabulary
every platform already executes -- a strategic intent plus a per-period
battery action -- so each platform runs a forced mode exactly the way it runs
that intent when the optimizer plans it, with no platform-specific code here.
"""

from dataclasses import replace

from .dp_schedule import DPSchedule
from .models import PeriodData
from .settings import BatterySettings

FORCE_MODES: frozenset[str] = frozenset(
    {
        "SOLAR_STORAGE",
        "LOAD_SUPPORT",
        "BATTERY_EXPORT",
        "GRID_CHARGING",
        "IDLE",
    }
)


def forced_action_kwh(
    mode: str, battery_settings: BatterySettings, period_hours: float
) -> float:
    """The battery action (kWh per period, + charge / - discharge) a forced mode commands.

    Export and grid charging run at the configured maximum power. LOAD_SUPPORT
    carries the full discharge ceiling too: it is written as a load-following
    mode, so the ceiling only bounds how much of the house load the battery may
    cover -- it is not an export command. SOLAR_STORAGE and IDLE command no
    battery power of their own.
    """
    if mode not in FORCE_MODES:
        raise ValueError(f"Unknown force mode: {mode}")
    if mode == "GRID_CHARGING":
        return battery_settings.max_charge_power_kw * period_hours
    if mode in ("BATTERY_EXPORT", "LOAD_SUPPORT"):
        return -battery_settings.max_discharge_power_kw * period_hours
    return 0.0


def _forced_period(planned: PeriodData, mode: str, action_kwh: float) -> PeriodData:
    """``planned`` with its decisions replaced by the forced command's.

    The forced mode is the whole command: its intent and action, no intra-period
    discharge lift or IDLE release (both are the plan's verdict on its own
    action, and would add discharge to a forced SOLAR_STORAGE or IDLE), and no
    curtailment (it would cap a forced BATTERY_EXPORT). A copy, because the
    stored plan the dashboard shows shares the planned record.
    """
    return replace(
        planned,
        decision=replace(
            planned.decision,
            strategic_intent=mode,
            battery_action=action_kwh,
            intra_period_discharge_allowed=False,
            curtailed=False,
        ),
    )


def apply_force_mode(
    schedule: DPSchedule,
    mode: str,
    from_period: int,
    battery_settings: BatterySettings,
) -> DPSchedule:
    """A copy of ``schedule`` that commands ``mode`` from ``from_period`` onward.

    Periods before ``from_period`` keep the plan's intent and action. From
    ``from_period`` on, each period's decisions (``period_data[p].decision``)
    are the forced command's, so a reader of the commanded schedule needs no
    forced check of its own. The energy trajectory (``state_of_energy`` and
    each period's ``energy``) stays as the optimizer produced it: what a forced
    period's flows would be depends on the forecast and is not modelled here.
    A reader of energy figures still has to treat a forced period, marked by
    ``forced_from_period``, as not following them.
    """
    if mode not in FORCE_MODES:
        raise ValueError(f"Unknown force mode: {mode}")
    period_count = len(schedule.actions)
    if not 0 <= from_period <= period_count:
        raise ValueError(f"from_period {from_period} out of range [0, {period_count}]")

    # Same duration convention as every reader of DPSchedule.actions
    # (BatterySystemManager._apply_period_schedule, get_period_settings), so
    # the forced action converts back to exactly the maximum rate -- including
    # on DST days, whose period count is not 96.
    period_hours = 24.0 / period_count
    forced_action = forced_action_kwh(mode, battery_settings, period_hours)
    forced_count = period_count - from_period

    actions = list(schedule.actions[:from_period]) + [forced_action] * forced_count
    intents = list(schedule.strategic_intents[:from_period]) + [mode] * forced_count
    period_data = [
        (
            planned
            if p < from_period or planned is None
            else _forced_period(planned, mode, forced_action)
        )
        for p, planned in enumerate(schedule.period_data)
    ]

    return DPSchedule(
        actions=actions,
        state_of_energy=schedule.state_of_energy,
        prices=schedule.prices,
        cycle_cost=schedule.cycle_cost,
        hourly_consumption=schedule.hourly_consumption,
        hourly_data={**schedule.hourly_data, "strategic_intent": intents},
        summary=schedule.summary,
        solar_charged=schedule.solar_charged,
        original_dp_results={
            **schedule.original_dp_results,
            "strategic_intent": intents,
            "period_data": period_data,
        },
        forced_from_period=from_period,
    )
