# Issue/PR State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give issues and PRs an explicit state machine whose every state has one cheap next action, so the Product Owner loop progresses work without spending a full `implement-issue` session per step.

**Architecture:** `Status` becomes the phase and `Awaiting` becomes an orthogonal, *signed* wait (`maintainer` escalates loudly; everything else suppresses quietly). `backlog-digest.sh` learns that one issue has many PRs and gains an `In Verification` phase plus an exact in-flight file set. `backlog-rhythm.sh` stops sorting alphabetically and ranks right-to-left across the board, under a WIP limit and a collision gate. A new `advance-pr` skill holds the single copy of the review loop, extracted from `implement-issue` Step 11, so advancing a PR one state costs a script instead of a session.

**Tech Stack:** bash + jq (the two scripts), pytest with PATH shims and file seams (`backend/tests/test_backlog_digest.py`, `backend/tests/test_backlog_rhythm.py`), GitHub Projects v2 via `gh project`, Claude Code skills as markdown under `.claude/skills/`.

**Spec:** `docs/superpowers/specs/2026-08-18-issue-pr-state-machine-design.md`

## Global Constraints

- **State lives on GitHub, nowhere else.** No local file may mirror board or issue state. Counters are derived from GitHub facts or recorded as issue comments — never as files.
- **No fallbacks.** Per `docs/agents/rules.md`, a missing input fails explicitly. Do not add `// null` defaults that let a wrong jq path resolve silently — that is the exact failure the digest's own comments warn about.
- **`Priority` options are `P1`–`P4`. There is no `P0`.**
- **`Status` options after Task 1:** `Backlog`, `Analysis`, `Ready for Dev`, `In Progress`, `In Review`, `In Verification`, `Done`.
- **`Awaiting` options after Task 1:** `reporter`, `discussion`, `upstream`, `analysis`, `maintainer`.
- **The digest's `column` values must match `Status` strings exactly** — reconciling a card is a string comparison, never a translation table.
- **No apostrophes anywhere inside the jq programs.** Both scripts embed jq in single-quoted shell strings; one apostrophe in a comment terminates the string and bash fails with `unexpected EOF` pointing at the top of the block.
- **`gh api` and `gh project` field mutations prompt for permission** (see `docs/agents/local-agent-environment.md`). Task 1 and Task 13 are interactive; every other task is unattended.
- **Run `./scripts/quality-check.sh` before every commit.** Black formatting is the most common CI failure and no pre-commit hook exists.
- Tests: `.venv/bin/pytest backend/tests/test_backlog_digest.py backend/tests/test_backlog_rhythm.py -v` — both are fast (not `slow`-marked).

---

### Task 1: Board fields — add `In Verification` and `maintainer`

Every later task derives or writes these values. Doing this first means no task ships code referencing a field option that does not exist.

**Files:**
- Modify: `.claude/skills/backlog/SKILL.md:44-52` (the field-options table)
- No test file — this is remote board state, verified by reading it back

**Interfaces:**
- Consumes: nothing
- Produces: `Status` option `In Verification`; `Awaiting` option `maintainer`. Tasks 3, 6, 7, 8 and 12 all depend on these strings existing verbatim.

- [ ] **Step 1: Read the current field definitions**

```bash
gh project field-list 1 --owner johanzander --format json \
  | jq '.fields[] | select(.name == "Status" or .name == "Awaiting")
        | {id, name, options: [.options[]?.name]}'
```

Expected: `Status` with six options ending at `Done`; `Awaiting` with four options ending at `analysis`. Record both field `id` values — the next step needs them.

- [ ] **Step 2: Add the two options**

Projects v2 has no "append option" mutation; `updateProjectV2Field` replaces the whole option list, so every existing option must be repeated or it is deleted along with every card's value.

```bash
gh api graphql -f query='
  mutation($field: ID!, $opts: [ProjectV2SingleSelectFieldOptionInput!]!) {
    updateProjectV2Field(input: {fieldId: $field, singleSelectOptions: $opts}) {
      projectV2Field { ... on ProjectV2SingleSelectField { id options { name } } }
    }
  }' -f field='<STATUS_FIELD_ID>' -f opts='[
    {"name":"Backlog","color":"GRAY","description":""},
    {"name":"Analysis","color":"YELLOW","description":""},
    {"name":"Ready for Dev","color":"BLUE","description":""},
    {"name":"In Progress","color":"PURPLE","description":""},
    {"name":"In Review","color":"ORANGE","description":""},
    {"name":"In Verification","color":"PINK","description":""},
    {"name":"Done","color":"GREEN","description":""}
  ]'
```

Then the same mutation for `Awaiting`, repeating `reporter`, `discussion`, `upstream`, `analysis` and appending `maintainer`.

- [ ] **Step 3: Verify by reading the board back**

```bash
gh project field-list 1 --owner johanzander --format json \
  | jq '.fields[] | select(.name == "Status" or .name == "Awaiting") | [.name, [.options[]?.name]]'
```

Expected: `Status` has seven options with `In Verification` between `In Review` and `Done`; `Awaiting` has five ending in `maintainer`. **Also confirm no card lost its value:**

```bash
gh project item-list 1 --owner johanzander --format json \
  | jq '[.items[] | select(.status != null)] | length'
```

Expected: the same non-null count as before the mutation. If it dropped, an option name was misspelled in the replacement list — re-run Step 2 with the exact strings from Step 1.

- [ ] **Step 4: Update the skill's field table**

In `.claude/skills/backlog/SKILL.md`, replace the `Status` and `Awaiting` rows:

