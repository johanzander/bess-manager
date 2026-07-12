"""Shared discretization constants for the DP battery optimizer.

Single source of truth for the DP's state/action grid resolution. Imported by
both dp_battery_algorithm.py (which uses them to build the state/action grid)
and decision_intelligence.py (which needs a "is this action real or just
floating-point noise" threshold that scales with the grid, not a hardcoded
absolute value).

Postmortem (#275): decision_intelligence.py used to hardcode
`_POWER_THRESHOLD_KW = 0.1` with a comment noting "The DP uses
POWER_STEP_KW=0.2" -- an implicit, unenforced assumption. Tuning
POWER_STEP_KW to 0.1 during the #275 investigation silently collided with
that hardcoded threshold: the smallest nonzero grid action (exactly 0.1)
failed the classifier's strict `power > 0.1` check, so real grid-charging
actions fell through to a passive-charging fallback and were misclassified
as SOLAR_STORAGE -- which then produced a ~21 SEK realized-vs-planned gap,
since the hardware-command mapper trusts the (wrong) intent label. Deriving
the classification noise-floor from POWER_STEP_KW here means any future grid
resolution change can't reintroduce that exact class of bug.

Not to be confused with dp_battery_algorithm.py's own POWER_TOLERANCE_KW
(a fixed, tiny floating-point epsilon used internally by the DP's backward
search to distinguish "exactly zero" from "any nonzero grid value" -- that
one must stay far smaller than any real grid step regardless of resolution,
so it is not derived from POWER_STEP_KW and is not defined here).
"""

# State space: State of Energy grid resolution (kWh). Matched to
# POWER_STEP_KW * 0.25h (the quarterly-period reachable-state increment, the
# production resolution -- see battery_system_manager.py) so V is sampled
# only at states a single action can actually reach; a finer SOE_STEP_KWH
# than that makes shadow_price's backward-difference report jagged/incorrect
# values at intermediate grid points that aren't independently reachable
# (verified empirically during the #275 Option B investigation).
SOE_STEP_KWH = 0.05

# Action space: power grid resolution (kW).
POWER_STEP_KW = 0.2

# Noise floor for intent classification: "is this action big enough to be a
# real, DP-chosen grid action, or a negligible residual." Set to half the
# grid step so it always sits strictly between the smallest possible nonzero
# grid action (POWER_STEP_KW) and genuine floating-point noise (observed in
# practice: ~1e-10 to 1e-14), regardless of how POWER_STEP_KW is tuned.
POWER_CLASSIFICATION_THRESHOLD_KW = POWER_STEP_KW / 2
