# Controller Lifecycle Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop recreating `InverterController` every optimization cycle. Each of the 4 subclasses becomes a single long-lived instance per platform selection; hardware-derived state (VPP confirmation, TOU mode tracking) is never reset because the object holding it is never rebuilt. Replaces `create_schedule`/`compare_schedules`/`seed_from` with a platform-neutral `apply_intents`/`evaluate_intents` interface backed by one shared `_build_candidate` helper per subclass, so "would this differ" and "commit this" can never silently drift apart.

**Architecture:** Migration uses an expand-contract pattern to keep every task independently green: each subclass task (2-5) adds new methods (`_build_candidate`, `apply_intents`, `evaluate_intents`) while keeping the old methods (`create_schedule`, `compare_schedules`) as thin backward-compatible wrappers, so `BatterySystemManager` and existing tests keep passing unmodified until Task 6 switches the call sites over. Task 7 deletes the old names, `seed_from`, and the `temp_growatt`-era tests, and makes the new methods properly abstract on the base class.

**Tech Stack:** Python 3.12, pytest, existing `InverterController` class hierarchy in `core/bess/`.

## Global Constraints

- No behavior change to what schedule gets applied or when — this is an architectural refactor. Acceptance criterion: identical applied schedules across all pinned scenario fixtures (`core/bess/tests/unit/test_min_schedule_e2e.py`, `test_scenarios.py`), only the redundant-write pattern changes.
- One exception, disclosed not hidden: `GrowattMinController`'s corruption-forced-apply check moves from reading a possibly-stale flag on the about-to-be-replaced controller to reading it on the single persistent controller right after `_build_candidate` recomputes it from that same controller's real current `tou_intervals` — strictly more correct, not a regression (see Task 2, Step 6).
- `previous_tou_intervals` parameter (on `create_schedule` today) is dead code in every subclass — confirmed via grep, never read in any method body, and `SolaxController`/`SolaxModbusGrowattController` already docstring it as "Unused". Drop it; not a behavior change.
- Run `.venv/bin/pytest -m "not slow"` after every task; run the full suite (`-m slow` too) before Task 7's final commit.
- Follow `docs/agents/workflow.md` commit format (subject + blank line + body explaining WHY) for every commit.

---

### Task 1: Mechanical rename — `write_schedule_to_hardware` → `write_to_hardware`

Pure rename, no logic change, across the abstract base method, all 4 subclass overrides, the one `BatterySystemManager` call site, and every test reference. Done first and separately because it's zero-risk and shouldn't be mixed with the real logic changes in later tasks.

