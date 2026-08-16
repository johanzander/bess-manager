---
name: project_backlog_board_state_2026_08_16
description: State of the backlog board before/after the first board-writes-only PO pass on 2026-08-16 — only #611 was on the board, 35 issues missing entirely
metadata:
  type: project
---

Before this pass, the board (project 1) had exactly **one** card (#611,
P1/Backlog) despite 36 open issues existing. `backlog-digest.sh` derives a
`column` for every open issue regardless of whether it's on the board, which
made this easy to miss without diffing against `gh project item-list`
directly — the digest's presence doesn't imply board presence.

**Why:** board-init/bootstrap work (PRs around #609-611 per recent commits)
created the project and field schema but never did a bulk backlog import —
only the issue that happened to be filed around that time landed on it.

**How to apply:** before trusting "the board is roughly in sync," diff
`gh project item-list` counts against `gh issue list --state open` counts.
Don't assume prior passes kept the board populated.

Several issues surfaced during this pass that are candidates for maintainer
attention but were out of scope (board-writes-only run):
- #520/#393/#571 form a cluster (LOAD_SUPPORT / discharge-gate shadow-price
  correctness) — likely worth a combined roadmap push rather than fixing
  piecewise.
- #118 (Solax-Growatt MIN-inverter correction) has 29 comments — the busiest
  thread in the backlog — and is still unlabeled and un-triaged.
- #96 is the only `analyzed`/Ready for Dev item; everything else needing
  Stage 2 analysis is still sitting in Analysis.

See [[project_board_field_ids]] for the GraphQL mechanics used.
