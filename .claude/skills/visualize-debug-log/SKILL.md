---
name: visualize-debug-log
description: Use when asked to visualize a bess-manager debug log/bundle, or when the user says "visualize this PR" / "visualize this issue" / "visualize this debug log" and a debug export is attached or referenced in a GitHub issue, PR comment, or local file.
---

# Visualize Debug Log

## Overview

Turns a BESS Manager debug bundle (the `.md` export attached to GitHub
issues/PRs, or produced locally by `mock-run.sh`/the Debug tab) into a
published interactive Artifact: a three-panel chart (price, energy trend,
battery SOE) with a fully toggleable ledger and a grouped tooltip, plus a raw
data table.

**Key property: it always reflects the current branch, not a stale
snapshot.** `scripts/build_chart.py` imports `core.bess.models.EnergyData`
and `infer_intent_from_flows` directly from the repo it's run from and
recomputes every actual/historical period's detailed flows and observed
intent from the bundle's six raw sensor aggregates — it never trusts the
bundle's own pre-computed `energy`/`decision` values for those periods, since
those were serialized by whatever code was running at export time and may
predate a since-merged fix (this is exactly how a stale-vs-current
discrepancy was caught and fixed during issue #328/#342/#350's
investigation). Forecast periods (from the bundle's `Raw Schedule JSON`,
latest optimization run) are used as-is, since they're the DP's own planning
output, not sensor-derived.

**One implementation, not two.** Every threshold, comparison, and formula the
tooltip shows (which price the shadow price is weighed against, whether it
clears, breakeven/profit, reward/total value, net savings) is computed once
in Python (`build_chart.py`'s `compute_decision_view`), reusing the same
`POWER_CLASSIFICATION_THRESHOLD_KW` core's own code classifies flows with.
`template_tail.js` only formats the resulting `view` dict per row — it never
re-derives a threshold or an economic formula from raw numbers. A bug fix or
behavior change in the real economics only has to happen in Python to reach
the chart; adding JS-side logic that duplicates something Python already
knows is the mistake this design exists to prevent.

## When to Use

- User asks to "visualize" a debug log, debug bundle, or a PR/issue that has
  one attached.
- User is debugging a reported behavior (wrong intent label, missing flow,
  savings discrepancy) and would benefit from seeing the whole day's
  price/energy/battery trace rather than reading bundle JSON by hand.

Not for: rendering the *live* running system's dashboard (that's the actual
frontend) — this is for a point-in-time bundle snapshot only.

## Process

1. **Get the bundle.** If it's attached to a GitHub issue/PR comment, download
   it:
   ```bash
   gh issue view <n> --json comments -q '.comments[].body' | grep -oE 'https://github.com/user-attachments/files/[^)]+'
   curl -sL <url> -o /tmp/bundle.md
   ```
   If the user pasted a local path, use it directly.

2. **Build the chart**, run from the repo whose `core/bess/models.py` should
   be reflected (a specific branch/worktree if the point is to show a fix's
   effect):
   ```bash
   python3 .claude/skills/visualize-debug-log/scripts/build_chart.py /tmp/bundle.md -o /tmp/chart.html
   ```
   Optional `--title "..."` to override the auto-generated title.

3. **Publish** the output with the `Artifact` tool (`file_path` = the
   generated HTML, pick a `favicon`, write a one-sentence `description`).

4. **If comparing before/after a fix** (e.g. "does this look different on
   `main` vs this branch"): run the build script once per worktree/branch and
   publish as two artifacts (or note in one artifact's description which
   branch it was built from) — never hand-edit the recomputed values.

## Quick Reference

| Piece | What it is |
|---|---|
| `scripts/build_chart.py` | Parses the bundle, recomputes actual periods via real `EnergyData`, merges with forecast `period_data`, renders the final HTML |
| `scripts/template_head.html` | CSS + page skeleton, `{{TITLE}}`/`{{SUBTITLE}}` placeholders |
| `scripts/template_tail.js` | Chart rendering, legend/ledger toggles, tooltip — reads `ROWS` and `SUMMARY` globals the build script injects |
| `ROWS` | One object per period: raw aggregates, detailed flows, intent, DP-reasoning fields (`shadow_price`, `cost_basis`, `economic_chain`, `immediate_value`, `future_value`), plus a `view` sub-object with every derived tooltip value (`compare`, `breakeven`, `home_profit`, `export_profit`, `reward`, `total_value`, `net_savings`, `charge_parts`, `discharge_parts`) |
| `SUMMARY` | Whole-trace totals: `grid_only_cost`, `actual_cost`, `savings`, `cycle_cost`, `capacity`, period counts |

## Common Mistakes

- **Editing `ROWS` values by hand to "fix" a chart.** If a number looks
  wrong, the fix belongs in `core/bess/models.py` (see #350) or the build
  script's field mapping — never patch the rendered JSON.
- **Running the build script from the wrong worktree.** The recompute is
  only meaningful relative to *some* checkout's `core/bess/models.py` — if
  you want to show a specific PR's effect, run it from that PR's worktree,
  not the main checkout.
- **Assuming the bundle's own stored `energy`/`decision` fields for actual
  periods are current.** They're a snapshot from export time; that's the
  entire reason this skill recomputes them instead of reading them directly.
- **Adding a threshold/comparison/formula to `template_tail.js`.** If the
  tooltip needs a new derived number, add it to `compute_decision_view` in
  `build_chart.py` and read it off `r.view` in JS — don't re-derive it from
  raw fields in JavaScript, even for "just this one case."
- **Forgetting `--title`.** Without it the title is auto-generated from
  period counts only (no bundle date/version) — fine for a quick look, but
  add a real title when publishing something you'll want to find again.