```markdown
| `Status` | `Backlog`, `Analysis`, `Ready for Dev`, `In Progress`, `In Review`, `In Verification`, `Done` |
| `Priority` | `P1`, `P2`, `P3`, `P4` — **there is no `P0`** |
| `Awaiting` | `reporter`, `discussion`, `upstream`, `analysis`, `maintainer` |
```

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/backlog/SKILL.md
git commit -m "feat: add In Verification and Awaiting:maintainer, which the state machine needs"
```

---

### Task 2: One issue, many PRs — stop discarding every PR but the first

`pr_for` returns `$matches[0]`, silently dropping the rest. The project's own no-auto-close rule guarantees an issue has several PRs, so this is a live bug.

**Files:**
- Modify: `scripts/backlog-digest.sh:167-173` (`pr_matches_issue`, `pr_for`), `:402-403` (item emission)
- Modify: `scripts/backlog-rhythm.sh` — three `.pr` call sites
- Test: `backend/tests/test_backlog_digest.py`, `backend/tests/test_backlog_rhythm.py`

**Interfaces:**
- Consumes: Task 1's field strings (not yet used here)
- Produces: digest items carry `prs: [{number, mergeable, isDraft}]` sorted ascending by number. **Fields `pr` and `pr_state` are removed.** Tasks 3, 7, 8 and 9 read `.prs`.

- [ ] **Step 1: Write the failing digest test**

Add to `backend/tests/test_backlog_digest.py`:

```python
def _pr(number: int, **over: object) -> dict:
    """A PR as `gh pr list --json ...` returns it to the digest."""
    pr: dict = {
        "number": number,
        "title": f"pr {number}",
        "body": "",
        "headRefName": f"fix/pr-{number}",
        "isDraft": True,
        "mergeable": "MERGEABLE",
    }
    pr.update(over)
    return pr


def test_an_issue_with_several_prs_reports_all_of_them(bin_dir: Path) -> None:
    """The no-auto-close rule means a beta PR and a graduation PR both point at
    one issue. Returning only the first made the second invisible to every
    board pass, and derived the column from an arbitrary one of the two.

    Branch names here deliberately carry NO issue number, so the association is
    proved by the body reference alone -- including the new `Refs` verb, which
    is the only spelling an intermediate PR is allowed."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [_issue(500, labels=[{"name": "bug"}])],
            [
                _pr(501, body="Refs #500", headRefName="fix/beta-work"),
                _pr(502, body="Closes #500", headRefName="fix/graduation",
                    mergeable="CONFLICTING"),
            ],
            [],
        ),
    )

    item = _run(bin_dir)["items"][0]
    assert [p["number"] for p in item["prs"]] == [501, 502]
    assert item["prs"][1]["mergeable"] == "CONFLICTING"
    assert "pr" not in item
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py::test_an_issue_with_several_prs_reports_all_of_them -v
```

Expected: FAIL — `KeyError: 'prs'`.

- [ ] **Step 3: Teach the matcher `Refs #N`, and return the set**

In `scripts/backlog-digest.sh`, replace `pr_matches_issue` and `pr_for`:

```jq
  # `refs` joins the closing verbs deliberately. The project rule is that a beta
  # or intermediate PR must NOT close the reporters issue -- only the graduation
  # PR does -- so an intermediate PR carries `Refs #N` and would otherwise
  # associate with nothing at all.
  def pr_matches_issue($p; $n):
    ($p.body // "" | test("(?i)(fixes|closes|resolves|refs) #\($n)\\b"))
    or ($p.headRefName | test("issue-\($n)(\\D|$)"));

  # Returns EVERY matching PR, ascending. Taking `[0]` discarded the rest, and
  # with one issue routinely carrying several PRs that meant the column was
  # derived from whichever happened to sort first.
  def prs_for($n):
    [ $prs[] | select(pr_matches_issue(.; $n))
             | {number: .number, mergeable: .mergeable, isDraft: .isDraft} ]
    | sort_by(.number);
```

- [ ] **Step 3b: Teach the MERGED-PR scan the same verb**

`scripts/backlog-digest.sh:80` computes `refs` for merged PRs with a **second,
separate regex**, and `merged_pr_for` reads it. Leaving it alone means an
intermediate `Refs #N` PR is never associated once merged — which is exactly
the case `In Verification` exists for, since only the graduation PR may use a
closing verb. Change:

```jq
      refs: [ (.body // "") | scan("(?i)(?:fixes|closes|resolves) #([0-9]+)") | .[0] | tonumber ]
```

to:

```jq
      refs: [ (.body // "") | scan("(?i)(?:fixes|closes|resolves|refs) #([0-9]+)") | .[0] | tonumber ]
```

- [ ] **Step 4: Emit `prs` and drop `pr` / `pr_state`**

Replace the `(pr_for(.number)) as $pr` binding with `(prs_for(.number)) as $open_prs`, and in the item object replace:

```jq
          pr: ($pr.number // null),
          pr_state: ($pr.mergeable // null),
```

with:

```jq
          prs: $open_prs,
```

Every other use of `$pr` in the item block becomes `$open_prs`.

- [ ] **Step 5: Update the three rhythm call sites**

In `scripts/backlog-rhythm.sh`:

- the chase suppression `if .pr != null then empty` becomes `if (.prs | length) > 0 then empty`
- the stalled-worktree guard `and .pr == null` becomes `and (.prs | length) == 0`
- the PR→issue lookup `select(.pr == $p.number)` becomes `select(.prs | map(.number) | index($p.number))`

- [ ] **Step 6: Update the rhythm test fixture**

In `backend/tests/test_backlog_rhythm.py`, in `_item`, replace `"pr": None, "pr_state": None,` with `"prs": [],` and update every test that passes `pr=<n>` to pass `prs=[{"number": <n>, "mergeable": "MERGEABLE", "isDraft": True}]`.

- [ ] **Step 7: Run both suites**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py backend/tests/test_backlog_rhythm.py -v
```

Expected: PASS, including the new test.

- [ ] **Step 8: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-digest.sh scripts/backlog-rhythm.sh backend/tests/
git commit -m "fix: report every PR on an issue, which one-to-many made invisible"
```

---

### Task 3: `In Verification`, and `Awaiting` stops moving the column

Two changes to one function, because they are the same change: phase comes from artifacts, waits are orthogonal.

**Files:**
- Modify: `scripts/backlog-digest.sh:338-345` (`column`)
- Test: `backend/tests/test_backlog_digest.py`

**Interfaces:**
- Consumes: `prs_for` from Task 2; `merged_pr_for` (already exists, returns a PR number or `null`)
- Produces: `column` may now return `In Verification`. `column` no longer returns `Analysis` merely because `awaiting` is set.

**Why `Awaiting` must stop moving the column:** the spec makes `Status` the phase and `Awaiting` the wait, orthogonal. Today an item with a wait reports `Analysis` however far it got — which is what makes an `In Review` PR blocked on the maintainer read as unanalysed. The safety property that rule was protecting survives without it: `Ready for Dev` already requires `blocked == false` and no wait, so an unsettled item still cannot become dispatchable. The wait gates readiness; it no longer rewrites the phase.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_merged_pr_with_the_issue_open_is_in_verification(tmp_path: Path) -> None:
    """Merged to main, not yet in a stable release. The digest used to leave
    this period unnamed, so a fix awaiting real-world confirmation sat in
    whatever column it happened to be in."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_shim(bin_dir, "gh", _gh_shim(
        issues=[_issue(510, labels=["bug", "analyzed"])],
        prs=[],
        merged_prs=[_pr(511, body="Refs #510", head="fix/issue-510", merged=True)],
    ))
    _write_shim(bin_dir, "git", _git_shim(_porcelain()))
    _write_shim(bin_dir, "claude", "echo '[]'")

    assert _run(bin_dir)["items"][0]["column"] == "In Verification"


