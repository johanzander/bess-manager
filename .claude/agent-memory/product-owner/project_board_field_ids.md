---
name: project_board_field_ids
description: GraphQL node/field/option IDs for the backlog board (project 1) — Status, Priority, Awaiting — and the Priority field's real options
metadata:
  type: project
---

Board GraphQL IDs, confirmed working 2026-08-16 via a full-board write pass
(all 36 open issues added, Status/Priority/Awaiting set on every card):

- Project id: `PVT_kwHOACEigM4Bgiwa`
- Status field: `PVTSSF_lAHOACEigM4Bgiwazhfh7Mg` — options: Backlog `f75ad846`,
  Analysis `012dae50`, Ready for Dev `456880aa`, In Progress `47fc9ee4`,
  In Review `58ad8ead`, Done `98236657`
- Priority field: `PVTSSF_lAHOACEigM4Bgiwazhfh7NQ` — options are **P1 `131c5c2f`,
  P2 `107b9947`, P3 `6d4b1494`, P4 `4d153125`. There is no P0 option** — the
  "P0 da61340b" that older skill and task text referenced does not exist on
  the live field. Treat P1 as the top tier.
- Awaiting field: `PVTSSF_lAHOACEigM4Bgiwazhfh7Nw` — options: reporter
  `71ef723a`, discussion `82098dd9`, upstream `16ca2f41`, analysis `c7538747`

Mutation shape that works: `addProjectV2ItemById(input: {projectId, contentId})`
to add a card (contentId = issue node id from `gh issue list --json id`), then
`updateProjectV2ItemFieldValue(input: {projectId, itemId, fieldId, value:
{singleSelectOptionId}})` per field. Run via
`scripts/gh-agent.sh --as po api graphql -f query='...' -f name=value ...`
from inside the repo checkout (it resolves `.env` via `git rev-parse
--git-common-dir`, so it fails silently with "BESS_PO_TOKEN not set" if run
from a non-repo cwd like a scratch tmpdir).

See [[project_backlog_board_state_2026_08_16]] for what was actually on the
board before/after this pass.
