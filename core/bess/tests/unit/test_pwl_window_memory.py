"""The exact PWL re-solve must not allocate without bound (#697).

On 2026-08-23 the add-on was OOM-killed 11 times in 10 minutes, every kill at
the same point: the log line announcing the #450 exact PWL re-solve, then
`Killed` on the uvicorn process. Home Assistant Supervisor's restart backoff
then gave up and the battery went unmanaged for 38 hours.

The allocation is not proportional to window width -- the reporter's windows
were five periods each. It is `_pwl_candidate_values_at` materialising a dense
`|X| x |actions|` candidate matrix, plus a dozen same-shape temporaries, in one
go. `|actions|` is ~102 for *every* battery, because
`discharge_rate_step_kw = max_discharge_power_kw / 100`, so the cost is a flat
~10 kB per breakpoint and the only free variable is `|X|` -- which compounds
per backward stage as the discharge-preimage cross product
(`_pwl_window_seed_points`) seeds `|xs_next| x ~100` points.

Neither budget caught it. `PWL_MAX_PREIMAGE_SEED_POINTS` counts abscissae, not
evaluation cells, and its own comment mis-states the cost ("1e6 float64 ~ 8 MB"
-- the evaluation on 1e6 seed points is ~10 GB). `PWL_MAX_BREAKPOINTS` is
checked strictly *after* the `values_at(X)` it is meant to bound, and against
the pruned row, which is roughly a tenth of what was just evaluated. So the
solve never raised `PWLWindowUnderRefinedError`, never reached #624's
bisection, and was killed by the kernel instead -- and SIGKILL is not an
exception the optimizer can catch.

The subject here is peak memory, so these assert allocation, not economics.
Exactness is already pinned by `test_pwl_window_dp.py`; what this file adds is
that the same answer is reached inside a bounded footprint.
"""

import json

import numpy as np
import pytest

import core.bess.dp_battery_algorithm as dpa
import core.bess.pwl_window_dp as pwl
from core.bess.exceptions import PWLWindowUnderRefinedError
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.unit.golden_capture import DATA_DIR

# The #624 reporter's day, whose nine-period tie window bisects into halves of
# four and five periods -- the same width as #697's `[(23, 28), (38, 43)]`.
# Reused rather than re-fixtured because it is the corpus's only input that
# still produces a tie window long enough to drive the breakpoint set into the
# region where this bug lives.
FIXTURE = "regression_2026_08_17_624"
WINDOW = (80, 85)

# Measured on this window before the fix: 198 MB traced peak (1134 MB RSS --
# the gap is allocator fragmentation across ~120 repeated hundreds-of-MB
# short-lived arrays, and RSS is what the OOM killer reads). Chunked
# evaluation brings the traced peak to roughly one block's worth. The ceiling
# is set well above that and well below the pre-fix figure, so it discriminates
# without being sensitive to numpy's exact temporary count.
PEAK_ALLOCATION_CEILING_MB = 48.0


@pytest.fixture(scope="module")
def window_inputs() -> dict:
    """Backward-induction kwargs for the bisected half of the #624 window.

    The end SOE comes from the grid DP's own trajectory, exactly as
    `dp_battery_algorithm` pins it when it re-solves a window in production --
    a hand-picked target would change the terminal row and with it the
    breakpoint growth this file is measuring.
    """
    scenario = json.loads((DATA_DIR / f"{FIXTURE}.json").read_text())
    inputs = dict(_scenario_inputs(scenario))
    # No terminal row, for the reason `test_pwl_window_bisection` documents:
    # a nonzero terminal curve breaks the near-ties the hybrid path exists to
    # resolve, and shrinks this window below the width under test.
    inputs.pop("terminal_curve", None)

    diagnostics: dict = {}
    dpa.optimize_battery_schedule(**inputs, tie_diagnostics=diagnostics)

    start, end = WINDOW
    return {
        "window_horizon": end - start,
        "buy_price": inputs["buy_price"][start:end],
        "sell_price": inputs["sell_price"][start:end],
        "home_consumption": inputs["home_consumption"][start:end],
        "solar_production": inputs["solar_production"][start:end],
        "battery_settings": inputs["battery_settings"],
        "dt": inputs["period_duration_hours"],
        "end_soe_target": diagnostics["soe_trajectory"][end],
    }


