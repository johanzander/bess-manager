# BESS Analyst — Decision-Rationale Expertise (Design Spec)

**Date:** 2026-06-28
**Status:** Approved design, pre-implementation
**Goal:** Make the `bess-analyst` agent a first-attempt, zero-pushback authority on
the optimization algorithm and the economics of price arbitrage.

## Problem

A real dialogue (`docs/dialogue.txt`) shows the analyst failing a single
optimization-rationale question through three escalating errors. The user had to
push back repeatedly; the agent only reached the correct answer after being
corrected step by step. The standard this spec targets is the opposite:
**invoke once, get a correct, complete, authoritative answer, no pushback.**

### Root causes (evidenced)

1. **Narrated over the evidence.** The user asked why the battery sold to grid at
   15:45. The agent answered "it's solar surplus, not the battery." But the debug
   bundle's `### Period Decisions` table already showed `BattAct -0.1`,
   `SOE` dropping, and `Intent = BATTERY_EXPORT` for that period — the agent even
   quoted that exact row in its *second* answer. The decisive fact was present and
   unread on attempt #1.

2. **Gross-value fallacy.** Once it accepted the discharge, it reasoned
   `sell_price 0.46 > wear 0.40 → +6 öre, marginally profitable`. This evaluates
   the action against *doing nothing*. The true counterfactual was "let solar keep
   charging one more slot, start solar-export one slot earlier," whose value is the
   *differential* sell price minus wear: `0.46 − 0.40 − 0.40 = −0.34 SEK/kWh` — a
   loss. The user had to derive this.