def test_an_open_pr_outranks_a_merged_one(tmp_path: Path) -> None:
    """A graduation PR still open means the work is In Review, not verified."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_shim(bin_dir, "gh", _gh_shim(
        issues=[_issue(512, labels=["bug"])],
        prs=[_pr(514, body="Closes #512", head="fix/issue-512-b")],
        merged_prs=[_pr(513, body="Refs #512", head="fix/issue-512-a", merged=True)],
    ))
    _write_shim(bin_dir, "git", _git_shim(_porcelain()))
    _write_shim(bin_dir, "claude", "echo '[]'")

    assert _run(bin_dir)["items"][0]["column"] == "In Review"


def test_a_wait_no_longer_rewrites_the_phase(tmp_path: Path) -> None:
    """Status is the phase, Awaiting is the wait, and they are orthogonal. An
    In Review item blocked on the maintainer must not report Analysis."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_shim(bin_dir, "gh", _gh_shim(
        issues=[_issue(515, labels=["bug", "blocked"])],
        prs=[_pr(516, body="Refs #515", head="fix/issue-515")],
    ))
    _write_shim(bin_dir, "git", _git_shim(_porcelain()))
    _write_shim(bin_dir, "claude", "echo '[]'")

    item = _run(bin_dir)["items"][0]
    assert item["column"] == "In Review"
    assert item["blocked"] is True
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py -k "verification or outranks or rewrites" -v
```

Expected: FAIL — first two give `Analysis`/`Backlog`, the third gives `Analysis`.

- [ ] **Step 3: Rewrite `column`**

```jq
  # PHASE COMES FROM ARTIFACTS. `Status` says what stage the work is at;
  # `Awaiting` says who is being waited on, and the two are orthogonal --
  # a wait no longer rewrites the phase. The safety property survives in
  # `Ready for Dev` below, which still requires no blocker and no wait, so an
  # unsettled item cannot be dispatched however far its analysis got.
  #
  # ORDER IS THE CONTENT. Live work outranks landed work: an issue whose
  # graduation PR is still open is In Review, not In Verification.
  def column($labels; $open_prs; $merged_pr; $wt_live; $awaiting; $priority; $blocked):
      if ($open_prs | length) > 0 then "In Review"
      elif $wt_live then "In Progress"
      elif $merged_pr != null then "In Verification"
      elif ($labels | index("analyzed")) and $priority != null
           and ($blocked | not) and $awaiting == null then "Ready for Dev"
      elif ($labels | index("analyzed")) then "Analysis"
      elif $blocked or $awaiting != null then "Analysis"
      else "Backlog" end;
```

Update the call site to pass `$open_prs` and `$merged_pr`:

```jq
      | (column($labels; $open_prs; $merged_pr; $wt_live; $aw; $prio; $blocked)) as $col
```

- [ ] **Step 4: Run the full digest suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py -v
```

Expected: PASS. Pre-existing tests asserting `awaiting` forces `Analysis` on a *pre-PR* item still pass — such an item has no PR, no worktree and no merged PR, so it falls through to the final `elif`.

- [ ] **Step 5: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-digest.sh backend/tests/test_backlog_digest.py
git commit -m "feat: name the merged-but-unreleased phase, and stop a wait rewriting it"
```

---

### Task 4: Count resume handoffs, so "died twice" is a fact

**Files:**
- Modify: `scripts/backlog-digest.sh` (item emission)
- Test: `backend/tests/test_backlog_digest.py`

**Interfaces:**
- Consumes: the issue `comments` array, already fetched
- Produces: `resume_count: <int>` on every item. Task 6 escalates at `>= 2`.

The marker is an HTML comment, invisible in rendered GitHub markdown, so the handoff comment reads normally to a human while staying countable.

- [ ] **Step 1: Write the failing test**

```python
def test_resume_handoffs_are_counted(bin_dir: Path) -> None:
    """A session that died twice is telling you something -- but nothing
    counted, so nothing could act on it. The marker is an HTML comment so the
    handoff still reads as prose on GitHub."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [
                _issue(
                    520,
                    labels=[{"name": "bug"}],
                    comments=[
                        _comment("bess-developer",
                                 "Resuming implementation.\n<!-- resume-handoff -->"),
                        _comment("johanzander", "thanks"),
                        _comment("bess-developer",
                                 "Resuming implementation.\n<!-- resume-handoff -->"),
                    ],
                )
            ],
            [],
            [],
        ),
    )

    assert _run(bin_dir)["items"][0]["resume_count"] == 2
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py::test_resume_handoffs_are_counted -v
```

Expected: FAIL — `KeyError: 'resume_count'`.

- [ ] **Step 3: Add the counter**

Add the definition beside `bot_authors`:

```jq
  # How many times an implementation session has been handed back on this
  # issue. The marker is an HTML comment, so the handoff reads as ordinary
  # prose on GitHub while staying exactly countable here -- no local file, and
  # no guessing from prose.
  def resume_count($comments):
    [ $comments[]? | select((.body // "") | contains("<!-- resume-handoff -->")) ] | length;
```

And in the item object, beside `session`:

```jq
          resume_count: resume_count(.comments),
```

- [ ] **Step 4: Run the suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-digest.sh backend/tests/test_backlog_digest.py
git commit -m "feat: count resume handoffs, so a twice-dead session is a fact not a feeling"
```

---

### Task 5: The in-flight file set

Half the collision gate is exact and needs no prediction: what open PRs and live worktree branches already touch.

**Files:**
- Modify: `scripts/backlog-digest.sh` (new top-level key)
- Test: `backend/tests/test_backlog_digest.py`

**Interfaces:**
- Consumes: the open-PR list and the worktree list, both already gathered
- Produces: top-level `in_flight_files: {"<path>": [<pr or issue numbers>]}` — a map from repo-relative path to every open PR number touching it. Task 9 intersects against it.

- [ ] **Step 1: Write the failing test**

```python
def test_in_flight_files_map_paths_to_the_prs_touching_them(bin_dir: Path) -> None:
    """The collision gate needs to know what is already being edited. Half of
    that is exact -- the changed-file set of every open PR -- and only the
    candidate's own touch-set has to be predicted."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [_issue(530, labels=[{"name": "bug"}])],
            [_pr(531, body="Refs #530", headRefName="fix/a-530"),
             _pr(532, body="Refs #530", headRefName="fix/b-530")],
            [],
            pr_files={531: ["CLAUDE.md", "scripts/backlog-rhythm.sh"],
                      532: ["CLAUDE.md"]},
        ),
    )

    in_flight = _run(bin_dir)["in_flight_files"]
    assert in_flight["CLAUDE.md"] == [531, 532]
    assert in_flight["scripts/backlog-rhythm.sh"] == [531]
