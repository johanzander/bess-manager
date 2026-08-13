#!/usr/bin/env python3
"""PreToolUse (Edit|Write|NotebookEdit): inject the optimizer core's normative
principles when the file being edited is part of that core.

Why a hook and not documentation. CLAUDE.md already marks
`docs/agents/optimizer-architecture.md` normative, and rules.md already says a
new test must be seen to fail. Both are prompt text an agent may or may not
have loaded, and the `implement-issue` skill that restates them only fires for
issue work — an ad-hoc DP edit reaches none of it. This fires on the edit, so
the constraints arrive when they apply regardless of how the session got here.

Never blocks: emits `additionalContext` and exits 0. The point is that nobody
edits the DP without being told the rules, not that edits need approval. Any
unexpected input exits 0 silently — a broken hook must not be able to stop
work.

Written as Python rather than a shell heredoc deliberately: `python3 - <<'PY'`
consumes the hook payload on stdin and the script then reads nothing, which is
how the first version of this silently matched no file at all.
"""

import json
import sys

CORE_FILES = (
    "core/bess/dp_battery_algorithm.py",
    "core/bess/action_selector.py",
    "core/bess/pwl_window_dp.py",
    "core/bess/tie_detection.py",
    "core/bess/tie_policy.py",
    "core/bess/dp_constants.py",
    "core/bess/strategic_intent.py",
)

CONTEXT = """\
OPTIMIZER CORE EDIT — docs/agents/optimizer-architecture.md is NORMATIVE here.

The seven principles this file is held to:
  P1  One selector. No second enumerate/evaluate/select implementation; the
      grid and PWL replays share `select_action`. Mirrored implementations
      are the #236 bug class.
  P2  Ties resolve through one lexicographic preference table, not ad-hoc
      comparisons at each call site.
  P3  Candidates are executable commands (Phase 4's target state).
  P4  One flow record per candidate; noise models live at ingestion only.
      Reporting must not re-derive physics the objective already priced.
  P5  One epsilon, one owner.
  P6  Exactness claims are certified or bounded — never asserted.
  P7  Point forecasts stay; risk handling is structural, not stochastic.

Before you finish this change:
  1. A new test must be SEEN TO FAIL without the fix. Write it RED, or revert
     the fix and watch it break, then report which test failed and how many.
     "The suite is green" is evidence the suite is satisfied, never that the
     behaviour holds — three guards in this repo passed while proving nothing.
  2. Assert the OUTCOME, not the command: realized cost, SoE trajectory, or
     flows, not the value written to a register. Command-level assertions are
     legitimate only where no execution model exists, and the test must say so.
  3. Prefer the existing harnesses over a new standalone test file —
     `test_scenarios.py` expected_results, the action-selector goldens, and
     `run_scenario_realized` for R == P.
  4. The goldens pin `actions`, `strategic_intent`,
     `intra_period_discharge_allowed` and the SoE trajectory bit-exactly. A
     reclassification or a gate flip is a golden diff even when no energy
     moves — regenerate deliberately and state the measured delta.
"""


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    normalized = path.replace("\\", "/")

    in_core = any(normalized.endswith(name) for name in CORE_FILES) or (
        "/core/bess/simulation/" in normalized and normalized.endswith(".py")
    )
    if not in_core:
        return

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": CONTEXT,
            }
        },
        sys.stdout,
    )


main()