@pytest.mark.slow
def test_a_five_period_window_solves_within_a_bounded_memory_footprint(
    window_inputs: dict,
) -> None:
    """The outcome #697 is about: the process survives the re-solve.

    Asserting the traced peak rather than the breakpoint count on purpose --
    a breakpoint ceiling is exactly the proxy that was already in place and
    already failed, because it bounded the retained row while the transient
    evaluation was ten times larger.
    """
    import tracemalloc

    tracemalloc.start()
    try:
        pwl.run_pwl_window_backward_induction(**window_inputs)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    peak_mb = peak / 1e6
    assert peak_mb < PEAK_ALLOCATION_CEILING_MB, (
        f"exact PWL re-solve of a {window_inputs['window_horizon']}-period "
        f"window peaked at {peak_mb:.1f} MB, above the "
        f"{PEAK_ALLOCATION_CEILING_MB} MB ceiling -- the objective evaluation "
        f"is allocating proportionally to |X| again (#697)"
    )


def test_blocked_evaluation_is_bitwise_identical_to_one_whole_allocation(
    window_inputs: dict,
) -> None:
    """The exactness claim the fix rests on, tested against the OLD code path.

    `_pwl_candidate_values_block` on the whole of `X` is precisely what
    `_pwl_candidate_values_at` used to do in one allocation, so comparing the
    wrapper against it is a direct before/after on the same input rather than
    a self-comparison. It holds because every reduction in the block is over
    `axis=1` (actions), including the import-cap floor, so a row's value
    depends on no other row; a future candidate that coupled rows -- a
    normalisation, a cross-row cap -- would surface here rather than as a
    drifting economic pin somewhere downstream.

    `X` must exceed the block size or this proves nothing: below it the
    wrapper returns the single-block result unchanged and both sides run
    identical code. The assertion below pins that premise, because an
    innocuous raise of `PWL_EVAL_BLOCK_CELLS` would otherwise turn this test
    green-but-vacuous.
    """
    settings = window_inputs["battery_settings"]
    args = _candidate_args(window_inputs)
    n_actions = np.asarray(args["power_row"]).size + 2
    block = max(1, pwl.PWL_EVAL_BLOCK_CELLS // n_actions)

    n_points = 4 * block + 7  # not a block multiple: exercise a ragged tail
    X = np.linspace(settings.min_soe_kwh, settings.max_soe_kwh, n_points)
    assert X.size > block, (
        f"fixture no longer spans a block boundary ({X.size} <= {block}) -- "
        f"both sides would take the single-block path and this test would "
        f"compare the code to itself"
    )

    blocked = pwl._pwl_candidate_values_at(X, **args)
    one_allocation = pwl._pwl_candidate_values_block(X, **args)

    assert np.array_equal(blocked, one_allocation), (
        "blocked evaluation differs from the single whole-array evaluation -- "
        "some candidate now couples rows, and blocking is no longer exact"
    )


@pytest.mark.slow
def test_an_oversized_evaluation_raises_before_it_allocates(
    window_inputs: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ceiling must fire ahead of the allocation, not after it.

    `PWL_MAX_BREAKPOINTS` was checked one line below the `values_at(X)` it was
    meant to bound, so the memory was already spent by the time the guard
    looked -- and it inspected the pruned row rather than the seed set that
    had actually been evaluated. Squeezing the cell budget to something every
    real row exceeds proves the check is now upstream: the solve must raise,
    and must do so without having allocated the matrix first.
    """
    import tracemalloc

    monkeypatch.setattr(pwl, "PWL_MAX_EVAL_CELLS", 5_000)

    tracemalloc.start()
    try:
        with pytest.raises(PWLWindowUnderRefinedError, match="PWL_MAX_EVAL_CELLS"):
            pwl.run_pwl_window_backward_induction(**window_inputs)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak / 1e6 < PEAK_ALLOCATION_CEILING_MB, (
        f"the cell ceiling raised, but only after allocating {peak / 1e6:.1f} "
        f"MB -- the check is still downstream of the evaluation it bounds"
    )


def _candidate_args(window_inputs: dict) -> dict:
    """The non-`X` arguments `_pwl_candidate_values_at` needs, for period 0."""
    settings = window_inputs["battery_settings"]
    power_row = np.concatenate(
        (
            [0.0],
            pwl._backward_discharge_levels(settings, pwl.DEFAULT_CAPABILITIES) * -1,
            [pwl.POWER_STEP_KW],
        )
    )
    return {
        "t": 0,
        "V_next": pwl._pinned_terminal_row(
            window_inputs["end_soe_target"], 0.05, settings
        ),
        "power_row": power_row,
        "horizon_inputs": (
            window_inputs["buy_price"],
            window_inputs["sell_price"],
            window_inputs["home_consumption"],
            window_inputs["solar_production"],
        ),
        "battery_settings": settings,
        "dt": window_inputs["dt"],
        "period_max_charge": None,
    }
