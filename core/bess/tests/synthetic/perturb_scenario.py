"""Deterministic scenario perturbation for the #450 tie-detection coverage
validation suite (see docs/superpowers/specs/2026-08-05-tie-detection-
synthetic-validation-design.md). Generates realistic-shaped variants of the
existing fixtures rather than a from-scratch synthetic price model -- every
perturbed scenario keeps a real diurnal price shape and consumption profile;
only the parameters relevant to this investigation move.
"""

import copy
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PerturbationParams:
    price_level_multiplier: float = 1.0
    volatility_jitter: float = 0.0
    solar_scale: float = 1.0
    battery_capacity_override_kwh: float | None = None


def perturb_scenario(base_fixture: dict, seed: int, params: PerturbationParams) -> dict:
    scenario = copy.deepcopy(base_fixture)
    rng = random.Random(seed)

    for key in ("buy_price", "sell_price"):
        if key in scenario:
            scaled = [v * params.price_level_multiplier for v in scenario[key]]
            if params.volatility_jitter:
                scaled = [
                    v
                    * (
                        1.0
                        + rng.uniform(
                            -params.volatility_jitter, params.volatility_jitter
                        )
                    )
                    for v in scaled
                ]
            scenario[key] = scaled

    if params.solar_scale != 1.0:
        scenario["solar_production"] = [
            v * params.solar_scale for v in scenario["solar_production"]
        ]

    if params.battery_capacity_override_kwh is not None:
        if params.battery_capacity_override_kwh <= 0:
            raise ValueError(
                "battery_capacity_override_kwh must be positive, got "
                f"{params.battery_capacity_override_kwh}"
            )
        battery = scenario["battery"]
        old_max = battery["max_soe_kwh"]
        new_max = params.battery_capacity_override_kwh
        # Keep min/initial SOE proportional to the old capacity, then clamp
        # into the new range so a large capacity reduction can't leave
        # initial_soe or min_soe_kwh above the new max.
        battery["min_soe_kwh"] = min(
            battery["min_soe_kwh"] * (new_max / old_max), new_max
        )
        battery["initial_soe"] = min(
            battery["initial_soe"] * (new_max / old_max), new_max
        )
        battery["max_soe_kwh"] = new_max

    return scenario
