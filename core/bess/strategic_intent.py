"""
Strategic intent classification and decision data construction.

Control-path code: `classify_strategic_intent` drives the Growatt TOU
hardware mode via `INTENT_TO_CONTROL` and the intent badges in
`BatteryActionsTable`, so it lives separately from reporting/analysis code.
"""

from core.bess.dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW
from core.bess.models import DecisionData, EnergyData

# Minimum absolute power (kW) for the main charge/discharge branches. Derived
# from the DP's own grid resolution (dp_constants.py) rather than hardcoded,
# so it can never silently collide with a tuned POWER_STEP_KW again -- see
# dp_constants.py's docstring for the #275 postmortem this fixes. This
# threshold filters noise while the fallthroughs below catch passive solar
# charging (battery_charged > 0) and small residual discharge.
_POWER_THRESHOLD_KW = POWER_CLASSIFICATION_THRESHOLD_KW

# Energy noise floor (kWh) shared by every flow check in
# classify_strategic_intent: flows at or below this are treated as noise,
# not evidence of a real action. Exported because the DP's residual-cover
# candidate gate (#466 follow-up, action_selector._residual_cover_p)
# must plan only discharges that this classifier will recognize as
# LOAD_SUPPORT -- a sub-floor planned discharge classifies IDLE and the
# command mapper executes nothing (the #282 R != P failure shape). Keeping
# the gate and the classifier on one constant prevents the silent-collision
# drift the #275 postmortem describes.
FLOW_NOISE_FLOOR_KWH = 0.01


def idle_hold_releasable(verdict_open: bool, planned_grid_imported_kwh: float) -> bool:
    """May a forced-power (VPP) platform release an IDLE hold this period? (#786)

    The one declaration of the rule, read by the write path, the display and the
    simulator alike. True when both hold:

    * the DP's verdict is open -- the stored energy is worth no more than the
      grid price (`decision.intra_period_discharge_allowed`, #526), and
    * the plan's own deficit (`energy.grid_imported`) is within
      `FLOW_NOISE_FLOOR_KWH`.

    The second condition is what makes IDLE a *fall-through* rather than a
    choice: `action_selector._residual_cover_p` refuses a cover below the floor,
    so a sub-floor deficit lands in IDLE although the optimizer never weighed
    holding against covering. Releasing then costs nothing when forecast equals
    plan and saves the import when load runs high. A deficit above the floor
    that the plan left to the grid is a deliberate IDLE -- the verdict is a
    marginal value at the planned SoE, and releasing would let the battery cover
    the whole deficit, draining energy the plan reserved for later (measured on
    the scenario corpus: +3.6 SEK worse in total, +4.5 on one fixture).
    """
    return verdict_open and planned_grid_imported_kwh <= FLOW_NOISE_FLOOR_KWH


def discharge_ceiling_lifts(
    intent: str, verdict_open: bool, planned_grid_imported_kwh: float
) -> bool:
    """Does the DP's open verdict raise this slot's discharge ceiling on a
    load-following platform (Growatt MIN TOU/cloud)? (#811)

    The one declaration of which intents get the lift, read by the write path
    and the simulator. SOLAR_EXPORT / SOLAR_STORAGE / LOAD_SUPPORT lift on an
    open verdict (#526). IDLE lifts only when it is a fall-through
    (`idle_hold_releasable`): a near-balanced slot lands in IDLE, and with a
    ceiling of 0 it cannot cover solar coming in low or load coming in high.
    """
    if intent in ("SOLAR_EXPORT", "SOLAR_STORAGE", "LOAD_SUPPORT"):
        return verdict_open
    if intent == "IDLE":
        return idle_hold_releasable(verdict_open, planned_grid_imported_kwh)
    return False


def classify_strategic_intent(power: float, energy_data: EnergyData) -> str:
    """Classify the strategic intent of a battery action based on power and energy flows.

    Intent controls hardware behavior via the Growatt TOU schedule and is displayed
    to the user in the UI. Must accurately reflect the actual action.

    The main branches use ``_POWER_THRESHOLD_KW`` (0.1 kW) to filter noise.
    Fallthrough branches catch passive solar charging and small residual
    discharge that fall below the threshold.

    Args:
        power: Battery power action (+ charge, - discharge) in kW.
        energy_data: Complete energy flow data for the period.

    Returns:
        One of: GRID_CHARGING, SOLAR_STORAGE, LOAD_SUPPORT, BATTERY_EXPORT, SOLAR_EXPORT, IDLE.
    """
    if power < -_POWER_THRESHOLD_KW:  # Discharging
        # Any meaningfully nonzero export (same 0.01 kWh noise floor used by
        # every other flow check in this function) must be BATTERY_EXPORT:
        # LOAD_SUPPORT maps to load_first, which can only ever cover a real
        # deficit and physically cannot export -- see
        # docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md
        # for the R == P failure this threshold mismatch caused.
        if energy_data.battery_to_grid > FLOW_NOISE_FLOOR_KWH:
            return "BATTERY_EXPORT"
        return "LOAD_SUPPORT"
    elif power > _POWER_THRESHOLD_KW:  # Charging
        if energy_data.grid_to_battery > FLOW_NOISE_FLOOR_KWH:
            return "GRID_CHARGING"
        return "SOLAR_STORAGE"
    elif energy_data.battery_charged > FLOW_NOISE_FLOOR_KWH:
        return "SOLAR_STORAGE"
    elif energy_data.battery_discharged > FLOW_NOISE_FLOOR_KWH:
        return "LOAD_SUPPORT"
    elif (
        energy_data.grid_exported > FLOW_NOISE_FLOOR_KWH
        and energy_data.solar_to_grid > FLOW_NOISE_FLOOR_KWH
    ):
        return "SOLAR_EXPORT"
    return "IDLE"


def create_decision_data(
    power: float,
    battery_action_kwh: float,
    energy_data: EnergyData,
    cost_basis: float,
    future_value: float,
    curtailed: bool = False,
) -> DecisionData:
    """
    Create DecisionData for a DP-evaluated period.

    Args:
        power: Battery power action (+ charge, - discharge) in kW
        battery_action_kwh: Reported planned energy action in kWh for this period.
            Caller-derived, since only the caller knows whether `power` is the
            physically achieved action or merely a DP test value.
        energy_data: Complete energy flow data
        cost_basis: Cost basis of stored energy per kWh
        future_value: The DP's value-to-go from the resulting state
            (continuation_value) -- the best achievable outcome from the
            resulting battery level onward.
        curtailed: Caller-computed planned-curtailment flag (#501) -- mirrors
            BSM's execution-time should_curtail condition.

    Returns:
        DecisionData with strategic intent and economic fields populated.
    """
    strategic_intent = classify_strategic_intent(power, energy_data)

    return DecisionData(
        strategic_intent=strategic_intent,
        battery_action=battery_action_kwh,
        cost_basis=cost_basis,
        future_value=future_value,
        curtailed=curtailed,
    )