3. **Did not know its own code.** The optimizer already implements this opportunity
   cost. `_compute_reward` (`core/bess/dp_battery_algorithm.py:356-389`) raises the
   discharge floor to `sell_price` when solar will replenish the battery, so
   `sell × eff_discharge < sell ≤ floor` ⇒ discharge blocked. The agent claimed the
   mechanism was *missing* and proposed building it (issue #196), when the real,
   legitimate finding is near-threshold `shadow_price` volatility across
   re-optimization runs.

### Meta-cause: the knowledge doc itself is contradictory

`docs/agents/bess-knowledge.md` contains **both**:

- the correct forward-looking framing (lines 69–147: shadow price = opportunity
  value, explicitly *not* the sunk cost basis), buried as a sub-detail of the
  narrow SOLAR_EXPORT gate; and
- a naive contradictory rule (lines 159–163: *"A discharge is profitable when
  sell_price > cost_basis + cycle_cost"*), echoed in the `_compute_reward`
  docstring.

The analyst reached for the simple, wrong one. The correct law is never stated as
**the** governing principle for evaluating *any* action.

### The two-layer shape of the failure

The debug bundle (`core/bess/debug_report_formatter.py`) separates exactly the two
things the agent conflated:

- **Fact layer** — `## Optimization Schedules → ### Period Decisions` table:
  `Intent | Observed | BattAct | SOE start→end | BuyPrice | Savings`. Answers
  *"what happened"* (battery vs solar) from one row.
- **Economic layer** — Full Schedule JSON `<details>` block: `sell_price`,
  `buy_price`, `cost_basis`, `shadow_price`; plus `### Economic Summary`. Answers
  *"why"*.

Both were available on attempt #1.

## Non-Goals

- No canonical/lookup scenario library. There are hundreds of cases; the *law* and
  the *protocol* must generalize, not a memorized example.
- No CI fixture / automated regression test tied to one debug bundle. Validation is
  manual: after the changes, re-run the same question + log against the new
  agent/knowledge and judge the output. (Both the user and the implementer do this.)
- No changes to the optimizer's behavior. This spec changes *documentation and the
  agent's reasoning protocol only*. (Issue #196's shadow-price-volatility fix is a
  separate piece of work.)

## Approved Approach: Layered Decision-Rationale Playbook

Two coordinated changes plus a small output template. Scope covers the **shared**
knowledge doc (so the in-app AI chat benefits too) and the **analyst agent file**
(reasoning discipline, which belongs in the agent and must fire on attempt #1).

### Part 1 — Rewrite the economics in `docs/agents/bess-knowledge.md`

State **one governing law** up front, before any action-specific detail:

> **Every battery action is judged by its *marginal* net value against the
> next-best alternative for that same slot — never gross value, never against
> "do nothing = 0."**
> The opportunity cost of a stored kWh is its forward-looking `shadow_price` (the
> DP's value-to-go slope), floored by `sell_price` when solar will replenish it. It
> is **not** the sunk `cost_basis`, and **not** zero. A discharge to grid is
> worthwhile only if `sell_price × efficiency_discharge >` that opportunity cost.

Changes:

1. **Delete** the naive formula at `bess-knowledge.md:159-163`. Replace with the
   governing law above and the per-action operational forms (charge / discharge /
   hold) derived from it.
2. **Add a note** that `_compute_reward`'s "value > cost_basis" docstring describes
   the *implementation's* anti-cycling floor (which already raises the floor to
   `sell_price`, `dp_battery_algorithm.py:376-389`), not the user-facing economic
   law — so the two are reconciled, not contradictory.
3. **Add a "Facts vs Economics — where each lives in a debug bundle" subsection:**
   - Facts → `### Period Decisions` table (Intent, BattAct sign+magnitude, SOE
     start→end).
   - Economics → Full Schedule JSON `<details>` (sell/buy/cost_basis/shadow_price)
     + `### Economic Summary`.
   - Period ↔ clock-time mapping (15-min slots), with an explicit **off-by-one
     warning** (the dialogue's "15:45 vs 16:00 price" slip).
4. **One short illustrative example** of the reasoning *shape* — clearly labelled
   *"illustrative; the method generalizes to any period — do not pattern-match the
   scenario."* It shows: wrong framing (`sell > wear → profit`) vs right framing
   (state the counterfactual → marginal value → `shadow_price` vs `sell`). Its job
   is to make the abstract gross-vs-marginal law transfer to the model, not to be a
   lookup case.

### Part 2 — Add a Decision-Rationale Protocol to `.claude/agents/bess-analyst.md`

The current process is built for "something is broken / discovery / sensor"
questions and has **no** path for "why did the optimizer decide X." Add:

**A routing step at the top:**
- (A) Broken / discovery / sensors / integration → existing process.
- (B) Why did the optimizer decide X / is decision X correct / savings rationale →
  Decision-Rationale Protocol below.

**The Decision-Rationale Protocol (mandatory, ordered, each step checkable):**

1. **Pin the period.** Convert the clock time in the question to period number +
   slot; state both; guard the off-by-one.
2. **Facts before narrative.** Read that period's `### Period Decisions` row; quote
   Intent, BattAct (sign + magnitude), SOE start→end; answer the literal "what
   happened" (battery vs solar) from this row *alone*. No mechanism yet.
3. **Pull economics.** Quote sell/buy/cost_basis/shadow_price from Full Schedule
   JSON for that period + relevant `### Economic Summary` totals.
4. **Apply the governing law.** State the counterfactual explicitly ("the
   alternative to this action was ___"), compute marginal value vs it using
   opportunity cost = `shadow_price` (floored by `sell_price` under solar
   replenishment); verdict: correct / incorrect / marginal-and-why.
5. **Cite the code path.** Name the exact function/lines that produced the decision
   (`_compute_reward` discharge gate `dp_battery_algorithm.py:356-389`;
   cost_basis/shadow_price). No claim without a code or data anchor.
6. **Cross-run reconciliation.** If the user references multiple runs or "it
   changed," diff the period's economics across the runs in the bundle and attribute
   the change to a specific input delta (initial SOC / price update / forecast).
7. **Self-check gate before emitting.** Verify: (a) every factual claim matches the
   quoted row; (b) a counterfactual was stated and marginal — not gross — value was
   used; (c) the mechanism has a code/data anchor; (d) the literal question is
   answered. Any miss → redo, do not emit.

**Anti-pattern list (verbatim from the dialogue failures):**
- Don't answer "solar surplus vs battery" from a narrative — read BattAct/SOE first.
- Never call a discharge profitable because `sell_price > wear_cost`. That's gross
  value; compute marginal value vs the counterfactual.
- Never claim a mechanism is "missing" before grepping the optimizer for it (e.g.,
  the anti-cycling floor already exists).

### Part 3 — Output template

Add a "Decision rationale" output format mirroring the protocol so answers are
auditable: **Facts → Economics → Counterfactual & verdict → Code anchor →
(cross-run note).**

### Part 4 — Correct contradictory in-code documentation

Comment/docstring-only changes, **no behavior change**. The implementation must
audit in-code documentation that states the economics and correct any that carry
the naive gross-value framing so code and docs agree on the one governing law:

- `_compute_reward` docstring (`core/bess/dp_battery_algorithm.py`, ~lines 262-284):
  the "PROFITABILITY CHECK … Discharge only profitable if this value > cost_basis"
  text. Reword to describe the opportunity-cost floor the code actually applies
  (floor raised to `sell_price` under replenishment, `dp_battery_algorithm.py:376-389`).
- The module-level docstring's profitability/threshold description (~lines 19-50)
  and the inline anti-cycling comments — confirm they match the governing law;
  correct any wording that implies gross value or `cost_basis`-only reasoning.
- Grep the rest of `core/bess/` (`decision_intelligence.py`, `models.py`) for the
  same framing in comments/docstrings and fix wording where it contradicts the law.

These are documentation corrections only — do not alter any computation.

## Files Touched

- `docs/agents/bess-knowledge.md` — rewrite economics section (Part 1).
- `.claude/agents/bess-analyst.md` — routing step, protocol, anti-patterns, output
  template (Parts 2 & 3).
- `core/bess/dp_battery_algorithm.py` — docstring/comment corrections only (Part 4).
- Any other `core/bess/` file whose comments/docstrings carry the naive framing
  (Part 4) — comment-only.

## Part 5 — Surface conclusions at the top of the debug bundle (added after validation)

Validation runs proved the knowledge/protocol fixes are necessary but not
sufficient: a Sonnet agent reliably anchors on the *latest* run and on the green
health snapshot, ignoring contradicting evidence buried in the raw logs — even an
explicit "STEP 0 MANDATORY" tool instruction. The durable fix is **structural**:
pre-digest the conclusions and put them first; demote raw data to the bottom.

**Restructure the bundle and the AI-chat context into three tiers:**

1. **Top — always-on `Key Findings` section** (auto-generated, conclusion-phrased):
   - **Cross-run schedule reconciliation:** per-slot disagreements computed from
     `schedule_store.get_all_schedules_today()` (already serialized into
     `export.schedules` as all runs). Phrased imperatively ("DISAGREEMENT @ 15:45:
     earlier runs BATTERY_EXPORT, latest SOLAR_EXPORT — explain why; do not conclude
     it didn't happen").
   - **Today's log-anomaly rollup:** parsed from `export.todays_log_content`,
     **categorized and deduplicated** by `(category, module:line)` — categories:
     network/connectivity, data gaps (skipped periods / missing actuals), restarts,
     runtime errors. Each entry = category · deduped count · first→last timestamp ·
     one sample. Raw counts over-count (e.g. 220 "restart" hits are one repeated
     warning string), so dedup is required. Derived from logs, NOT the runtime
     failure tracker (which isn't exported and is unreliable).
   - Self-suppressing: shows "No anomalies or disagreements detected" when clean.
   - The existing health snapshot stays but is captioned **point-in-time** so its
     green "OK" is never read as "nothing went wrong today."

2. **Middle — structured reference** (settings, latest schedule, economics, entity
   snapshot): unchanged, read on demand.

3. **Bottom — raw data for deep digging** (`## System Logs`, full schedule JSON
   `<details>`): moved to the end.

**Shared computation, two renderers** (no duplicated logic): a new
`core/bess/debug_findings.py` produces the findings from structured data + log text;
`debug_report_formatter.py` renders the markdown section; `backend/ai_chat.py`
`_gather_context` includes the same findings and **excludes the raw log dump**
(fewer tokens, better answers). The standalone `scripts/extract_decision_evidence.py`
remains a manual CLI.

## Validation

Manual, by re-invoking the agent (no baked fixture). After the changes, run the
original `docs/dialogue.txt` question against a representative debug bundle and
confirm the agent, on the **first attempt**, without pushback:
1. identifies a battery discharge (BattAct negative, SOE drop), not solar surplus;
2. rejects the gross "6 öre" framing and gives the marginal verdict
   (`shadow_price > sell_price` ⇒ a loss to discharge);
3. cites `_compute_reward`;
4. names cross-run shadow-price volatility as the real issue.

This is a judgement check on representative cases, not a pinned regression test.
