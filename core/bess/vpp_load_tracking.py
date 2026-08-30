"""VPP load tracking: the bounded middle between "force a rate" and "let go".

Growatt VPP's ``LOAD_SUPPORT`` releases control entirely (#413): remote
control disabled, the inverter runs its own load-following self-use. That was
itself a fix -- forcing a fixed discharge rate caused avoidable imports and
exports whenever the plan's load forecast missed -- but it overshoots. A
released period can cover a spike and can never *hold*: when ``shadow_price``
says the stored energy is worth more at the evening peak, VPP has no way to
express that, and the inverter self-consumes the reservation anyway.

TOU got the other half in #524: a plan-scaled cap whose ceiling the
intra-period discharge gate raises when the energy is worth more now than
later. The economic test contains only prices and the plan --
``buy_price * efficiency_discharge >= shadow_price`` -- so nothing in it is
platform-specific, and the same house with the same prices and the same plan
should behave the same way on both platforms. #520 is that discrepancy.

**Why this needs a tick loop rather than a re-mapping.** VPP carries
``BATTERY_EXPORT``'s planned magnitude faithfully, but collapses
``LOAD_SUPPORT``'s 101 possible rates to a single command: release, or don't.
"Deliver the plan, no more" is inexpressible in that vocabulary. Draft PR #537
tried to map a closed gate onto a ``battery_first`` hold and would have
abandoned every planned kWh in the closed-gate periods -- 118.11 kWh across
the then-36-fixture corpus. The fix has to add expressiveness, and the only
expressiveness the register model allows is recomputing the commanded power
against measured load between period boundaries.

**Energy budget, not power cap.** Two readings of "no more" were considered.
A power cap -- command ``min(deficit, planned rate)`` -- cannot overshoot at
any instant and needs no state, but it leaves the spike under-covered: a
4.8 kW actual against a 1.96 kW forecast would command 1.96 kW and import the
remaining 2.84 kW, which is the failure #352 reports. An energy budget
commands the measured deficit and stops once the period's planned kWh is
spent, so it covers the spike while it lasts and then hands back.

The budget is the correct bound because ``shadow_price`` prices a **kWh, not a
kW**: the gate's test is a per-kWh comparison, so the quantity worth bounding
is energy. It is also what keeps the gate's own approximation honest --
``shadow_price`` is the marginal value at the *planned* SoE, accurate for a
modest overshoot, and flattering for a large one because the true value of
stored energy rises as SoE falls. Bounding total energy stops a large
overshoot running past the point where that approximation holds; bounding the
rate does not bound it at all.

**Budget exhaustion is a hand-back, not an error.** Once spent, the command
drops to the hold and the remainder of the period imports. That is the
reservation being protected, and it is the intended outcome of a closed gate.

See ``docs/superpowers/specs/2026-08-23-vpp-load-tracking-design.md``.
"""

from __future__ import annotations

# Tick cadence. 10 s matches the P1 meter's own update rate -- there is no
# point sampling faster than the data changes -- and is the cadence #520's
# reporter has run as a hand-written HA automation since day one on VPP
# without the inverter showing stress. Growatt VPP protocol V2.01 confirms
# vpp_power / vpp_time / vpp_remote_control are RAM registers, so a frequent
# write loop carries no flash-wear cost.
#
# Reusing the shared scheduler's 1-minute cron was rejected on the design's
# own terms: a kettle cycle can begin and end inside one tick, and that is the
# case this feature exists for.
VPP_LOAD_TRACKING_TICK_SECONDS = 10

# A reading older than this many ticks stops the loop commanding. Stale
# readings are the sharper risk than absent ones -- an absent sensor is caught
# once, at opt-in, by the health check, whereas a sensor that resolves and then
# goes stale *while the loop is commanding power* would otherwise hold a stale
# figure against a load that has since changed.
VPP_LOAD_TRACKING_STALE_TICKS = 3

