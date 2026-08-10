"""The live cost-basis path, exercised on a real recorded day.

`_calculate_initial_cost_basis` is the one behaviour change in Phase 3 that
the synthetic scenario corpus cannot reach at all: fixtures pass
`initial_cost_basis` in as an input, so the goldens never call this function.
It is also the change with real money behind it -- its result feeds
`optimize_battery_schedule(initial_cost_basis=...)`, and understating it makes
stored energy look cheaper to discharge than it was.

So it is pinned here against actual sensor data from a user's system
(`bess-debug-2026-07-18-181637.md`, 73 recorded periods) rather than against
hand-built numbers. Measured across all 30 bundles in `docs/`: 118 charging
periods in 15 of them carry the attribution error, totalling 48.9 kWh of grid
charging that the retired formula booked as free solar; 14 periods carry
charge that neither source can account for.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData

TIMEZONE = ZoneInfo("Europe/Stockholm")
FIXTURE = (
    Path(__file__).parent
    / "data"
    / "bundles"
    / "historical_2026_07_18_charge_attribution.json"
)


def _load():
    return json.loads(FIXTURE.read_text())["periods"]


def _record(system, rows):
    """Replay recorded periods into the historical store, exactly as the
    sensor collector would have."""
    for row in rows:
        energy = EnergyData(
            solar_production=row["solar_production"],
            home_consumption=row["home_consumption"],
            battery_charged=row["battery_charged"],
            battery_discharged=row["battery_discharged"],
            grid_imported=row["grid_imported"],
            grid_exported=row["grid_exported"],
            clipped_solar=row["clipped_solar"],
            battery_soe_start=row["battery_soe_start"],
            battery_soe_end=row["battery_soe_end"],
        )
        system.historical_store.record_period(
            row["period"],
            PeriodData(
                period=row["period"],
                energy=energy,
                economic=EconomicData(buy_price=row["buy_price"]),
                timestamp=datetime.now(tz=TIMEZONE),
                data_source="actual",
                decision=DecisionData(),
            ),
        )


def _replay_cost_basis(rows, cycle_cost, attribute):
    """Independent re-implementation of the running total, parameterised by
    the charge-source split, so the two attributions can be compared without
    reaching into the method under test."""
    first = min(r["period"] for r in rows)
    start = next(r for r in rows if r["period"] == first)["battery_soe_start"]
    energy, cost = start, start * cycle_cost

    for row in sorted(rows, key=lambda r: r["period"]):
        e = EnergyData(
            solar_production=row["solar_production"],
            home_consumption=row["home_consumption"],
            battery_charged=row["battery_charged"],
            battery_discharged=row["battery_discharged"],
            grid_imported=row["grid_imported"],
            grid_exported=row["grid_exported"],
            clipped_solar=row["clipped_solar"],
            battery_soe_start=row["battery_soe_start"],
            battery_soe_end=row["battery_soe_end"],
        )
        if e.battery_charged > 0:
            s2b, g2b = attribute(e)
            unattributed = max(0.0, e.battery_charged - s2b - g2b)
            cost += s2b * cycle_cost + (g2b + unattributed) * (
                row["buy_price"] + cycle_cost
            )
            energy += e.battery_charged
        if e.battery_discharged > 0 and energy > 0:
            avg = cost / energy
            cost = max(0.0, cost - min(e.battery_discharged, energy) * avg)
            energy = max(0.0, energy - e.battery_discharged)
            if energy <= 0.1:
                cost, energy = 0.0, 0.0
    return cost / energy if energy > 0.1 else cycle_cost


def _correct(e):
    return e.solar_to_battery, e.grid_to_battery


def _retired(e):
    """The formula this fix replaced: blind to the house load."""
    s2b = min(e.battery_charged, e.solar_production)
    return s2b, max(0.0, e.battery_charged - s2b)


def test_real_day_cost_basis_uses_the_derived_charge_split(base_system):
    """On a real recorded day the live path must agree with `EnergyData`'s
    attribution, and must NOT agree with the retired load-blind one."""
    rows = _load()
    cycle_cost = base_system.battery_settings.cycle_cost_per_kwh
    _record(base_system, rows)

    actual = base_system._calculate_initial_cost_basis(
        current_period=max(r["period"] for r in rows) + 1
    )

    expected = _replay_cost_basis(rows, cycle_cost, _correct)
    retired = _replay_cost_basis(rows, cycle_cost, _retired)

    assert actual == pytest.approx(expected, rel=1e-9)

    # The day must actually discriminate, or this test proves nothing.
    assert retired != pytest.approx(expected, rel=1e-6), (
        "this recorded day no longer exercises the attribution difference -- "
        "pick a bundle whose periods consume solar at home while charging"
    )
    # And the retired split understates, which is why it cost money.
    assert retired < expected


def test_real_day_has_charge_neither_source_explains(base_system):
    """The unattributed-charge case is real, not hypothetical.

    Independent lifetime counters do not reconcile exactly, so
    `EnergyData.grid_to_battery` -- capped by the grid counter's own reading --
    can leave part of a recorded charge unexplained. Every such kWh still
    divides into the running total, so leaving it uncosted drags the basis
    down. It is priced at cycle cost, as this method already prices the
    pre-existing charge of unknown provenance.
    """
    rows = _load()
    cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

    unattributed = []
    for row in rows:
        e = EnergyData(
            solar_production=row["solar_production"],
            home_consumption=row["home_consumption"],
            battery_charged=row["battery_charged"],
            battery_discharged=row["battery_discharged"],
            grid_imported=row["grid_imported"],
            grid_exported=row["grid_exported"],
            clipped_solar=row["clipped_solar"],
            battery_soe_start=row["battery_soe_start"],
            battery_soe_end=row["battery_soe_end"],
        )
        resid = e.battery_charged - e.solar_to_battery - e.grid_to_battery
        if resid > 1e-9:
            unattributed.append((row["period"], resid))

    assert unattributed, (
        "this recorded day no longer contains unattributed charge, so it "
        "cannot pin the costing of it -- pick another bundle"
    )

    _record(base_system, rows)
    actual = base_system._calculate_initial_cost_basis(
        current_period=max(r["period"] for r in rows) + 1
    )

    def _uncosted(e):
        return e.solar_to_battery, e.grid_to_battery

    def _replay_uncosted():
        first = min(r["period"] for r in rows)
        start = next(r for r in rows if r["period"] == first)["battery_soe_start"]
        energy, cost = start, start * cycle_cost
        for row in sorted(rows, key=lambda r: r["period"]):
            e = EnergyData(
                solar_production=row["solar_production"],
                home_consumption=row["home_consumption"],
                battery_charged=row["battery_charged"],
                battery_discharged=row["battery_discharged"],
                grid_imported=row["grid_imported"],
                grid_exported=row["grid_exported"],
                clipped_solar=row["clipped_solar"],
                battery_soe_start=row["battery_soe_start"],
                battery_soe_end=row["battery_soe_end"],
            )
            if e.battery_charged > 0:
                s2b, g2b = _uncosted(e)
                cost += s2b * cycle_cost + g2b * (row["buy_price"] + cycle_cost)
                energy += e.battery_charged
            if e.battery_discharged > 0 and energy > 0:
                avg = cost / energy
                cost = max(0.0, cost - min(e.battery_discharged, energy) * avg)
                energy = max(0.0, energy - e.battery_discharged)
                if energy <= 0.1:
                    cost, energy = 0.0, 0.0
        return cost / energy if energy > 0.1 else cycle_cost

    assert actual > _replay_uncosted(), (
        "unattributed charge is being added to the running energy without a "
        "cost, which dilutes the basis downward"
    )

    # And it must not be priced BELOW what the retired formula charged for the
    # same energy. The retired split assigned everything above solar to the
    # grid at buy price, so pricing the remainder at cycle cost would have been
    # cheaper than the bug -- understating the basis, the very failure this
    # method was fixed for. This is the direction the first version of this
    # test could not see, because it only compared against costing at zero.
    retired = _replay_cost_basis(rows, cycle_cost, _retired)
    assert actual >= retired, (
        "the unattributed remainder is priced below what the retired split "
        "charged for it -- a 'fix' cheaper than the bug"
    )
