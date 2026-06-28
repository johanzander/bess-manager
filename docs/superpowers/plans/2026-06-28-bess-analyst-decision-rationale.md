# BESS Analyst Decision-Rationale Expertise — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `bess-analyst` agent answer optimization-rationale questions
correctly and completely on the first invocation, by fixing the economics
knowledge it relies on and giving it a mandatory evidence-first reasoning protocol.

**Architecture:** Documentation + agent-prompt changes only, in three layers:
(1) rewrite the economics in the shared knowledge doc to one governing
opportunity-cost law; (2) add a routing step + ordered Decision-Rationale Protocol
to the agent file; (3) correct contradictory in-code docstrings so code and docs
agree. No optimizer behavior changes.

**Tech Stack:** Markdown (knowledge doc, agent file), Python docstrings/comments
(`core/bess/`). No new dependencies.

## Global Constraints

- **No behavior change to the optimizer.** Part 4 edits are comment/docstring-only.
  Do not alter any computation in `core/bess/`.
- **One governing law, stated verbatim** everywhere economics are described: *an
  action's value is its marginal net value vs the next-best alternative; the
  opportunity cost of a stored kWh is its forward-looking `shadow_price` (floored by
  `sell_price` under solar replenishment), never the sunk `cost_basis`, never zero.*
- **No canonical scenario library, no CI fixture.** The single illustrative example
  must be labelled non-canonical. Validation is a manual agent re-run.
- Run `./scripts/quality-check.sh` before any commit that touches `core/bess/`
  (per repo convention — Black formatting is the most common CI failure).
- Spec: `docs/superpowers/specs/2026-06-28-bess-analyst-decision-rationale-design.md`.

---

## File Structure

- `docs/agents/bess-knowledge.md` — economics section rewritten (Task 1). Shared by
  the in-app AI chat and the analyst agent.
- `.claude/agents/bess-analyst.md` — routing step, Decision-Rationale Protocol,
  anti-patterns, output template (Task 2).
- `core/bess/dp_battery_algorithm.py` — docstring/comment corrections (Task 3).
- Other `core/bess/` files (`decision_intelligence.py`, `models.py`) — comment-only
  corrections if the grep in Task 3 finds the naive framing.

---

### Task 1: Rewrite the economics in the knowledge doc

**Files:**
- Modify: `docs/agents/bess-knowledge.md` (delete lines 159-163; add governing-law
  section, facts-vs-economics map, illustrative example)

**Interfaces:**
- Produces: the canonical wording of the governing law that Task 2 (agent protocol)
  and Task 3 (code docstrings) must match verbatim.

- [ ] **Step 1: Delete the contradictory naive formula.**

Remove this block (currently `bess-knowledge.md:159-163`):

```
A discharge is profitable when:
    sell_price (or avoided buy_price) > cost_basis + cycle_cost

Where cost_basis is the price at which the energy was originally stored
(tracked via FIFO), and cycle_cost is the battery wear cost per kWh.
```

- [ ] **Step 2: Add the governing-law section.**

Insert a new section immediately after `## The Dynamic Programming Algorithm`
(before `## Strategic Intents`):