```

Extend `_gh_shim` to answer `pr diff <n> --name-only` from the new `pr_files` argument, one path per line.

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py::test_in_flight_files_map_paths_to_the_prs_touching_them -v
```

Expected: FAIL — `KeyError: 'in_flight_files'`.

- [ ] **Step 3: Gather the changed files**

Beside where the digest collects open PRs, add:

```bash
# The EXACT half of the collision gate: what every open PR already touches.
# One `gh pr diff` per open PR -- bounded by the WIP limit in practice, and the
# alternative (predicting from issue text alone) is what let five PRs race to
# rewrite the same three files.
in_flight_files='{}'
for n in $(printf '%s' "$prs_json" | jq -r '.[].number'); do
    files=$(gh pr diff "$n" --repo "$repo" --name-only 2>/dev/null || true)
    in_flight_files=$(printf '%s' "$in_flight_files" | jq \
        --argjson n "$n" \
        --argjson f "$(printf '%s' "$files" | jq -R -s 'split("\n") | map(select(length > 0))')" \
        'reduce $f[] as $p (.; .[$p] = ((.[$p] // []) + [$n] | unique))')
done
```

Pass it into the main jq program as `--argjson in_flight "$in_flight_files"` and emit it as a top-level key:

```jq
    in_flight_files: $in_flight,
```

- [ ] **Step 4: Run the suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py -v
```

Expected: PASS. Pre-existing tests get `in_flight_files: {}` because their shims report no open PRs.

- [ ] **Step 5: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-digest.sh backend/tests/test_backlog_digest.py
git commit -m "feat: compute what open PRs already touch, which the collision gate needs exactly"
```

---

### Task 6: Escalation — `maintainer` ranks first, and two triggers derive themselves

**Files:**
- Modify: `scripts/backlog-rhythm.sh` (issue rules, PR rules, output ordering)
- Test: `backend/tests/test_backlog_rhythm.py`

**Interfaces:**
- Consumes: `resume_count` (Task 4), `.prs` (Task 2), the PR `reviews` array
- Produces: action `escalated`, always ranked first. Task 7's ordering must keep it there.

- [ ] **Step 1: Write the failing tests**

```python
def test_awaiting_maintainer_escalates_instead_of_suppressing(tmp_path: Path) -> None:
    """Awaiting is signed. reporter/upstream/discussion mean they owe us, and
    stay quiet; maintainer means YOU owe us, and must be loud. Today every
    value suppresses, so an item blocked on the maintainer gets quieter."""
    item = _item(700, awaiting="maintainer", awaiting_source="board")
    result = _run(tmp_path, [item])
    assert "escalated" in _actions_for(result, 700)
    assert result["actions"][0]["issue"] == 700


def test_three_changes_requested_rounds_escalate(tmp_path: Path) -> None:
    """Three rounds of disagreement is a design argument, not a bug -- the
    implement-issue cap already says so. Another round will not settle it."""
    pr = _pr(701, isDraft=True, reviews=[
        {"state": "CHANGES_REQUESTED"}, {"state": "CHANGES_REQUESTED"},
        {"state": "CHANGES_REQUESTED"},
    ])
    actions = _actions_for(_run(tmp_path, [], prs=[pr]), 701)
    assert "escalated" in actions
    assert "resume_implementation" not in actions


def test_two_resume_handoffs_escalate(tmp_path: Path) -> None:
    item = _item(702, resume_count=2, worktree="/wt", worktree_branch="fix/issue-702")
    assert "escalated" in _actions_for(_run(tmp_path, [item]), 702)


def test_one_handoff_is_not_yet_an_escalation(tmp_path: Path) -> None:
    item = _item(703, resume_count=1, worktree="/wt", worktree_branch="fix/issue-703")
    actions = _actions_for(_run(tmp_path, [item]), 703)
    assert "escalated" not in actions
    assert "resume_implementation" in actions
```

Add `"resume_count": 0` to the `_item` default dict. **Use the existing `_pr(number, **over)` helper at `backend/tests/test_backlog_rhythm.py:391` — do not add a second one.**

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -k escalat -v
```

Expected: FAIL — no `escalated` action exists.

- [ ] **Step 3: Add the issue-side escalations**

In the issue rules block, **before** every other rule:

```jq
    # ESCALATION IS SIGNED AWAITING, POINTED THE OTHER WAY. Every other value
    # means someone else owes us and correctly goes quiet; `maintainer` means
    # the loop cannot advance without a decision, so it must be the loudest
    # thing in the pass. An escalation that ranks by column is an escalation
    # that waits, which defeats the valve.
    (if .awaiting == "maintainer"
     then {issue: .number, action: "escalated",
           why: "awaiting the maintainer",
           detail: "read the open question on the issue and decide; or send it back to Analysis"}
     else empty end),

    # A session that died twice is telling you something. Nothing counted
    # before, so `resume_implementation` was re-reported forever on work that
    # had already failed twice.
    (if .resume_count >= 2
     then {issue: .number, action: "escalated",
           why: "\(.resume_count) implementation sessions have been handed back",
           detail: "the item is not implementable as specified -- decide, or send it back to Analysis"}
     else empty end),