**Files:**
- Modify: `core/bess/inverter_controller.py` (abstract method, ~line 480)
- Modify: `core/bess/growatt_min_controller.py`, `core/bess/growatt_sph_controller.py`, `core/bess/solax_controller.py`, `core/bess/solax_modbus_growatt_controller.py` (each subclass's override)
- Modify: `core/bess/battery_system_manager.py` (`_apply_schedule`, the one call site)
- Modify test files that reference `write_schedule_to_hardware`

**Interfaces:**
- Produces: `InverterController.write_to_hardware(controller, effective_period, current_tou) -> tuple[int, int]` — identical signature and behavior to today's `write_schedule_to_hardware`, name only.

- [ ] **Step 1: Find every reference**

```bash
grep -rln "write_schedule_to_hardware" core/bess/*.py core/bess/tests/unit/*.py
```

- [ ] **Step 2: Rename in each file**

In `core/bess/inverter_controller.py`, `core/bess/growatt_min_controller.py`, `core/bess/growatt_sph_controller.py`, `core/bess/solax_controller.py`, `core/bess/solax_modbus_growatt_controller.py`, and `core/bess/battery_system_manager.py`: replace every occurrence of `write_schedule_to_hardware` with `write_to_hardware` (method definition, the one call site in `battery_system_manager.py`'s `_apply_schedule`, and docstrings that name it). Use your editor's find-and-replace per file — this is a literal identifier rename, no other text on any of these lines changes.

Also update the docstring on the abstract method in `inverter_controller.py`:

```python
    @abstractmethod
    def write_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Write schedule to inverter hardware.

        Returns:
            Tuple of (writes, disables)
        """
```

- [ ] **Step 3: Rename in tests**

Repeat the same literal find-and-replace of `write_schedule_to_hardware` → `write_to_hardware` in every test file the Step 1 grep listed (call sites like `controller.write_schedule_to_hardware(mock_ha, ...)` become `controller.write_to_hardware(mock_ha, ...)`).

- [ ] **Step 4: Run full fast suite**

```bash
.venv/bin/pytest -m "not slow" -q
```
Expected: same pass count as baseline (1236 passed, 14 skipped), 0 failures — this step is a pure rename so nothing should change.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: rename write_schedule_to_hardware to write_to_hardware

Naming-only step ahead of the controller-lifecycle refactor (#369) --
"schedule" implies a persisted hardware object, which is only true for
TOU/SPH platforms and actively misleading for VPP/SolaX-style ephemeral
control. No behavior change.
EOF
)"
```

---

### Task 2: `GrowattMinController` — extract `_build_candidate`, add `apply_intents`/`evaluate_intents`

The one subclass with genuinely non-trivial candidate computation (TOU-interval building from period grouping). Keeps `create_schedule`/`compare_schedules` as thin wrappers so `BatterySystemManager` and the existing 35+ tests in `test_growatt_tou_scheduling.py` (which call `_consolidate_and_convert_with_strategic_intents()` directly) are untouched and stay green.

**Files:**
- Modify: `core/bess/growatt_min_controller.py`
- Test: `core/bess/tests/unit/test_controller_coverage.py` (has the `compare_schedules` tests for this controller — add new `evaluate_intents` tests alongside, don't delete the old ones yet)

**Interfaces:**
- Consumes: `DPSchedule.original_dp_results["strategic_intent"] -> list[str]` (existing).
- Produces: `_build_candidate(intents: list[str], current_period: int) -> tuple[list[dict], list[dict]]` (new tou_intervals, new active_tou_intervals — used internally and by Task 6/7 callers later); `apply_intents(schedule: DPSchedule, current_period: int) -> None`; `evaluate_intents(schedule: DPSchedule, current_period: int = 0) -> tuple[bool, str]`.

- [ ] **Step 1: Write the failing test for `_build_candidate` purity**

Add to `core/bess/tests/unit/test_growatt_tou_scheduling.py` (near the top, after existing fixtures):

```python
class TestBuildCandidate:
    """_build_candidate must not mutate self.tou_intervals/self.strategic_intents —
    it's the shared computation both evaluate_intents and apply_intents call."""

    def test_does_not_mutate_self_state(self, scheduler):
        scheduler.strategic_intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        scheduler.tou_intervals = ["sentinel"]

        candidate_intents = hourly_to_quarterly({5: "BATTERY_EXPORT"})
        new_intervals, new_active = scheduler._build_candidate(
            candidate_intents, current_period=0
        )

        assert scheduler.tou_intervals == ["sentinel"]
        assert scheduler.strategic_intents == hourly_to_quarterly(
            {2: "GRID_CHARGING"}
        )
        assert new_intervals != ["sentinel"]
        assert isinstance(new_active, list)

    def test_matches_consolidate_and_convert_output(self, scheduler):
        """The extracted candidate builder must produce byte-identical output
        to the existing (untouched) mutator, for the same intents."""
        intents = hourly_to_quarterly(
            {2: "GRID_CHARGING", 10: "BATTERY_EXPORT", 18: "LOAD_SUPPORT"}
        )
        scheduler.strategic_intents = intents
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)
        expected_intervals = [i.copy() for i in scheduler.tou_intervals]
        expected_active = [i.copy() for i in scheduler.active_tou_intervals]

        # Reset and rebuild via the new pure path
        scheduler.tou_intervals = []
        scheduler.active_tou_intervals = []
        candidate_intervals, candidate_active = scheduler._build_candidate(
            intents, current_period=0
        )

        assert candidate_intervals == expected_intervals
        assert candidate_active == expected_active
```

(`scheduler` and `hourly_to_quarterly` are existing fixtures/helpers already in this test file — reuse them, don't redefine.)

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_scheduling.py::TestBuildCandidate -v
```
Expected: FAIL with `AttributeError: 'GrowattMinController' object has no attribute '_build_candidate'`.

- [ ] **Step 3: Parameterize `_group_periods_by_mode` to accept intents explicitly**

In `core/bess/growatt_min_controller.py`, change the signature at line 163 and its one internal reference to `self.strategic_intents`:

```python
    def _group_periods_by_mode(
        self, intents: list[str], start_period: int = 0
    ) -> list[dict]:
        """Group consecutive 15-min periods by their battery mode.

        This is the core of the new 15-minute resolution TOU scheduling.
        Instead of aggregating to hours, we work directly with periods.

        Args:
            intents: Strategic intents to group (the candidate being built —
                may be self.strategic_intents, or a different candidate's
                intents when called from _build_candidate for comparison).
            start_period: Period to start from (0-95), typically current_period

        Returns:
            List of period groups:
            [
                {
                    'mode': 'battery_first'|'grid_first'|'load_first',
                    'start_period': int,
                    'end_period': int (inclusive),
                    'intents': list[str],  # Original intents for debugging
                },
                ...
            ]
        """
        if not intents:
            return []

        groups = []
        current_mode = None
        group_start = None
        group_intents = []

        num_periods = len(intents)

        for period in range(start_period, num_periods):
            intent = intents[period]
            mode = self.INTENT_TO_MODE.get(intent, "load_first")

            if mode != current_mode:
                # Save previous group if exists
                if current_mode is not None:
                    groups.append(
                        {
                            "mode": current_mode,
                            "start_period": group_start,
                            "end_period": period - 1,
                            "intents": group_intents,
                        }
                    )

                # Start new group
                current_mode = mode
                group_start = period
                group_intents = [intent]
            else:
                group_intents.append(intent)

        # Add final group
        if current_mode is not None and group_start is not None:
            groups.append(
                {
                    "mode": current_mode,
                    "start_period": group_start,
                    "end_period": num_periods - 1,
                    "intents": group_intents,
                }
            )

        return groups
```

- [ ] **Step 4: Add `_build_candidate`, delegate `_consolidate_and_convert_with_strategic_intents` to it**

Replace the body of `_consolidate_and_convert_with_strategic_intents` (currently lines 455-546) with:

```python
    def _build_candidate(
        self, intents: list[str], current_period: int = 0
    ) -> tuple[list[dict], list[dict]]:
        """Compute what tou_intervals/active_tou_intervals WOULD be for the
        given intents, without mutating self.tou_intervals/self.active_tou_intervals.

        Shared by apply_intents (commits the result onto self) and
        evaluate_intents (diffs the result against self's currently-applied
        state) -- one computation, so they can never silently drift apart.

        Exception to purity: reads self.tou_intervals (current committed
        state, unchanged by this call) to check for corruption, and DOES set
        self.corruption_detected as an accepted diagnostic side effect (see
        docs/superpowers/specs/2026-07-23-controller-lifecycle-refactor-design.md).
        """
        logger.info(
            "Converting %d strategic intents to TOU intervals using 15-minute resolution",
            len(intents),
        )

        # Check for corrupted existing intervals (self's real current state)
        if self.tou_intervals:
            intervals_valid = self.validate_tou_intervals_ordering(
                self.tou_intervals, "before_strategic_intent_conversion"
            )
            if not intervals_valid:
                logger.warning(
                    "TOU RECOVERY: Existing intervals are corrupted, clearing and rebuilding"
                )
                for interval in self.tou_intervals:
                    logger.warning(
                        "  Corrupted: Segment %s: %s-%s %s",
                        interval.get("segment_id", "?"),
                        interval.get("start_time", "?"),
                        interval.get("end_time", "?"),
                        interval.get("batt_mode", "?"),
                    )
                self.corruption_detected = True
                logger.warning("CORRUPTION FLAG SET - Hardware write will be FORCED")

        # Group periods by mode from current_period (rolling window)
        period_groups = self._group_periods_by_mode(intents, current_period)

        logger.info(
            "Grouped %d periods into %d mode groups",
            len(intents),
            len(period_groups),
        )

        for group in period_groups:
            start_h, start_m = self._period_to_time(group["start_period"])
            end_h, end_m = self._period_to_time(group["end_period"])
            end_m += 14
            logger.debug(
                "Mode group: %s from %02d:%02d to %02d:%02d (%d periods)",
                group["mode"],
                start_h,
                start_m,
                end_h,
                end_m,
                len(group["intents"]),
            )

        new_intervals = self._groups_to_tou_intervals(period_groups)
        new_intervals.sort(key=lambda x: x["start_time"])
        for i, interval in enumerate(new_intervals, 1):
            interval["segment_id"] = i

        active = self._select_hardware_intervals(new_intervals, current_period)

        logger.info(
            "TOU conversion complete: %d total intervals, %d selected for hardware",
            len(new_intervals),
            len(active),
        )

        return new_intervals, active

    def _consolidate_and_convert_with_strategic_intents(self, current_period: int = 0):
        """Unchanged public behavior: mutates self.tou_intervals/active_tou_intervals
        from self.strategic_intents. Delegates to _build_candidate, shared with
        apply_intents/evaluate_intents, so there is one computation, not two."""
        if not self.strategic_intents:
            raise ValueError(
                "No strategic intents available — cannot convert to TOU intervals"
            )
        new_intervals, active = self._build_candidate(
            self.strategic_intents, current_period
        )
        self.tou_intervals = new_intervals
        self.active_tou_intervals = active
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_growatt_tou_scheduling.py -v
```
Expected: PASS, including the two new `TestBuildCandidate` tests and all ~35 pre-existing tests in this file unchanged.

- [ ] **Step 6: Add `apply_intents`/`evaluate_intents`, keep `create_schedule`/`compare_schedules` as compat wrappers**

Replace `create_schedule` (currently lines 415-453) with:

```python
    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list, rebuilding TOU intervals from it."""
        logger.info(
            "Creating Growatt schedule using strategic intents from DP algorithm"
        )

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]

        logger.info(
            f"Using {len(self.strategic_intents)} strategic intents from DP algorithm (quarterly resolution)"
        )

        for period in range(max(1, current_period), len(self.strategic_intents)):
            if self.strategic_intents[period] != self.strategic_intents[period - 1]:
                logger.info(
                    "Intent transition at period %d: %s → %s",
                    period,
                    self.strategic_intents[period - 1],
                    self.strategic_intents[period],
                )

        self.current_schedule = schedule
        self._consolidate_and_convert_with_strategic_intents(current_period)

        logger.info(
            "New Growatt schedule created with %d TOU intervals (%d active for hardware)",
            len(self.tou_intervals),
            len(self.active_tou_intervals),
        )

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Deprecated alias for apply_intents — removed in Task 7."""
        self.apply_intents(schedule, current_period)
```

Add `_format_daily_tou` and rewrite `get_daily_TOU_settings` to use it (find `get_daily_TOU_settings` around line 781):

```python
    def _format_daily_tou(self, intervals: list[dict]) -> list[dict]:
        """Truncate to max_intervals and fill in segment_id where missing.
        Shared by get_daily_TOU_settings (self's committed intervals) and
        evaluate_intents (a candidate's intervals) -- one formatting rule."""
        if not intervals:
            return []

        result = []
        for interval in intervals[: self.max_intervals]:
            segment = interval.copy()
            if "segment_id" not in segment:
                segment["segment_id"] = len(result) + 1
            result.append(segment)

        return result

    def get_daily_TOU_settings(self):
        """Get Growatt-specific TOU settings for all battery modes."""
        return self._format_daily_tou(self.tou_intervals)
```

Replace `compare_schedules` (currently lines 581-717, ending at the `return False, ""` before the next method) with `evaluate_intents` plus a thin `compare_schedules` wrapper:

```python
    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare TOU intervals a candidate schedule would produce against
        what's currently applied, from a specific period onwards.

        Uses 15-minute period granularity to match TOU segment resolution.
        """
        from_period = current_period
        from_hour = from_period // 4
        from_min_in_hour = (from_period % 4) * 15

        logger.info(
            "Comparing TOU intervals from period %d (%02d:%02d) onwards",
            from_period,
            from_hour,
            from_min_in_hour,
        )

        candidate_intents = schedule.original_dp_results["strategic_intent"]
        candidate_intervals, _active = self._build_candidate(
            candidate_intents, current_period
        )

        # CRITICAL: If corruption was detected (by the _build_candidate call
        # just above, reading self's real current tou_intervals), force
        # hardware write regardless of comparison.
        if self.corruption_detected:
            logger.warning(
                "⚠️  CORRUPTION DETECTED FLAG IS SET - FORCING HARDWARE WRITE"
            )
            logger.warning(
                "This overrides normal schedule comparison to ensure corrupted intervals are cleared"
            )
            return True, "Corruption detected - forcing hardware write to clear"

        current_tou = self.get_daily_TOU_settings()
        new_tou = self._format_daily_tou(candidate_intervals)

        logger.info(f"Current schedule has {len(current_tou)} TOU intervals")
        logger.info(f"New schedule has {len(new_tou)} TOU intervals")

        def interval_end_minute(interval: dict) -> int:
            parts = interval["end_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        from_minute = from_period * 15

        relevant_current = []
        relevant_new = []

        for interval in current_tou:
            end_minute = interval_end_minute(interval)
            if end_minute >= from_minute and interval.get("enabled", True):
                relevant_current.append(interval)

        for interval in new_tou:
            end_minute = interval_end_minute(interval)
            if end_minute >= from_minute and interval.get("enabled", True):
                relevant_new.append(interval)

        past_enabled_current = [
            i
            for i in current_tou
            if i.get("enabled", True) and interval_end_minute(i) < from_minute
        ]
        if past_enabled_current and not relevant_current and not relevant_new:
            past_summary = ", ".join(
                f"{i['start_time']}-{i['end_time']} {i['batt_mode']}"
                for i in past_enabled_current
            )
            logger.info(
                "DECISION: Schedules differ - %d past TOU interval(s) still on "
                "hardware need cleanup: %s",
                len(past_enabled_current),
                past_summary,
            )
            return (
                True,
                f"Stale hardware cleanup ({len(past_enabled_current)} past intervals)",
            )

        logger.info(
            f"Relevant intervals: Current={len(relevant_current)}, New={len(relevant_new)}"
        )

        if len(relevant_current) != len(relevant_new):
            logger.info(
                f"DECISION: Schedules differ - Different number of relevant intervals ({len(relevant_current)} vs {len(relevant_new)})"
            )
            return (
                True,
                f"Different number of relevant intervals ({len(relevant_current)} vs {len(relevant_new)})",
            )

        relevant_current.sort(key=lambda x: x["start_time"])
        relevant_new.sort(key=lambda x: x["start_time"])

        for i, (curr, new) in enumerate(
            zip(relevant_current, relevant_new, strict=False)
        ):
            if (
                curr["start_time"] != new["start_time"]
                or curr["end_time"] != new["end_time"]
                or curr["batt_mode"] != new["batt_mode"]
                or curr.get("enabled", True) != new.get("enabled", True)
            ):
                logger.info(f"DECISION: Schedules differ - TOU interval {i} differs:")
                return True, f"TOU interval {i} differs in mode or timing"

        logger.info("DECISION: Schedules match")
        return False, ""

    def compare_schedules(
        self, other_schedule: "GrowattMinController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Deprecated alias for evaluate_intents — removed in Task 7."""
        return self.evaluate_intents(other_schedule.current_schedule, from_period)
```

- [ ] **Step 7: Write failing tests for `evaluate_intents` and the corruption-forced-apply behavior**

Add to `core/bess/tests/unit/test_controller_coverage.py` (near the existing `compare_schedules` tests for this controller):

```python
class TestEvaluateIntentsGrowattMin:
    def test_no_change_when_intents_identical(self, growatt_min_controller_pair):
        controller, make_schedule = growatt_min_controller_pair
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        differs, _reason = controller.evaluate_intents(
            make_schedule(intents), current_period=0
        )

        assert differs is False

    def test_detects_change_when_intents_differ(self, growatt_min_controller_pair):
        controller, make_schedule = growatt_min_controller_pair
        controller.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )

        differs, reason = controller.evaluate_intents(
            make_schedule(hourly_to_quarterly({10: "BATTERY_EXPORT"})),
            current_period=0,
        )

        assert differs is True
        assert reason

    def test_corruption_forces_apply(self, growatt_min_controller_pair):
        controller, make_schedule = growatt_min_controller_pair
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)
        # Corrupt hardware-committed state directly (out of chronological order)
        controller.tou_intervals[0]["start_time"] = "99:99"

        differs, reason = controller.evaluate_intents(
            make_schedule(intents), current_period=0
        )

        assert differs is True
        assert "Corruption" in reason
```

Check whether `growatt_min_controller_pair` (a fixture pairing a controller with a `make_schedule` helper) already exists in `test_controller_coverage.py` — if the existing `compare_schedules` tests use a different fixture name/shape (e.g. two separately-constructed controller instances `ctrl_a`/`ctrl_b` per the grep earlier in this investigation), adapt the new tests to build a `DPSchedule` via whatever helper that file already uses (likely a local `make_schedule(intents)` function near its top — read the file's existing imports/helpers before writing these tests, don't invent a fixture name that doesn't exist).

- [ ] **Step 8: Run test to verify it fails, then implement, then verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_controller_coverage.py::TestEvaluateIntentsGrowattMin -v
```
Expected before Step 6's code lands: FAIL (`AttributeError: no attribute 'evaluate_intents'`). After Step 6: PASS.

- [ ] **Step 9: Run the full fast suite**

```bash
.venv/bin/pytest -m "not slow" -q
```
Expected: all pre-existing tests still pass (compat wrappers keep `compare_schedules`/`create_schedule` callers working), plus the new tests.

- [ ] **Step 10: Commit**

```bash
git add core/bess/growatt_min_controller.py core/bess/tests/unit/test_growatt_tou_scheduling.py core/bess/tests/unit/test_controller_coverage.py
git commit -m "$(cat <<'EOF'
refactor: extract _build_candidate, add apply_intents/evaluate_intents to GrowattMinController (#369)

Shared candidate computation for "would this differ" and "commit this",
so they can never drift apart the way create_schedule/compare_schedules
implicitly could. create_schedule/compare_schedules become thin
backward-compat wrappers, removed once BatterySystemManager switches
over (Task 6/7).
EOF
)"
```

---

### Task 3: `GrowattSphController` — same pattern

SPH's candidate is charge/discharge period lists rather than TOU intervals, but the same expand-contract shape applies. `_group_sph_periods` reads `self.strategic_intents` directly today — parameterize it the same way as Task 2's `_group_periods_by_mode`.

**Files:**
- Modify: `core/bess/growatt_sph_controller.py`
- Test: `core/bess/tests/unit/test_sph_schedule.py`

**Interfaces:**
- Produces: `_build_candidate(intents: list[str]) -> tuple[list[dict], list[dict], list[dict]]` (new charge_periods, new discharge_periods, new tou_intervals-for-display); `apply_intents(schedule, current_period=0)`; `evaluate_intents(schedule, current_period=0) -> tuple[bool, str]`.

- [ ] **Step 1: Write the failing purity test**

Add to `core/bess/tests/unit/test_sph_schedule.py`:

```python
class TestBuildCandidateSph:
    def test_does_not_mutate_self_state(self, controller):
        controller.strategic_intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller._charge_periods = ["sentinel"]
        controller._discharge_periods = ["sentinel"]

        candidate_intents = hourly_to_quarterly({10: "LOAD_SUPPORT"})
        charge, discharge, tou = controller._build_candidate(candidate_intents)

        assert controller._charge_periods == ["sentinel"]
        assert controller._discharge_periods == ["sentinel"]
        assert charge != ["sentinel"]

    def test_matches_build_sph_periods_output(self, controller):
        intents = hourly_to_quarterly({2: "GRID_CHARGING", 10: "LOAD_SUPPORT"})
        controller.strategic_intents = intents
        controller._build_sph_periods()
        expected_charge = [p.copy() for p in controller._charge_periods]
        expected_discharge = [p.copy() for p in controller._discharge_periods]
        expected_tou = [i.copy() for i in controller.tou_intervals]

        controller._charge_periods = []
        controller._discharge_periods = []
        controller.tou_intervals = []
        charge, discharge, tou = controller._build_candidate(intents)

        assert charge == expected_charge
        assert discharge == expected_discharge
        assert tou == expected_tou
```

(Check `test_sph_schedule.py`'s existing `controller`/`hourly_to_quarterly` fixture names before pasting — reuse whatever's already defined at the top of that file, matching the pattern used by its existing tests.)

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_sph_schedule.py::TestBuildCandidateSph -v
```
Expected: FAIL, `AttributeError: no attribute '_build_candidate'`.

- [ ] **Step 3: Parameterize `_group_sph_periods`**

In `core/bess/growatt_sph_controller.py`, change the signature (currently reads `self.strategic_intents` at line 115) to:

```python
    def _group_sph_periods(
        self, intents: list[str]
    ) -> tuple[list[dict], list[dict]]:
        """Group consecutive periods into charge/discharge blocks.

        Args:
            intents: Strategic intents to group (the candidate being built).

        Returns:
            Tuple of (charge_blocks, discharge_blocks) where each block is a dict with
            keys 'start_period', 'end_period', and 'intents'.
        """
        if not intents:
            return [], []

        charge_blocks: list[dict] = []
        discharge_blocks: list[dict] = []

        for _category, target_list, intent_set in [
            ("charge", charge_blocks, self.CHARGE_INTENTS),
            ("discharge", discharge_blocks, self.DISCHARGE_INTENTS),
        ]:
            current_block: dict | None = None

            for period, intent in enumerate(intents):
                if intent in intent_set:
                    if current_block is None:
                        current_block = {
                            "start_period": period,
                            "end_period": period,
                            "intents": [intent],
                        }
                    else:
                        current_block["end_period"] = period
                        current_block["intents"].append(intent)
                else:
                    if current_block is not None:
                        target_list.append(current_block)
                        current_block = None

            if current_block is not None:
                target_list.append(current_block)

        return charge_blocks, discharge_blocks
```

- [ ] **Step 4: Add `_build_candidate`, delegate `_build_sph_periods` to it**

Replace the body of `_build_sph_periods` (currently lines 212-263) with:

```python
    def _build_candidate(
        self, intents: list[str]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Compute charge/discharge periods and display TOU intervals for the
        given intents, without mutating self. Shared by apply_intents (commits
        onto self) and evaluate_intents (diffs against self's current state)."""
        charge_blocks, discharge_blocks = self._group_sph_periods(intents)

        charge_blocks = self._enforce_period_limit(
            charge_blocks, self.MAX_CHARGE_PERIODS
        )
        discharge_blocks = self._enforce_period_limit(
            discharge_blocks, self.MAX_DISCHARGE_PERIODS
        )

        charge_periods = self._blocks_to_period_dicts(charge_blocks)
        discharge_periods = self._blocks_to_period_dicts(discharge_blocks)

        tou_intervals = []
        for p in charge_periods:
            tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "battery_first",
                    "enabled": True,
                    "is_default": False,
                    "strategic_intent": "GRID_CHARGING",
                }
            )
        for p in discharge_periods:
            tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "grid_first",
                    "enabled": True,
                    "is_default": False,
                    "strategic_intent": "LOAD_SUPPORT/BATTERY_EXPORT",
                }
            )
        tou_intervals.sort(key=lambda x: x["start_time"])
        for idx, interval in enumerate(tou_intervals):
            interval["segment_id"] = idx + 1

        logger.info(
            "SPH periods built: %d charge period(s), %d discharge period(s)",
            len(charge_periods),
            len(discharge_periods),
        )
        for p in charge_periods:
            logger.info("  Charge:    %s-%s", p["start_time"], p["end_time"])
        for p in discharge_periods:
            logger.info("  Discharge: %s-%s", p["start_time"], p["end_time"])

        return charge_periods, discharge_periods, tou_intervals

    def _build_sph_periods(self) -> None:
        """Unchanged public behavior: mutates self._charge_periods/
        self._discharge_periods/self.tou_intervals from self.strategic_intents.
        Delegates to _build_candidate, shared with apply_intents/evaluate_intents."""
        charge, discharge, tou = self._build_candidate(self.strategic_intents)
        self._charge_periods = charge
        self._discharge_periods = discharge
        self.tou_intervals = tou
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_sph_schedule.py -v
```
Expected: PASS, including all pre-existing tests in this file.

- [ ] **Step 6: Add `apply_intents`/`evaluate_intents`, keep `create_schedule`/`compare_schedules` as compat wrappers**

Replace `create_schedule` (currently lines 265-294) with:

```python
    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list, rebuilding SPH charge/discharge periods."""
        logger.info("Creating SPH schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "Using %d strategic intents (quarterly resolution)",
            len(self.strategic_intents),
        )

        self._build_sph_periods()

        logger.info(
            "SPH schedule created: %d charge period(s), %d discharge period(s), "
            "%d display intervals",
            len(self._charge_periods),
            len(self._discharge_periods),
            len(self.tou_intervals),
        )

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Deprecated alias for apply_intents — removed in Task 7."""
        self.apply_intents(schedule, current_period)
```

Replace `compare_schedules` (currently lines 532-578) with:

```python
    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare SPH charge/discharge periods a candidate schedule would
        produce against what's currently applied."""
        candidate_intents = schedule.original_dp_results["strategic_intent"]
        new_charge, new_discharge, _tou = self._build_candidate(candidate_intents)

        current_charge = self._charge_periods
        current_discharge = self._discharge_periods

        def _periods_equal(a: list[dict], b: list[dict]) -> bool:
            if len(a) != len(b):
                return False
            for pa, pb in zip(a, b, strict=False):
                if (
                    pa.get("start_time") != pb.get("start_time")
                    or pa.get("end_time") != pb.get("end_time")
                    or pa.get("enabled") != pb.get("enabled")
                ):
                    return False
            return True

        if not _periods_equal(current_charge, new_charge):
            logger.info(
                "DECISION: SPH charge periods differ — current=%s new=%s",
                current_charge,
                new_charge,
            )
            return True, "SPH charge periods differ"

        if not _periods_equal(current_discharge, new_discharge):
            logger.info(
                "DECISION: SPH discharge periods differ — current=%s new=%s",
                current_discharge,
                new_discharge,
            )
            return True, "SPH discharge periods differ"

        logger.info("DECISION: SPH schedules match")
        return False, ""

    def compare_schedules(
        self, other_schedule: "GrowattSphController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Deprecated alias for evaluate_intents — removed in Task 7."""
        return self.evaluate_intents(other_schedule.current_schedule, from_period)
```

Note: `_build_candidate` is called twice here (once for `new_charge`/`new_discharge`, discarding `_tou`) which recomputes the display-intervals list unnecessarily — acceptable, it's cheap pure computation, not a hardware call. Don't optimize this away; keep the one shared computation.

- [ ] **Step 7: Write failing tests for `evaluate_intents`, then implement, then verify green**

Add to `core/bess/tests/unit/test_sph_schedule.py` near its existing `compare_schedules` tests:

```python
class TestEvaluateIntentsSph:
    def test_no_change_when_intents_identical(self, controller, make_schedule):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        differs, _ = controller.evaluate_intents(make_schedule(intents))

        assert differs is False

    def test_detects_charge_period_change(self, controller, make_schedule):
        controller.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )

        differs, reason = controller.evaluate_intents(
            make_schedule(hourly_to_quarterly({10: "GRID_CHARGING"}))
        )

        assert differs is True
        assert "charge" in reason.lower()
```

(Confirm `make_schedule`/fixture names against what `test_sph_schedule.py` already defines near its top — its existing `compare_schedules` tests, per the earlier grep, use a `manager`/`other` naming pattern; adapt these new tests' fixture names to match whatever that file already has rather than inventing new ones.)

```bash
.venv/bin/pytest core/bess/tests/unit/test_sph_schedule.py::TestEvaluateIntentsSph -v
```
Expected: FAIL before Step 6's code, PASS after.

- [ ] **Step 8: Run the full fast suite**

```bash
.venv/bin/pytest -m "not slow" -q
```
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add core/bess/growatt_sph_controller.py core/bess/tests/unit/test_sph_schedule.py
git commit -m "$(cat <<'EOF'
refactor: extract _build_candidate, add apply_intents/evaluate_intents to GrowattSphController (#369)

Same pattern as GrowattMinController (previous commit): shared candidate
computation for charge/discharge periods, backward-compat wrappers kept
until BatterySystemManager switches over.
EOF
)"
```

---

### Task 4: `SolaxController` — trivial candidate (intent list passthrough)

No TOU-interval computation at all for this platform — the candidate IS the intent list.

**Files:**
- Modify: `core/bess/solax_controller.py`
- Test: `core/bess/tests/unit/test_solax_controller.py`

**Interfaces:**
- Produces: `_build_candidate(schedule) -> list[str]` (just `schedule.original_dp_results["strategic_intent"]` — kept as a named method for interface symmetry with the other 3 subclasses, even though it does no transformation); `apply_intents(schedule, current_period=0)`; `evaluate_intents(schedule, current_period=0) -> tuple[bool, str]`.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_solax_controller.py` near its existing `compare_schedules` tests:

```python
class TestEvaluateIntentsSolax:
    def test_no_change_when_intents_identical(self, controller, make_schedule):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        differs, _ = controller.evaluate_intents(make_schedule(intents))

        assert differs is False

    def test_detects_change_when_intents_differ(self, controller, make_schedule):
        controller.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )

        differs, reason = controller.evaluate_intents(
            make_schedule(hourly_to_quarterly({10: "BATTERY_EXPORT"}))
        )

        assert differs is True
        assert reason

    def test_respects_from_period(self, controller, make_schedule):
        controller.apply_intents(
            make_schedule(hourly_to_quarterly({0: "GRID_CHARGING"})), current_period=0
        )

        # Period 0-3 differs, but evaluate_intents starts at period 8 -> no diff
        differs, _ = controller.evaluate_intents(
            make_schedule(hourly_to_quarterly({})), current_period=8
        )

        assert differs is False
```

(Match `controller`/`make_schedule`/`hourly_to_quarterly` to whatever `test_solax_controller.py` already defines — its existing `compare_schedules` tests at lines 232-292 use `controller`/`other` naming per the earlier grep; adapt accordingly.)

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_solax_controller.py::TestEvaluateIntentsSolax -v
```
Expected: FAIL, `AttributeError: no attribute 'apply_intents'`.

- [ ] **Step 3: Add `apply_intents`/`evaluate_intents`, keep `create_schedule`/`compare_schedules` as compat wrappers**

Replace `create_schedule` (currently lines 71-96) with:

```python
    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Store strategic intents from a DPSchedule.

        SolaX requires no TOU conversion. Intents are applied period-by-period
        via ``_write_period_to_hardware`` and are not pushed as a batch to the
        inverter hardware.
        """
        logger.info("Creating SolaX schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "SolaX: %d strategic intents loaded (quarterly resolution)",
            len(self.strategic_intents),
        )

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Deprecated alias for apply_intents — removed in Task 7."""
        self.apply_intents(schedule, current_period)
```

Replace `compare_schedules` (currently lines 210-246) with:

```python
    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare SolaX schedules by strategic-intent list.

        Two schedules differ when any period at or after ``current_period``
        has a different strategic intent.
        """
        current = self.strategic_intents
        new = schedule.original_dp_results["strategic_intent"]

        if not current and not new:
            return False, ""

        if len(current) != len(new):
            return True, (f"SolaX intent count differs: {len(current)} vs {len(new)}")

        for period in range(current_period, len(current)):
            if current[period] != new[period]:
                logger.info(
                    "DECISION: SolaX intent differs at period %d — "
                    "current=%s new=%s",
                    period,
                    current[period],
                    new[period],
                )
                return True, (f"SolaX strategic intents differ from period {period}")

        logger.info("DECISION: SolaX schedules match")
        return False, ""

    def compare_schedules(
        self, other_schedule: "SolaxController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Deprecated alias for evaluate_intents — removed in Task 7."""
        return self.evaluate_intents(other_schedule.current_schedule, from_period)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_solax_controller.py -v
```
Expected: PASS, all tests including pre-existing `compare_schedules` ones (via the wrapper).

- [ ] **Step 5: Commit**

```bash
git add core/bess/solax_controller.py core/bess/tests/unit/test_solax_controller.py
git commit -m "$(cat <<'EOF'
refactor: add apply_intents/evaluate_intents to SolaxController (#369)

Trivial candidate (the intent list itself, no transformation) --
same interface as the other 3 subclasses for consistency.
create_schedule/compare_schedules kept as compat wrappers.
EOF
)"
```

---

### Task 5: `SolaxModbusGrowattController` — trivial candidate, both `tou` and `vpp` control modes

Like `SolaxController`, this class's `create_schedule` already stores strategic intents directly with no TOU-interval computation (per-period mode/VPP writes happen live in `apply_period`, not via a precomputed batch schedule) — its `compare_schedules` already compares raw intent lists for both `control_mode` values. `seed_from` stays for now (still used by `BatterySystemManager` until Task 6).

**Files:**
- Modify: `core/bess/solax_modbus_growatt_controller.py`
- Test: `core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py`, `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`

**Interfaces:**
- Produces: `apply_intents(schedule, current_period=0)`; `evaluate_intents(schedule, current_period=0) -> tuple[bool, str]`.

- [ ] **Step 1: Write the failing test**

Add to `core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py` near its existing `compare_schedules` tests:

```python
class TestEvaluateIntents:
    def test_no_change_when_intents_identical(self, controller, battery_settings):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        controller.apply_intents(make_schedule(intents), current_period=0)

        differs, _reason = controller.evaluate_intents(make_schedule(intents))

        assert differs is False

    def test_detects_change_when_intents_differ(self, controller, battery_settings):
        controller.apply_intents(
            make_schedule(hourly_to_quarterly({2: "GRID_CHARGING"})), current_period=0
        )

        differs, _reason = controller.evaluate_intents(
            make_schedule(hourly_to_quarterly({10: "BATTERY_EXPORT"}))
        )

        assert differs is True

    def test_respects_from_period(self, controller, battery_settings):
        controller.apply_intents(
            make_schedule(hourly_to_quarterly({0: "GRID_CHARGING"})), current_period=0
        )

        differs, _ = controller.evaluate_intents(
            make_schedule(hourly_to_quarterly({})), current_period=8
        )

        assert differs is False
```

(This file already defines `hourly_to_quarterly`/`make_schedule`/`controller`/`battery_settings` at its top per the code read earlier in this investigation — reuse them directly, no new fixtures needed.)

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py::TestEvaluateIntents -v
```
Expected: FAIL, `AttributeError: no attribute 'apply_intents'`.

- [ ] **Step 3: Add `apply_intents`/`evaluate_intents`, keep `create_schedule`/`compare_schedules` as compat wrappers**

Replace `create_schedule` (currently lines 141-183) with:

```python
    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list — control is applied per-period,
        no batch TOU/VPP schedule computed here."""
        logger.info(
            "Creating %s schedule from strategic intents", self.control_mode.upper()
        )

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "%s: %d strategic intents loaded (quarterly resolution)",
            self.control_mode.upper(),
            len(self.strategic_intents),
        )

        for period in range(max(1, current_period), len(self.strategic_intents)):
            if self.strategic_intents[period] != self.strategic_intents[period - 1]:
                logger.info(
                    "Intent transition at period %d: %s -> %s",
                    period,
                    self.strategic_intents[period - 1],
                    self.strategic_intents[period],
                )

        if self.control_mode == "tou":
            self._update_tou_display_state()

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Deprecated alias for apply_intents — removed in Task 7."""
        self.apply_intents(schedule, current_period)
```

Locate the existing `compare_schedules` method (around line 517, matches the version confirmed earlier in this investigation comparing `self.strategic_intents` vs `other_schedule.strategic_intents`) and replace it with:

```python
    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare schedules by strategic intent list (like SolaxController).

        Two schedules differ when any period at or after ``current_period``
        has a different strategic intent.
        """
        current = self.strategic_intents
        new = schedule.original_dp_results["strategic_intent"]

        if not current and not new:
            return False, ""

        if len(current) != len(new):
            return True, (f"Modbus intent count differs: {len(current)} vs {len(new)}")

        for period in range(current_period, len(current)):
            if current[period] != new[period]:
                logger.info(
                    "DECISION: Modbus intent differs at period %d — "
                    "current=%s new=%s",
                    period,
                    current[period],
                    new[period],
                )
                return True, (f"Modbus strategic intents differ from period {period}")

        logger.info("DECISION: Modbus schedules match")
        return False, ""

    def compare_schedules(
        self,
        other_schedule: "SolaxModbusGrowattController",
        from_period: int = 0,
    ) -> tuple[bool, str]:
        """Deprecated alias for evaluate_intents — removed in Task 7."""
        return self.evaluate_intents(other_schedule.current_schedule, from_period)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py core/bess/tests/unit/test_solax_modbus_growatt_vpp.py -v
```
Expected: PASS, all tests including pre-existing ones (via the wrapper).

- [ ] **Step 5: Commit**

```bash
git add core/bess/solax_modbus_growatt_controller.py core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py
git commit -m "$(cat <<'EOF'
refactor: add apply_intents/evaluate_intents to SolaxModbusGrowattController (#369)

Trivial candidate (intent list) for both tou and vpp control modes,
matching SolaxController's shape. seed_from is kept for this task --
still needed by BatterySystemManager until Task 6 removes controller
recreation.
EOF
)"
```

---

### Task 6: `BatterySystemManager` — stop recreating the controller

Switch every call site to the new methods on the single persistent `self._inverter_controller`, removing `temp_growatt` entirely.

**Files:**
- Modify: `core/bess/battery_system_manager.py`
- Test: `core/bess/tests/unit/test_extended_horizon.py` (calls `_create_updated_schedule` directly and unpacks a tuple — needs updating for the new single-value return)

**Interfaces:**
- Consumes: `InverterController.apply_intents`, `.evaluate_intents`, `.write_to_hardware` (from Tasks 1-5).
- Produces: `_create_updated_schedule(...) -> DPSchedule | None` (was `tuple[DPSchedule, InverterController] | None`).

- [ ] **Step 1: Update the failing test for `_create_updated_schedule`'s new return shape**

In `core/bess/tests/unit/test_extended_horizon.py`, find `TestScheduleTruncation.test_schedule_arrays_truncated_to_today` (around line 600) and change:

```python
        schedule_result = system._create_updated_schedule(
            optimization_period, result, prices, optimization_data, True, False
        )
        assert schedule_result is not None
        dp_schedule, _growatt_manager = schedule_result
```

to:

```python
        dp_schedule = system._create_updated_schedule(
            optimization_period, result, prices, optimization_data, True, False
        )
        assert dp_schedule is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest core/bess/tests/unit/test_extended_horizon.py::TestScheduleTruncation -v
```
Expected: FAIL (still unpacking a tuple from the old two-value return, or the test itself already updated to expect one value while the source hasn't changed yet — either way, a clear mismatch pinpointing this call site).

- [ ] **Step 3: `_create_updated_schedule`** — drop `temp_growatt` creation, return only `temp_schedule`

Find the block (currently around lines 2372-2391):

```python
            # Create schedule manager matching current inverter type
            temp_growatt: InverterController = self._create_inverter_controller()
            temp_growatt.seed_from(self._inverter_controller)
            temp_growatt.strategic_intents = full_day_strategic_intents

            # Create schedule with rolling window — only future periods get TOU segments
            effective_period = 0 if prepare_next_day else optimization_period
            previous_tou = (
                []
                if prepare_next_day
                else self._inverter_controller.active_tou_intervals.copy()
            )
            logger.info(f"Creating Growatt schedule for period={effective_period}")
            temp_growatt.create_schedule(
                temp_schedule,
                current_period=effective_period,
                previous_tou_intervals=previous_tou,
            )

            return temp_schedule, temp_growatt
```

Replace with:

```python
            return temp_schedule
```

Also update the method's return type annotation (find `-> tuple[DPSchedule, InverterController] | None:` in its signature) to `-> DPSchedule | None:`.

- [ ] **Step 4: `update_battery_schedule`** — unpack one value, call the new interface

Find (currently around lines 653-701):

```python
            # Create new schedule
            schedule_result = self._create_updated_schedule(
                optimization_period,
                optimization_result,
                prices,
                optimization_data,
                is_first_run,
                prepare_next_day,
            )

            if schedule_result is None:
                logger.error("Failed to create updated schedule")
                return False

            temp_schedule, temp_growatt = schedule_result

            # Determine if we should apply the new schedule
            should_apply, reason = self._should_apply_schedule(
                is_first_run,
                current_period,
                prepare_next_day,
                temp_growatt,
                optimization_period,
                temp_schedule,
            )

            # Apply schedule if needed
            if should_apply:
                self._apply_schedule(
                    current_period,
                    temp_schedule,
                    temp_growatt,
                    reason,
                    prepare_next_day,
                )
            else:
                # Update current schedule even when TOU doesn't change.
                # Hardware-derived state (TOU intervals, VPP confirmation,
                # etc.) is already carried onto temp_growatt via seed_from()
                # at creation time (#329), so no further copying is needed
                # here before adopting it.
                self._current_schedule = temp_schedule
                self._inverter_controller = temp_growatt
```

Replace with:

```python
            # Create new schedule
            temp_schedule = self._create_updated_schedule(
                optimization_period,
                optimization_result,
                prices,
                optimization_data,
                is_first_run,
                prepare_next_day,
            )

            if temp_schedule is None:
                logger.error("Failed to create updated schedule")
                return False

            # Determine if we should apply the new schedule
            should_apply, reason = self._should_apply_schedule(
                is_first_run,
                current_period,
                prepare_next_day,
                optimization_period,
                temp_schedule,
            )

            # Apply schedule if needed
            if should_apply:
                self._apply_schedule(
                    current_period,
                    temp_schedule,
                    reason,
                    prepare_next_day,
                )
            else:
                # Update display data even when nothing changes on hardware.
                # Applied TOU/VPP state on self._inverter_controller is left
                # untouched — there's only ever one instance now (#369), so
                # there's nothing to carry forward or swap in.
                self._current_schedule = temp_schedule
                self._inverter_controller.strategic_intents = (
                    temp_schedule.strategic_intents
                )
```

- [ ] **Step 5: `_should_apply_schedule`** — drop the `temp_growatt` parameter, call `evaluate_intents`

Find (currently around lines 2392-2438):

```python
    def _should_apply_schedule(
        self,
        is_first_run: bool,
        period: int,
        prepare_next_day: bool,
        temp_growatt: InverterController,
        optimization_period: int,
        temp_schedule: DPSchedule,
    ) -> tuple[bool, str]:
        """Determine if schedule should be applied based on TOU differences from current period onwards."""

        logger.info("Evaluating whether to apply new schedule at period %d", period)

        # Retry failed hardware write from previous cycle
        if self._hardware_write_pending:
            logger.info(
                "DECISION: Apply schedule - retrying previously failed hardware write"
            )
            return True, "Retry failed hardware write"

        # Special case: preparing next day (runs at 23:55 for 00:00 start)
        if prepare_next_day:
            # Compare full day TOU settings for tomorrow (from start of day)
            schedules_differ, reason = self._inverter_controller.compare_schedules(
                other_schedule=temp_growatt, from_period=0
            )

            logger.info(
                "DECISION for next day: %s - %s",
                "Apply" if schedules_differ else "Keep",
                reason,
            )
            return schedules_differ, f"Next day: {reason}"

        # Normal case: compare TOU settings from current period onwards
        try:
            schedules_differ, reason = self._inverter_controller.compare_schedules(
                other_schedule=temp_growatt, from_period=period
            )

            if schedules_differ:
                logger.info("DECISION: Apply schedule - %s", reason)
            else:
                logger.info("DECISION: Keep current schedule - %s", reason)

            return schedules_differ, reason

        except Exception as e:
            logger.warning("Schedule comparison failed: %s, applying new schedule", e)
            return True, f"Schedule comparison error: {e}"
```

Replace with:

```python
    def _should_apply_schedule(
        self,
        is_first_run: bool,
        period: int,
        prepare_next_day: bool,
        optimization_period: int,
        temp_schedule: DPSchedule,
    ) -> tuple[bool, str]:
        """Determine if schedule should be applied based on TOU differences from current period onwards."""

        logger.info("Evaluating whether to apply new schedule at period %d", period)

        # Retry failed hardware write from previous cycle
        if self._hardware_write_pending:
            logger.info(
                "DECISION: Apply schedule - retrying previously failed hardware write"
            )
            return True, "Retry failed hardware write"

        # Special case: preparing next day (runs at 23:55 for 00:00 start)
        if prepare_next_day:
            # Compare full day TOU settings for tomorrow (from start of day)
            schedules_differ, reason = self._inverter_controller.evaluate_intents(
                temp_schedule, current_period=0
            )

            logger.info(
                "DECISION for next day: %s - %s",
                "Apply" if schedules_differ else "Keep",
                reason,
            )
            return schedules_differ, f"Next day: {reason}"

        # Normal case: compare TOU settings from current period onwards
        try:
            schedules_differ, reason = self._inverter_controller.evaluate_intents(
                temp_schedule, current_period=period
            )

            if schedules_differ:
                logger.info("DECISION: Apply schedule - %s", reason)
            else:
                logger.info("DECISION: Keep current schedule - %s", reason)

            return schedules_differ, reason

        except Exception as e:
            logger.warning("Schedule comparison failed: %s, applying new schedule", e)
            return True, f"Schedule comparison error: {e}"
```

Update the one caller of `_should_apply_schedule` in Step 4's `update_battery_schedule` block (already shown above without `temp_growatt`) — done.

- [ ] **Step 6: `_apply_schedule`** — drop `temp_growatt` parameter, mutate the persistent controller

Find (currently around lines 2449-2500, exact numbers shifted by earlier edits — locate by signature):

```python
    def _apply_schedule(
        self,
        period: int,
        temp_schedule: DPSchedule,
        temp_growatt: InverterController,
        reason: str,
        prepare_next_day: bool,
    ) -> None:
        """Apply schedule to hardware."""

        logger.info("=" * 80)
        logger.info("=== SCHEDULE APPLICATION START ===")
        logger.info(
            "Period: %d (%s), Reason: %s, Next day: %s",
            period,
            format_period(period),
            reason,
            prepare_next_day,
        )
        logger.info("=" * 80)

        logger.info("Schedule update required: %s", reason)
        self._current_schedule = temp_schedule

        # Adopt the new controller BEFORE the hardware write so that
        # strategic intents, period settings, and TOU state are available
        # even when the write fails (e.g. missing TOU entity mappings,
        # Modbus timeout).  The _hardware_write_pending flag ensures the
        # write is retried on the next quarterly cycle.
        current_tou = self._inverter_controller.active_tou_intervals
        self._inverter_controller = temp_growatt

        try:
            effective_period = 0 if prepare_next_day else period

            if self._controller is None:
                logger.error("Cannot apply schedule: controller is not available")
            else:
                temp_growatt.write_to_hardware(
                    self._controller, effective_period, current_tou
                )

            # Clear corruption flag after successful hardware write
            if temp_growatt.corruption_detected:
                logger.info(
                    "Corruption recovery complete - clearing corruption flag after successful hardware write"
                )
                temp_growatt.corruption_detected = False
```

Replace with:

```python
    def _apply_schedule(
        self,
        period: int,
        temp_schedule: DPSchedule,
        reason: str,
        prepare_next_day: bool,
    ) -> None:
        """Apply schedule to hardware."""

        logger.info("=" * 80)
        logger.info("=== SCHEDULE APPLICATION START ===")
        logger.info(
            "Period: %d (%s), Reason: %s, Next day: %s",
            period,
            format_period(period),
            reason,
            prepare_next_day,
        )
        logger.info("=" * 80)

        logger.info("Schedule update required: %s", reason)
        self._current_schedule = temp_schedule

        # Read the currently-active TOU intervals BEFORE apply_intents
        # rebuilds them, so write_to_hardware still sees what's on hardware
        # right now (used for stale-segment cleanup on some platforms).
        current_tou = self._inverter_controller.active_tou_intervals.copy()
        effective_period = 0 if prepare_next_day else period
        self._inverter_controller.apply_intents(temp_schedule, effective_period)

        try:
            if self._controller is None:
                logger.error("Cannot apply schedule: controller is not available")
            else:
                self._inverter_controller.write_to_hardware(
                    self._controller, effective_period, current_tou
                )

            # Clear corruption flag after successful hardware write
            if self._inverter_controller.corruption_detected:
                logger.info(
                    "Corruption recovery complete - clearing corruption flag after successful hardware write"
                )
                self._inverter_controller.corruption_detected = False
```

Read a few lines further in the existing method (past this block, to the end of `_apply_schedule`) and replace any remaining references to `temp_growatt` in that tail (e.g. `self._hardware_write_pending = False`, exception handling) with `self._inverter_controller` — same mechanical substitution, no other logic changes. Update the one caller in Step 4's `update_battery_schedule` block (already shown above without `temp_growatt`) — done.

- [ ] **Step 7: Run the updated test, then the full fast suite**

```bash
.venv/bin/pytest core/bess/tests/unit/test_extended_horizon.py::TestScheduleTruncation -v
```
Expected: PASS.

```bash
.venv/bin/pytest -m "not slow" -q
```
Expected: all tests pass — this is the highest-risk step in the whole plan (it's the actual behavior wiring change), so if anything fails here, stop and diagnose before continuing; do not proceed to Task 7 with a red suite.

- [ ] **Step 8: Run the slow suite too**

```bash
.venv/bin/pytest -m slow -q
```
Expected: all tests pass (this includes `test_min_schedule_e2e.py`'s pinned scenario fixtures — the design's acceptance criterion that applied schedules are unchanged).

- [ ] **Step 9: Commit**

```bash
git add core/bess/battery_system_manager.py core/bess/tests/unit/test_extended_horizon.py
git commit -m "$(cat <<'EOF'
refactor: stop recreating InverterController every schedule update (#369)

_create_updated_schedule no longer builds a scratch temp_growatt --
it returns just the DPSchedule. _should_apply_schedule and
_apply_schedule now call evaluate_intents/apply_intents/write_to_hardware
directly on the single persistent self._inverter_controller. This is the
actual behavior-wiring change; Task 7 removes the now-dead
seed_from/create_schedule/compare_schedules machinery this superseded.
EOF
)"
```

---

### Task 7: Cleanup — delete `seed_from`, old method names, old tests; make new interface abstract

Now that nothing calls `create_schedule`, `compare_schedules`, or `seed_from`, remove them entirely and tighten the abstract base class.

**Files:**
- Modify: `core/bess/inverter_controller.py`
- Modify: `core/bess/growatt_min_controller.py`, `core/bess/growatt_sph_controller.py`, `core/bess/solax_controller.py`, `core/bess/solax_modbus_growatt_controller.py`
- Modify: `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`, `core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py` (delete `TestSeedFromVpp`/`TestSeedFrom`)
- Modify: `CHANGELOG.md`
- Modify: `docs/agents/bess-knowledge.md` / `docs/SOFTWARE_DESIGN.md` if either references `create_schedule`/`compare_schedules`/`seed_from` (grep first, per Step 5)

- [ ] **Step 1: Remove `seed_from` from all 4 subclasses and the base class**

```bash
grep -rn "def seed_from\|seed_from(" core/bess/*.py core/bess/tests/unit/*.py
```

Delete the `seed_from` method from `core/bess/inverter_controller.py` (base, added in #368), `core/bess/growatt_min_controller.py`, and `core/bess/solax_modbus_growatt_controller.py` (the only 2 subclasses that override it, per the grep). Delete the `TestSeedFromVpp` class from `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py` and the `TestSeedFrom` class from `core/bess/tests/unit/test_solax_modbus_growatt_single_segment.py` (both added in #368, now testing a deleted method).

- [ ] **Step 2: Remove the deprecated `create_schedule`/`compare_schedules` wrapper methods**

In each of `core/bess/growatt_min_controller.py`, `core/bess/growatt_sph_controller.py`, `core/bess/solax_controller.py`, `core/bess/solax_modbus_growatt_controller.py`: delete the `create_schedule` and `compare_schedules` methods added as "Deprecated alias" wrappers in Tasks 2-5 (each is a 3-6 line method immediately following its `apply_intents`/`evaluate_intents` counterpart — easy to spot by the "Deprecated alias for X — removed in Task 7" docstring).

- [ ] **Step 3: Remove old test coverage for the deleted wrapper methods**

For each of the 4 subclass test files touched in Tasks 2-5, remove any `TestCompareSchedules`/`class Test...` blocks whose tests call `.compare_schedules(...)` or `.create_schedule(...)` directly (as opposed to the new `evaluate_intents`/`apply_intents` tests added in Tasks 2-5, which stay). Search first:

```bash
grep -rln "\.compare_schedules(\|\.create_schedule(" core/bess/tests/unit/*.py
```

Any remaining hits after this step should be zero (every test now uses `apply_intents`/`evaluate_intents`).

- [ ] **Step 4: Tighten the base class — make `apply_intents`/`evaluate_intents` abstract, remove old abstract methods**

In `core/bess/inverter_controller.py`, find the abstract `create_schedule` (around line 471) and `compare_schedules` (around line 493) and `previous_tou_intervals` parameter usage, and replace with:

```python
    @abstractmethod
    def apply_intents(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
    ) -> None:
        """Adopt this cycle's DP intent list as current control state.

        For TOU-style platforms this rebuilds persisted hardware TOU
        intervals; for VPP/SolaX-style ephemeral platforms this is a
        near-passthrough of the intent list (control is applied per-period
        elsewhere, not as a batch schedule).
        """

    @abstractmethod
    def evaluate_intents(
        self, schedule: "InverterController", current_period: int = 0
    ) -> tuple[bool, str]:
        """Would applying ``schedule`` differ from what's currently in
        effect, from ``current_period`` onwards? Returns (differs, reason).

        Read-only: must not mutate self's committed state (tou_intervals,
        strategic_intents, etc.) — only self.corruption_detected may be set
        as an accepted diagnostic side effect on platforms that support it.
        """
```

(Fix the `evaluate_intents` type hint above — `schedule` should be typed `DPSchedule`, not `"InverterController"`; this was a placeholder slip during drafting, use `schedule: DPSchedule` to match every subclass's actual signature.)

Remove `seed_from`'s abstract-adjacent presence if it was declared on the base (Step 1 already deletes its body; confirm no leftover abstract declaration remains).

- [ ] **Step 5: Grep the design docs for anything this refactor invalidates**

```bash
grep -n "create_schedule\|compare_schedules\|seed_from\|temp_growatt" docs/agents/bess-knowledge.md docs/SOFTWARE_DESIGN.md
```

If either file names these methods, update the reference to `apply_intents`/`evaluate_intents`. If neither mentions them (likely — these are internal implementation details, not documented BESS behavior), note that explicitly in the PR description per `implement-issue`/`writing-plans` convention rather than silently skipping the check.

- [ ] **Step 6: Add a regression test proving the #329 bug class is fixed by construction**

Add to `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`:

```python
class TestNoRedundantWritesAcrossCycles:
    """#329: applying the same intents twice in a row on the SAME controller
    instance (no recreation at all, unlike #368's simulated-recreation test)
    must not re-write VPP status/allow-AC-charging the second time."""

    def test_apply_intents_twice_writes_vpp_status_once(self, controller, mock_ha):
        intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        schedule = make_schedule(intents)

        controller.apply_intents(schedule, current_period=0)
        _apply_at_period(controller, mock_ha, 8, grid_charge=True, discharge_rate=0)
        assert len(mock_ha.calls["growatt_vpp_status"]) == 1

        # Re-apply the identical schedule -- same instance, no recreation
        controller.apply_intents(schedule, current_period=0)
        _apply_at_period(controller, mock_ha, 9, grid_charge=True, discharge_rate=0)

        assert len(mock_ha.calls["growatt_vpp_status"]) == 1
        assert len(mock_ha.calls["growatt_vpp_allow_ac_charging"]) == 1
```

- [ ] **Step 7: Run the full fast suite, then the slow suite**

```bash
.venv/bin/pytest -m "not slow" -q
```
Expected: all pass, 0 failures.

```bash
.venv/bin/pytest -m slow -q
```
Expected: all pass, 0 failures — same applied-schedule outcomes as the pre-refactor baseline on every pinned scenario fixture.

- [ ] **Step 8: Run quality-check.sh**

```bash
./scripts/quality-check.sh
```
Expected: 0 errors, 0 warnings (Black, Ruff, mypy — the abstract method signature and dropped parameters need to typecheck cleanly across all 4 subclasses).

- [ ] **Step 9: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]` → `### Changed`, add:

```markdown
- **InverterController is no longer recreated every optimization cycle** — `BatterySystemManager` previously built a fresh controller instance each cycle (`temp_growatt`) and selectively carried hardware-derived state onto it (`seed_from`, added in #368 to fix #329). Each of the 4 platforms (`GrowattMinController`, `GrowattSphController`, `SolaxController`, `SolaxModbusGrowattController`) is now a single long-lived instance per platform selection, only ever recreated on an explicit platform/control-mode switch — removing the whole class of "forgot to carry a field forward" bugs by construction rather than patching around it. The abstract interface is renamed to be platform-neutral: `create_schedule`/`compare_schedules` → `apply_intents`/`evaluate_intents`, `write_schedule_to_hardware` → `write_to_hardware`, both backed by one shared `_build_candidate` helper per subclass so "would this differ" and "commit this" can never drift apart. No change to what schedule gets applied or when. ([#369](https://github.com/johanzander/bess-manager/issues/369))
```

- [ ] **Step 10: Delete the plan file, keep the spec**

```bash
rm docs/superpowers/plans/2026-07-23-controller-lifecycle-refactor.md
```

(Per `implement-issue`/`writing-plans` convention: the plan is execution scaffolding that drifts once the code is the source of truth; the design spec at `docs/superpowers/specs/2026-07-23-controller-lifecycle-refactor-design.md` stays.)

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: remove seed_from and deprecated create_schedule/compare_schedules aliases (#369)

Final cleanup step: nothing calls the old names after Task 6 switched
BatterySystemManager over. apply_intents/evaluate_intents are now
properly abstract on InverterController. Adds a direct regression test
proving #329's bug class is fixed by construction (same instance,
applied twice, one hardware write) rather than by carry-forward
bookkeeping.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the naming rename (spec section 2's `write_to_hardware`); Tasks 2-5 cover the per-subclass `_build_candidate`/`apply_intents`/`evaluate_intents` split (spec section 2); Task 6 covers the `BatterySystemManager` call-site changes (spec section 3); Task 7 covers `seed_from` deletion, test migration, and the regression test (spec section 4). The `previous_tou_intervals` dead-parameter removal (spec's Global Constraints) is folded into Tasks 2-5's `apply_intents` signatures and Task 6's `_create_updated_schedule` edit, and finalized in Task 7 Step 4's base-class signature.
- **Type consistency check:** `_build_candidate`'s return type differs per subclass by design (`tuple[list[dict], list[dict]]` for GrowattMin, `tuple[list[dict], list[dict], list[dict]]` for SPH, bare `list[str]` for the other two) — this is intentional (each subclass's private helper, not part of the public abstract interface) and does not need to unify.
- **Ambiguity flagged inline:** Task 7 Step 4 calls out and fixes a type-hint slip in its own draft (`evaluate_intents`'s `schedule` parameter) rather than leaving it for the implementer to notice.