```markdown
## The Governing Economic Law (read this first)

Every battery action is judged by its **marginal net value against the next-best
alternative for that same slot** — never by its gross value, and never against
"do nothing = 0".

The opportunity cost of a stored kWh is its **forward-looking `shadow_price`** (the
DP's value-to-go slope), floored by `sell_price` when upcoming solar will replenish
the battery for free. It is **not** the sunk `cost_basis`, and **not** zero.

Operational forms of the one law:

- **Discharge to grid** is worthwhile only if
  `sell_price × efficiency_discharge > opportunity_cost_of_stored_kWh`.
- **Discharge to cover home load** is worthwhile only if it beats the cheapest
  alternative for that kWh (usually a future avoided import at a higher buy price).
- **Charge** is worthwhile only if the stored kWh's future value exceeds what it
  cost to store it (grid/solar cost + wear).

The classic error this prevents: treating `sell_price > wear_cost` as "profitable".
That compares gross sale value to wear and ignores the counterfactual. If the real
alternative is "let solar keep charging one more slot and export one slot earlier",
the value captured is only the **differential** in sell price between the two slots,
which must still clear the wear cost. A 6 öre differential against a 40 öre wear
cost is a loss, not a 6 öre gain.

**Reconciliation with the code:** `_compute_reward`
(`core/bess/dp_battery_algorithm.py:356-389`) implements this as an anti-cycling
floor — for a discharge it raises the effective floor to `sell_price` whenever solar
will replenish the discharged capacity, so `sell × efficiency_discharge < sell ≤
floor` blocks the trade. The function's older docstring phrasing ("value >
cost_basis") describes that floor's implementation, not the user-facing law above.
```

- [ ] **Step 3: Add the facts-vs-economics bundle map.**

Append this subsection to the new section (or directly after it):

```markdown
### Facts vs Economics — where each lives in a debug bundle

Answer "what happened" and "why" from different parts of the bundle, in that order:

- **Facts (what happened):** `## Optimization Schedules → ### Period Decisions`
  table. Columns: `Intent | Observed | BattAct | SOE start→end | BuyPrice |
  Savings`. A negative `BattAct` with a falling `SOE` is a battery discharge — read
  this before proposing any mechanism. Solar-only export shows `BattAct ≈ 0`.
- **Economics (why):** the Full Schedule JSON `<details>` block — `sell_price`,
  `buy_price`, `cost_basis`, `shadow_price` per period — plus `### Economic Summary`.
- **Period ↔ clock time:** slots are 15 minutes. Map the question's clock time to a
  period number and confirm it. Watch the off-by-one: the price shown for 15:45 is
  the 15:45 slot's price, not 16:00's.
```

- [ ] **Step 4: Add the single illustrative example.**

Append:

```markdown
### Illustrative: applying the law (method demo, not a lookup)

*Illustrative only — the method generalizes to any period. Do not pattern-match the
scenario; reproduce the reasoning steps.*

A battery discharges a small amount to grid in a slot where `sell = 0.46`,
`wear = 0.40`.

- **Wrong (gross):** `0.46 > 0.40 → +6 öre, profitable.`
- **Right (marginal):** the alternative is to let solar charge one more slot and
  export one slot earlier, so only the sell-price *differential* (~0.06) is gained,
  against 0.40 wear ⇒ ≈ `−0.34 SEK/kWh`, a loss. Equivalently: `shadow_price` (e.g.
  0.876) and `cost_basis` (e.g. 0.62) both exceed `sell 0.46`, so the stored kWh is
  worth more kept than exported ⇒ do not discharge.
- If different optimization runs disagree on such a near-threshold slot, the cause
  is `shadow_price` sensitivity across re-optimizations, not a missing mechanism.
```

- [ ] **Step 5: Verify the doc is internally consistent.**

Run: `grep -n "profitable when\|cost_basis + cycle_cost\|shadow_price\|Governing Economic Law" docs/agents/bess-knowledge.md`
Expected: the deleted naive formula no longer appears; the governing-law section and
shadow_price references are present.

- [ ] **Step 6: Commit.**

```bash
git add docs/agents/bess-knowledge.md
git commit -m "docs: state one governing opportunity-cost law in bess-knowledge"
```

---

### Task 2: Add the Decision-Rationale Protocol to the agent

**Files:**
- Modify: `.claude/agents/bess-analyst.md` (add routing step before "Analysis
  Process"; add protocol, anti-patterns, output template)

**Interfaces:**
- Consumes: the governing-law wording from Task 1 (reference it, do not restate a
  different version).

- [ ] **Step 1: Add a question-routing step.**

Insert immediately before `## Analysis Process`:

