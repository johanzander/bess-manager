---
name: project_backlog_board_state_2026_08_16
description: The digest deriving a column for an issue does not mean the issue is on the board — learned when a 2026-08-16 pass found 1 card against 36 open issues
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

See [[project_board_field_ids]] for the GraphQL mechanics used.