```

Guard `resume_implementation` so it does not also fire: add `and .resume_count < 2` to its condition.

- [ ] **Step 4: Add the PR-side escalation**

In the PR rules, immediately after `$deferred` is bound and before `mark_ready`:

```jq
      | ([ .reviews[]? | select(.state == "CHANGES_REQUESTED") ] | length) as $rounds
      | (if $rounds >= 3
         then {pr: .number, action: "escalated",
               why: "\($rounds) CHANGES_REQUESTED rounds without an approval",
               detail: "the reviewer and the implementer disagree about the design; another round will not settle it"}
```

and chain the existing `if $approved_draft` as an `elif`, so an escalated PR never also reports `resume_implementation`.

- [ ] **Step 5: Rank escalations first**

Replace the output sort:

```jq
      actions: sort_by((if .action == "escalated" then 0 else 1 end), .action, (.issue // .pr)),
```

Task 7 replaces the `.action` term; the `escalated`-first term survives it.

- [ ] **Step 6: Run the suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-rhythm.sh backend/tests/test_backlog_rhythm.py
git commit -m "feat: make an escalation loud, which suppressing Awaiting made quiet"
```

---

### Task 7: Pull from the right — replace the alphabetical sort

`sort_by(.action, …)` puts `dispatchable` first and `resume_implementation` last because `d < m < r`. Every pass therefore leads with "start new work" and buries "finish started work" — the exact inversion of the flow policy.

**Files:**
- Modify: `scripts/backlog-rhythm.sh` (output ordering)
- Test: `backend/tests/test_backlog_rhythm.py`

**Interfaces:**
- Consumes: Task 6's `escalated`
- Produces: `actions` sorted by `rank` (0 = escalations, then rightmost column first). Each action gains a `rank: <int>` field so the ordering is assertable.

- [ ] **Step 1: Write the failing test**

```python
def test_finishing_outranks_starting(tmp_path: Path) -> None:
    """Empty the board from the right. The alphabetical sort put dispatchable
    first and resume_implementation last purely because d < m < r."""
    ready = _item(800, column="Ready for Dev", board_status="Ready for Dev",
                  labels=["bug", "analyzed"], priority="P2")
    stalled = _item(801, column="In Progress", board_status="In Progress",
                    worktree="/wt", worktree_branch="fix/issue-801")
    order = [a["action"] for a in _run(tmp_path, [ready, stalled])["actions"]]
    assert order.index("resume_implementation") < order.index("dispatchable")


def test_an_escalation_outranks_every_column(tmp_path: Path) -> None:
    escalated = _item(802, awaiting="maintainer", awaiting_source="board")
    verifying = _item(803, column="In Verification", board_status="In Verification")
    first = _run(tmp_path, [escalated, verifying])["actions"][0]
    assert first["action"] == "escalated"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -k "outranks_starting or outranks_every" -v
```

Expected: FAIL — `dispatchable` sorts before `resume_implementation`.

- [ ] **Step 3: Add the rank function and sort on it**

Before the `{due: …}` object:

```jq
  # FLOW POLICY RULE 1: EMPTY THE BOARD FROM THE RIGHT. Finish started work
  # before starting new work, so actions rank by the column of the item they
  # serve, rightmost first. Escalations sit above all of it -- see Task 6.
  #
  # This replaces a plain alphabetical sort, which ranked `dispatchable` above
  # `resume_implementation` for no reason beyond d < m < r, and so led every
  # pass with "start new work".
  | map(. + {rank:
      (if .action == "escalated" then 0
       elif .action == "mark_ready" or .action == "awaiting_maintainer"
            or .action == "request_review" or .action == "rework_review"
            or .action == "resolve_conflict" then 2
       elif .action == "resume_implementation" or .action == "prune_worktree" then 3
       elif .action == "dispatchable" then 4
       elif .action == "recheck_ready" or .action == "surface_discussion"
            or .action == "nudge_reporter" or .action == "park" then 5
       else 6 end)})
```

and replace the sort:

```jq
      actions: sort_by(.rank, .action, (.issue // .pr)),
```

- [ ] **Step 4: Leave `by_action` alone (no-op step)**

`by_action` is a count summary, not an ordering — `group_by` sorting it by key
is correct and stays. Only `actions` is re-sorted. Nothing to change here; the
step exists so the next reviewer does not read the untouched summary block as
an oversight.

- [ ] **Step 5: Run the suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-rhythm.sh backend/tests/test_backlog_rhythm.py
git commit -m "fix: rank actions right-to-left, which an alphabetical sort had inverted"
```

---

### Task 8: The WIP limit

**Files:**
- Modify: `scripts/backlog-rhythm.sh`
- Test: `backend/tests/test_backlog_rhythm.py`

**Interfaces:**
- Consumes: item `column` values from Task 3
- Produces: top-level `wip: {count, limit, over}`. `dispatchable` is suppressed entirely while `over` is true. `RHYTHM_WIP_LIMIT` is the test seam, default `3`.

- [ ] **Step 1: Write the failing tests**

```python
def test_over_the_wip_limit_suppresses_dispatch(tmp_path: Path) -> None:
    """Unbounded WIP is the state that produced 8 open drafts, 6 of them
    conflicting. Above the limit, nothing new starts."""
    in_flight = [
        _item(900 + i, column="In Review", board_status="In Review",
              prs=[{"number": 950 + i, "mergeable": "MERGEABLE", "isDraft": True}])
        for i in range(3)
    ]
    ready = _item(910, column="Ready for Dev", board_status="Ready for Dev",
                  labels=["bug", "analyzed"], priority="P2")
    result = _run(tmp_path, in_flight + [ready])
    assert result["wip"] == {"count": 3, "limit": 3, "over": True}
    assert "dispatchable" not in _actions_for(result, 910)


def test_under_the_limit_dispatch_is_allowed(tmp_path: Path) -> None:
    ready = _item(911, column="Ready for Dev", board_status="Ready for Dev",
                  labels=["bug", "analyzed"], priority="P2")
    result = _run(tmp_path, [ready])
    assert result["wip"]["over"] is False
    assert "dispatchable" in _actions_for(result, 911)


def test_a_branch_and_its_pr_count_as_one(tmp_path: Path) -> None:
    """In Progress and In Review are the same piece of work at two stages;
    counting them separately would double the effective limit."""
    items = [_item(920, column="In Progress", board_status="In Progress"),
             _item(921, column="In Review", board_status="In Review",
                   prs=[{"number": 960, "mergeable": "MERGEABLE", "isDraft": True}])]
    assert _run(tmp_path, items)["wip"]["count"] == 2
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -k wip -v
```

Expected: FAIL — `KeyError: 'wip'`.

- [ ] **Step 3: Add the limit**

Read the seam beside `NUDGE_DAYS`:

```bash
# FLOW POLICY: the WIP limit. 3 is deliberately aggressive -- with 7 in flight
# it keeps dispatch shut until the fleet drains to 2, which is the point. A
# variable so the tests can drive the boundary.
WIP_LIMIT="${RHYTHM_WIP_LIMIT:-3}"
```

Pass `--argjson wip_limit "$WIP_LIMIT"`, then bind before the rules:

```jq
  # In Progress and In Review are ONE piece of work at two stages -- a branch
  # and its PR. Counting them separately would silently double the limit.
  | ([ $items[] | select(.column == "In Progress" or .column == "In Review") ] | length) as $wip
  | ($wip >= $wip_limit) as $over_wip
```

Guard `dispatchable`: `(if .column == "Ready for Dev" and ($over_wip | not) then …`.

Emit the block:

```jq
      wip: {count: $wip, limit: $wip_limit, over: $over_wip},
```

- [ ] **Step 4: Report it in the human output**

After the `RHYTHM:` header line:

```bash
wip_line=$(printf '%s' "$actions" | jq -r '.wip
  | if .over then "  WIP " + (.count|tostring) + "/" + (.limit|tostring)
                  + " — finish before starting; dispatch suppressed"
    else "  WIP " + (.count|tostring) + "/" + (.limit|tostring) end')
printf '%s\n' "$wip_line"
```

Print it on the `nothing due` path too — a suppressed dispatch queue is exactly when the reader needs to know why.

- [ ] **Step 5: Run the suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-rhythm.sh backend/tests/test_backlog_rhythm.py
git commit -m "feat: cap work in progress at 3, which unbounded WIP had jammed"
```

---

### Task 9: The collision gate

**Files:**
- Modify: `scripts/backlog-rhythm.sh`
- Test: `backend/tests/test_backlog_rhythm.py`

**Interfaces:**
- Consumes: `in_flight_files` (Task 5); a per-item `predicted_files: [<path>]` supplied by the Stage 2 analysis or the PO
- Produces: action `queued_behind` replacing `dispatchable` on collision; `cluster` when two Ready items overlap each other

- [ ] **Step 1: Write the failing tests**

```python
def test_a_candidate_touching_an_in_flight_file_is_queued(tmp_path: Path) -> None:
    """Five PRs raced to rewrite the same three files. The gate belongs before
    dispatch -- detecting the clash at merge time is detecting a fire."""
    ready = _item(1000, column="Ready for Dev", board_status="Ready for Dev",
                  labels=["bug", "analyzed"], priority="P2",
                  predicted_files=["CLAUDE.md"])
    result = _run(tmp_path, [ready], in_flight_files={"CLAUDE.md": [614]})
    actions = _actions_for(result, 1000)
    assert "queued_behind" in actions
    assert "dispatchable" not in actions


def test_a_candidate_with_no_predicted_files_is_not_dispatchable(tmp_path: Path) -> None:
    """No touch-set, no dispatch. A proposal that cannot be checked against the
    in-flight set is a proposal to find out by colliding."""
    ready = _item(1001, column="Ready for Dev", board_status="Ready for Dev",
                  labels=["bug", "analyzed"], priority="P2", predicted_files=[])
    actions = _actions_for(_run(tmp_path, [ready]), 1001)
    assert "dispatchable" not in actions
    assert "needs_touch_set" in actions


def test_two_ready_items_that_overlap_are_clustered(tmp_path: Path) -> None:
    """Two issues that will fight over one file cost less as one unit of work
    than as two PRs plus a conflict resolution."""
    a = _item(1002, column="Ready for Dev", board_status="Ready for Dev",
              labels=["analyzed"], priority="P2", predicted_files=["core/bess/x.py"])
    b = _item(1003, column="Ready for Dev", board_status="Ready for Dev",
              labels=["analyzed"], priority="P2", predicted_files=["core/bess/x.py"])
    result = _run(tmp_path, [a, b])
    assert "cluster" in _actions_for(result, 1002)
```

Add `"predicted_files": []` to the `_item` default and an `in_flight_files` argument to `_run`, written into the digest fixture.

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -k "queued or touch_set or clustered" -v
```

Expected: FAIL — all three still report `dispatchable`.

- [ ] **Step 3: Implement the gate**

Replace the `dispatchable` rule:

```jq
    # FLOW POLICY RULE 3: NOTHING STARTS THAT COLLIDES. The in-flight half is
    # exact (every open PR changed-file set); only the candidate half is
    # predicted, and a candidate with no prediction is not dispatchable -- a
    # proposal that cannot be checked is a proposal to find out by colliding.
    (if .column != "Ready for Dev" or $over_wip then empty
     elif (.predicted_files | length) == 0
     then {issue: .number, action: "needs_touch_set",
           why: "Ready for Dev but no predicted touch-set",
           detail: "name the files from the Stage 2 analysis; no touch-set, no dispatch"}
     else
       ([ .predicted_files[] | select($in_flight[.] != null) ]) as $clash
       | ([ $items[] | select(.number != $i.number
                              and .column == "Ready for Dev"
                              and ((.predicted_files // []) | any(. as $f | ($i.predicted_files | index($f))))) ]
          | map(.number)) as $peers
       | if ($clash | length) > 0
         then {issue: .number, action: "queued_behind",
               why: "touches \($clash | join(", ")) which is already in flight",
               detail: "wait for the in-flight PR to land, or fold this into it"}
         elif ($peers | length) > 0
         then {issue: .number, action: "cluster",
               why: "overlaps Ready item(s) \($peers | map("#" + (. | tostring)) | join(", "))",
               detail: "dispatch them as ONE unit of work -- one branch, one PR"}
         else {issue: .number, action: "dispatchable",
               why: "Ready for Dev, priority \(.priority), no file collision",
               detail: "meets Definition of Ready; propose for dispatch"}
         end
     end),
```

Bind `$in_flight` from the digest at the top: `(.in_flight_files // {}) as $in_flight`, and `. as $i` on the item.

- [ ] **Step 4: Run the suite**

```bash
.venv/bin/pytest backend/tests/test_backlog_rhythm.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-rhythm.sh backend/tests/test_backlog_rhythm.py
git commit -m "feat: gate dispatch on file collisions, which advisory prose never prevented"
```

---

### Task 10: The `advance-pr` skill

`backlog/SKILL.md` argues correctly that a second copy of the review loop goes stale. So this does not copy it — it **moves** it, leaving one copy with three callers.

**Files:**
- Create: `.claude/skills/advance-pr/SKILL.md`
- Test: none — a skill is a prompt, not code. Its behaviour is pinned by Task 11's delegation and by the rhythm actions already tested.

**Interfaces:**
- Consumes: `scripts/request-pr-review.sh <n>`; `gh pr view/ready/diff`
- Produces: a skill invoked as `/advance-pr <n>` that performs **exactly one** transition and exits, and that writes `Awaiting: maintainer` on the two escalations it owns

- [ ] **Step 1: Write the skill**

Create `.claude/skills/advance-pr/SKILL.md` with frontmatter:

```markdown
---
name: advance-pr
description: Use when a single open PR needs moving one step closer to merge — requesting its review, acting on a verdict, resolving a conflict, or flipping it ready. Advances exactly one PR by exactly one state and exits.
---
```

Body sections, in order:

1. **Overview** — states that this is the *only* copy of the review loop, that `implement-issue` Step 11 and `backlog-rhythm.sh` both call it, and that it advances one PR by one state then exits. Explicitly: *do not* re-read the implementation context; that is where the cost went.
2. **The transition table** — copied verbatim from the spec's §2 table, one row per PR fact.
3. **Read the state first** —

```bash
git fetch origin
gh pr view <n> --json number,isDraft,mergeable,mergeStateStatus,reviews,comments,statusCheckRollup,headRefName
```

   with the existing warning that `comments` is a separate feed from `reviews` and carries maintainer direction that no verdict touches.
4. **The verdict rules, carried over unchanged from Step 11** — `reviewDecision` when set, else the **last** non-`COMMENTED` review; CI must be green not merely unconflicted; a `COMMENTED` that arrives after the run finished *is* the verdict; a maintainer review or conversation comment stops the loop.
5. **The two escalations this skill owns**, each ending in a board write plus a comment:

```bash
gh project item-edit --id <item> --field-id <awaiting-field> --single-select-option-id <maintainer>
scripts/gh-agent.sh --as dev pr comment <n> --body "..."
```

   - **semantic conflict**: `git merge origin/main` produced conflicts that are not textual — the two sides disagree about behaviour. Abort the merge, do not guess, escalate with the conflicting hunks quoted.
   - **CI red after a retry**: this skill pushed a fix and checks failed again. One retry distinguishes a flake from a real breakage; a second is guessing.
6. **Hard constraints** — never merge; never `gh pr ready` a red, conflicted, or unreviewed PR; never flip a PR whose approval predates commits that touched reviewed code.

- [ ] **Step 2: Verify the skill loads**

```bash
head -5 .claude/skills/advance-pr/SKILL.md
```

Expected: valid frontmatter with `name: advance-pr`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/advance-pr/
git commit -m "feat: extract the review loop into advance-pr, so advancing a PR costs a step not a session"
```

---

### Task 11: `implement-issue` delegates, requires `Refs #N`, and opens its own issue

**Files:**
- Modify: `.claude/skills/implement-issue/SKILL.md` — Step 0, Step 9, Step 11, and the CI-mode table row 11

**Interfaces:**
- Consumes: `advance-pr` (Task 10)
- Produces: `implement-issue` no longer contains the review loop; every PR it opens carries `Refs #N`

- [ ] **Step 1: Replace Step 11 with a delegation**

Replace the whole `### 11. Independent review loop` section body with:

```markdown
### 11. Independent review loop (never skip this)

The loop lives in **`advance-pr`**, which is its only copy. Invoke it, and keep
invoking it until it reports a terminal state:

    /advance-pr <pr-number>

Each invocation performs one transition and exits. You still hold the Step 2
diagnosis and the Step 3 scope assessment, which is what lets you tell a real
review finding from one that contradicts a decision made deliberately — so act
on a `CHANGES_REQUESTED` verdict **here**, in this session, then invoke
`advance-pr` again for the next round.

**Hard cap: 3 rounds.** On the third `CHANGES_REQUESTED`, `advance-pr` escalates
by setting `Awaiting: maintainer`, and you stop and hand over the findings
verbatim.
```

- [ ] **Step 2: Update the CI-mode table**

Row 11 currently says the loop is skipped. Keep the substance and name the new home:

```markdown
| 11. Independent review loop | Skip — CI opens the PR as a draft and the owner triggers Stage 4 by hand. A CI run that requested its own review would be the fix bot grading itself. `advance-pr` is therefore not invoked in CI, and the PR stays a draft: `gh pr ready` is that skill's, and there is no approval in CI mode to earn it. |
```

- [ ] **Step 3: Require `Refs #N` in Step 9**

In the draft-PR step, add:

```markdown
**Every PR body carries `Refs #<issue>`** — and only the graduation PR carries
`Closes #<issue>`, per the no-auto-close rule. A beta or intermediate PR that
used a closing verb would close the reporter's issue before the fix has shipped
to them; one that referenced nothing at all would be invisible to the board,
which associates PRs with issues by that line.
```

- [ ] **Step 4: Teach Step 0 to open an issue when given none**

In Step 0, after the issue-or-PR resolution:

```markdown
**If `<n>` is neither — a bare refactor or `TODO.md` item with no issue — open
one first**, so the work has a card and can carry `Priority`, `Awaiting` and a
phase like everything else:

    gh issue create --title "<one line>" --body "<why, in two sentences>" --label refactor

One card per unit of work is the rule; a PR with no issue is a second card for
the same work, which is what made `Priority` ambiguous between the two.
```

- [ ] **Step 5: Post the resume-handoff marker**

Also in Step 0, in the resume branch:

```markdown
When resuming, post the handoff marker so the count is a fact rather than a
feeling — two handoffs on one issue is an escalation:

    scripts/gh-agent.sh --as dev issue comment <n> \
      --body "Resuming implementation from step <k>.
    <!-- resume-handoff -->"
```

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/implement-issue/SKILL.md
git commit -m "refactor: delegate the review loop to advance-pr, keeping one copy"
```

---

### Task 12: Rewrite the state machine into `backlog/SKILL.md`

**Files:**
- Modify: `.claude/skills/backlog/SKILL.md`

**Interfaces:**
- Consumes: every preceding task
- Produces: the PO's operating document, matching what the scripts now do

- [ ] **Step 1: Replace the state documentation**

Add a **States and transitions** section carrying the spec's §1 table verbatim (seven `Status` values with their meaning and exit condition), and the signed-`Awaiting` table.

- [ ] **Step 2: Replace the rhythm action table**

Add the new actions and their handling:

```markdown
| `escalated` | **Read first, always.** Decide the open question, or send the item back to Analysis by clearing `Awaiting` and re-opening the scope |
| `graduate` | the fix is in a stable release: close the issue and tell the reporter, as the PO identity |
| `queued_behind` | do nothing; it is correctly waiting on an in-flight PR |
| `cluster` | dispatch the named items as ONE unit of work — one branch, one PR |
| `needs_touch_set` | name the files from the Stage 2 analysis, then re-run the pass |
```

and note that `resume_implementation` now means `/advance-pr <n>` for a PR, and `/implement-issue <n>` only for a worktree with no PR.

- [ ] **Step 3: Add the flow policy**

Carry the spec's §6 verbatim: the three rules, the rank order, and the WIP limit of 3 counting `In Progress` + `In Review` together.

- [ ] **Step 4: Update the dispatch section**

Replace the advisory same-file paragraph with the gate:

```markdown
**A `dispatchable` proposal must carry its predicted touch-set.** No touch-set,
no dispatch — the pass reports `needs_touch_set` instead. This replaces the
advisory "queue same-file work" paragraph, which was prose with no gate and
never fired: five of eight open PRs ended up editing the same three files.
```

- [ ] **Step 5: Delete the PR-card machinery**

The "Deferring a PR" section describes cards on PRs. Rewrite it for issue cards, keeping the reasoning intact — a decision must be recorded once, not re-argued every tick — and noting that `Awaiting: maintainer` is the one value that makes an item *louder* rather than quieter.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/backlog/SKILL.md
git commit -m "docs: document the state machine the scripts now implement"
```

---

### Task 13: Board migration — drop PR cards, resolve the deferrals

Interactive: it needs decisions only the maintainer can make.

**Files:**
- No repo files — this is board state

**Interfaces:**
- Consumes: Tasks 1–12
- Produces: a board with issue cards only, and no ambiguous deferrals

- [ ] **Step 1: List the PR cards to remove**

```bash
gh project item-list 1 --owner johanzander --format json \
  | jq -r '.items[] | select(.content.type == "PullRequest")
           | "\(.id) #\(.content.number) \(.content.title)"'
```

- [ ] **Step 2: Move each deferral decision onto its issue**

For each PR card carrying `Priority` or `Awaiting` (today: #437 `P4`, #354 and #167 `discussion`), ask the maintainer whether the wait is genuinely on a third party (`discussion`/`upstream` — stays quiet) or on them (`maintainer` — becomes loud). Set the resolved value on the **issue** card, then delete the PR card:

```bash
gh project item-delete 1 --owner johanzander --id <ITEM_ID>
```

- [ ] **Step 3: Backfill `In Verification`**

```bash
./scripts/backlog-digest.sh | jq -r '.items[] | select(.column == "In Verification")
  | "#\(.number) card is \(.board_status)"'
```

Move each card to `In Verification`.

- [ ] **Step 4: Drain the WIP jam**

```bash
./scripts/backlog-rhythm.sh
```

Expected: `WIP 7/3 — finish before starting; dispatch suppressed`, escalations first, no `dispatchable`. Work the PR actions in the printed order — the pipeline cluster (#614, #620, #638, #645) lowest-number-first, one at a time, so each merges against a main moving by one PR rather than five.

- [ ] **Step 5: Confirm the machine agrees**

```bash
./scripts/backlog-rhythm.sh
```

Expected once WIP ≤ 2: `dispatchable` reappears, gated by the collision check.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 state table, `In Verification` | 1, 3 |
| §1 signed `Awaiting` | 1, 6 |
| §2 `advance-pr`, one step per call | 10, 11 |
| §3 escalation triggers — review non-convergence, session died twice | 6 (derived) |
| §3 escalation triggers — semantic conflict, CI red after retry | 10 (`advance-pr` writes them) |
| §4 `Refs #N`, one closer, set-based derivation, no PR cards | 2, 11, 13 |
| §5 collision gate, clustering | 5, 9 |
| §6 pull from the right | 7 |
| §6 bugs pre-empt, do not add | **see below** |
| §6 WIP limit 3 | 8 |
| Migration | 13 |

**One gap found and closed by note rather than by task:** §6 Rule 2 (bugs pre-empt) is already implemented by the combination of Task 7's rank and Task 8's limit — a `bug` reaching `Ready for Dev` sorts into the same rank as any other candidate, and the WIP limit applies to it identically, which is exactly "pre-empt, do not add". The *ordering within* `Ready for Dev` is `Verb: next`'s existing tier-1 rule (`bug` from a non-maintainer outranks everything), which is unchanged and needs no code. **No new task.**

**Second gap, deliberately deferred:** nothing moves an issue *out* of `In Verification`. The trigger is "appeared in a stable release", which only the `release` skill knows. Task 12 names a `graduate` action in the PO's table; the hook that *emits* it belongs in `release` and is out of scope for this plan. **Flagged, not silently dropped.**

**Placeholder scan:** no `TBD`, no "similar to Task N", no "add error handling". Every code step carries the actual jq, bash or markdown.

**Type consistency:** `prs` (Task 2) is read by Tasks 3, 7, 8, 9 with the same `[{number, mergeable, isDraft}]` shape. `resume_count` (Task 4) is read by Task 6 as an int. `in_flight_files` (Task 5) is read by Task 9 as `{path: [numbers]}`. `predicted_files` (Task 9) is a `[path]` on the item. `rank` (Task 7) is an int on every action. `escalated` is spelled identically in Tasks 6, 7 and 12.