```markdown
## FIRST: Route the question

Classify before doing anything else:

- **(A) Something is broken / discovery / sensors / integration** → use the
  Analysis Process below.
- **(B) Why did the optimizer decide X / is decision X correct / savings
  rationale** → use the **Decision-Rationale Protocol** below. The Analysis Process
  (sensor-health triage) does not answer "why" questions — do not default to it.
```

- [ ] **Step 2: Add the Decision-Rationale Protocol.**

Insert after the routing step:

```markdown
## Decision-Rationale Protocol (for type-B questions)

The governing economic law is in `docs/agents/bess-knowledge.md` — read it first.
Then follow these steps in order. Each step is checkable; do not skip ahead.

1. **Pin the period.** Convert the clock time in the question to a period number and
   slot; state both. Guard the off-by-one (15-min slots).
2. **Facts before narrative.** Read that period's row in `### Period Decisions`.
   Quote `Intent`, `BattAct` (sign + magnitude), and `SOE start→end`. Answer the
   literal "what happened" (battery discharge vs solar surplus) from this row
   alone. Do not propose a mechanism yet. A negative `BattAct` with falling `SOE`
   IS a battery discharge — never call it solar surplus.
3. **Pull the economics.** From the Full Schedule JSON for that period, quote
   `sell_price`, `buy_price`, `cost_basis`, `shadow_price`. Add relevant totals from
   `### Economic Summary`.