# vpp_power for "hold": battery_first at a trickle rate. Per the Growatt VPP
# protocol (V2.01 section 3.5) a positive power selects battery_first, which
# per #118/#466 is the one priority that releases house load to grid/solar
# instead of drawing it from the battery. grid_first (power=0) does NOT --
# it holds the battery against *charging* but still lets it serve load, which
# would spend the reservation this bound exists to protect.
#
# The magnitude is 1 rather than anything larger because the physics core's
# STORE branch is binary: any commanded charge above POWER_TOLERANCE_KW
# charges at the full rate, so only +1 (hold) and +100 (charge) are faithfully
# modellable -- see vpp_simulator.vpp_command_to_power.
VPP_HOLD_POWER_PCT = 1


def tracked_vpp_power_pct(
    deficit_kw: float,
    budget_remaining_kwh: float,
    max_discharge_power_kw: float,
) -> int:
    """The ``vpp_power`` percentage to command for one tick.

    Args:
        deficit_kw: Measured house load minus measured solar, floored at 0.
        budget_remaining_kwh: The period's planned discharge energy, less what
            the loop has already spent this period. Non-positive means spent.
        max_discharge_power_kw: The percentage's reference scale --
            ``vpp_power`` is a percentage of the battery's maximum discharge
            rate, matching ``compute_rates_for_period``'s own convention.

    Returns:
        A negative percentage (discharge at that rate) while there is both a
        deficit to cover and budget left to cover it with;
        ``VPP_HOLD_POWER_PCT`` otherwise.

    Both the exhausted-budget case and the no-deficit case return the hold
    rather than a release. Releasing would hand the period back to the
    inverter's own self-use, which is precisely what spends the reservation --
    #413's behaviour, and the half of #520 that has no way to say "hold". The
    hold still permits passive solar absorption, so a surplus is not thrown
    away.
    """
    if max_discharge_power_kw <= 0:
        raise ValueError(
            f"max_discharge_power_kw must be positive to scale a VPP power "
            f"percentage, got {max_discharge_power_kw}"
        )

    if budget_remaining_kwh <= 0 or deficit_kw <= 0:
        return VPP_HOLD_POWER_PCT

    pct = round(deficit_kw / max_discharge_power_kw * 100)
    # A deficit smaller than half a percent of the discharge rating rounds to
    # 0, which is grid_first, not a discharge -- a different command with
    # different physics (#118: grid_first still serves load from the battery,
    # unbounded by this budget). Clamp to the smallest real discharge instead
    # so the command always means what this function decided it means.
    return -max(1, min(100, pct))


def budget_for_period(
    planned_action_kwh: float,
    intra_period_discharge_allowed: bool,
) -> float | None:
    """The tracking budget for one ``LOAD_SUPPORT`` period, or None to release.

    Args:
        planned_action_kwh: The period's planned battery action (negative
            discharges).
        intra_period_discharge_allowed: The DP's own
            ``buy_price * efficiency_discharge >= shadow_price`` verdict,
            carried on ``decision.intra_period_discharge_allowed``.

    Returns:
        The planned discharge energy in kWh when the gate is **closed**, or
        ``None`` when it is **open**.

    The two cases mirror TOU's
    ``max(plan_scaled, intra_period_discharge_gate(...))`` from #524 exactly:

    - **Gate closed** -- the reservation is worth more later, so deliver the
      plan and no more. This is the behaviour VPP cannot express today, and
      the whole reason this module exists.
    - **Gate open** -- the energy is worth more used now than saved, so cover
      whatever load appears. ``None`` means "do not track": releasing control
      (#413) already delivers exactly "unbounded within the period, bounded
      only by SoE floor, physical rating and AC headroom", so tracking would
      add a thread and a write loop to reproduce behaviour that already ships.
      Returning None here is what makes this design a strict addition to #413
      rather than a change to it.

    A closed gate on a period that plans no discharge yields a zero budget,
    which the loop spends immediately and holds -- correct, and not a special
    case: nothing was planned, so nothing is owed.
    """
    if intra_period_discharge_allowed:
        return None
    return max(0.0, -planned_action_kwh)