4. **Apply the governing law.** State the counterfactual explicitly ("the
   alternative to this action was ___"). Compute marginal value vs that
   counterfactual using opportunity cost = `shadow_price` (floored by `sell_price`
   under solar replenishment). Verdict: correct / incorrect / marginal-and-why.
   Never use gross value.
5. **Cite the code path.** Name the exact function/lines that produced the decision
   (e.g. the discharge gate in `_compute_reward`,
   `core/bess/dp_battery_algorithm.py:356-389`; cost_basis/shadow_price handling).
   No claim without a code or data anchor.
6. **Cross-run reconciliation.** If the user references multiple runs or "it
   changed", diff the period's economics across the runs in the bundle and attribute
   the change to a specific input delta (initial SOC / price update / forecast).
7. **Self-check gate before emitting.** Confirm: (a) every factual claim matches the
   quoted table row; (b) you stated a counterfactual and used marginal — not gross —
   value; (c) the mechanism has a code/data anchor; (d) you answered the literal
   question. Any miss → redo. Do not emit until all four hold.

### Anti-patterns (do not do these)

- Answering "solar surplus vs battery" from a narrative instead of reading
  `BattAct`/`SOE` first.
- Calling a discharge profitable because `sell_price > wear_cost`. That is gross
  value; compute marginal value vs the counterfactual.
- Claiming a mechanism is "missing" before grepping the optimizer for it (e.g. the
  anti-cycling floor already exists in `_compute_reward`).
```

- [ ] **Step 3: Add the decision-rationale output template.**

Append to the `## Output Format` section:

```markdown
### For type-B (decision-rationale) answers, use this shape:

1. **Facts** — period, Intent, BattAct, SOE start→end (quoted from the table).
2. **Economics** — sell/buy/cost_basis/shadow_price for the period.
3. **Counterfactual & verdict** — the stated alternative, the marginal value vs it,
   and correct / incorrect / marginal.
4. **Code anchor** — the function/lines that produced the decision.
5. **Cross-run note** — only if the user referenced multiple runs.
```

- [ ] **Step 4: Verify the agent file.**

Run: `grep -n "Route the question\|Decision-Rationale Protocol\|Anti-patterns\|Counterfactual" .claude/agents/bess-analyst.md`
Expected: routing step, protocol, anti-patterns, and output template all present.

- [ ] **Step 5: Commit.**

```bash
git add .claude/agents/bess-analyst.md
git commit -m "docs: add evidence-first decision-rationale protocol to bess-analyst"
```

---

### Task 3: Correct contradictory in-code documentation

**Files:**
- Modify: `core/bess/dp_battery_algorithm.py` (docstring/comments only)
- Modify (if grep hits): `core/bess/decision_intelligence.py`, `core/bess/models.py`

**Interfaces:**
- Consumes: the governing-law wording from Task 1.

- [ ] **Step 1: Find all naive-framing docstrings/comments.**

Run: `grep -rn "profitable if\|value > cost_basis\|sell_price > cost_basis\|profitability" core/bess/dp_battery_algorithm.py core/bess/decision_intelligence.py core/bess/models.py`
Expected: hits in the `_compute_reward` docstring (~lines 262-284) and possibly the
module docstring (~lines 19-50). Note every hit before editing.

- [ ] **Step 2: Reword the `_compute_reward` docstring.**

In `core/bess/dp_battery_algorithm.py`, replace the `PROFITABILITY CHECK` paragraph
of the `_compute_reward` docstring so it describes the opportunity-cost floor the
code actually applies. New text:

```
    PROFITABILITY CHECK (opportunity-cost floor):
    - A discharge is worthwhile only if its value beats the opportunity cost of
      the stored kWh — not its sunk cost basis and not zero.
    - Value = max(avoided grid purchase, grid export revenue), after discharge
      efficiency.
    - The effective floor is raised to sell_price whenever upcoming solar will
      replenish the discharged capacity (replenishment): the kWh could be exported
      later, so sell_price is its true replacement cost. Since
      sell_price * efficiency_discharge < sell_price, marginal round-trip and
      refill trades are correctly blocked.
```

Keep the numeric example below it; it is still valid.

- [ ] **Step 3: Reconcile the module docstring and inline comments.**

Read the module docstring (~lines 19-50) and the inline anti-cycling comments
(~lines 361-375). Where wording implies gross value or `cost_basis`-only reasoning,
adjust it to match the governing law. Do not change any code or numbers.

- [ ] **Step 4: Fix any other files flagged by Step 1.**

For each hit in `decision_intelligence.py` / `models.py`, correct comment/docstring
wording to match the governing law. Comment-only; no logic changes.

- [ ] **Step 5: Verify no behavior changed.**

Run: `git diff --stat core/bess/` (confirm only the intended files changed) and
`./scripts/quality-check.sh`
Expected: quality check passes; diff shows comment/docstring lines only.

- [ ] **Step 6: Commit.**

```bash
git add core/bess/
git commit -m "docs: align optimizer docstrings with the governing opportunity-cost law"
```

---

### Task 4: Validate via manual agent re-run

**Files:** none (validation only).

- [ ] **Step 1: Re-invoke the analyst on a representative bundle.**

Using a real debug bundle (e.g. `bess-debug-2026-06-28-113159.md` referenced in
`docs/dialogue.txt`, or any current bundle), invoke the `bess-analyst` agent with
the original question from `docs/dialogue.txt` (the 15:45 battery-export question).

- [ ] **Step 2: Confirm first-attempt correctness, no pushback.**

The answer must, on the first attempt:
1. identify a battery discharge (negative `BattAct`, falling `SOE`), not solar surplus;
2. reject the gross "6 öre" framing and give the marginal verdict
   (`shadow_price > sell_price` ⇒ discharging is a loss);
3. cite `_compute_reward`;
4. name cross-run `shadow_price` volatility as the real issue.

If it fails any point, capture which step of the protocol was skipped and refine the
relevant doc/agent wording (Tasks 1-2), then re-run. This is a judgement check on
representative cases, not a pinned regression test.

---

## Self-Review

- **Spec coverage:** Part 1 → Task 1; Parts 2 & 3 → Task 2; Part 4 → Task 3;
  Validation → Task 4. All spec sections covered.
- **Placeholder scan:** no TBD/TODO; every doc edit shows the actual text to insert.
- **Consistency:** the governing-law wording is authored once in Task 1 and
  referenced (not re-forked) by Tasks 2 and 3; the `_compute_reward:356-389` anchor
  is used identically in the knowledge doc, the agent protocol, and the validation.
