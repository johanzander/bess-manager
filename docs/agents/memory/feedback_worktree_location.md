---
name: Worktree location
description: Sibling worktrees and native .claude/worktrees are both first-class; pick by VS Code-inspect/run workflow vs project-scoped Agent View
type: feedback
originSessionId: 3c427ddc-6dd1-4bc2-b841-54e3f1c0f4ba
---
Both layouts are valid — the worktree is a normal git checkout either way, so
per-agent inspect/test/run (`./deploy.sh`, `pytest`, the app) works the same.

**Sibling folders** (`../bess-manager-<name>`) — open cleanly in their own VS
Code window; the go-to when actively inspecting/running each agent's work. They
work with Agent View too: start the background session *inside* the sibling and
Claude won't relocate it (it's already a linked worktree). Caveat: a sibling only
shows in **unscoped** `claude agents` (or `--cwd ~/GitHub`), not in the
project-scoped `claude agents --cwd <repo>` view.

**Native `.claude/worktrees/`** (`claude agents` / `--worktree` /
`EnterWorktree`) — auto-created for background sessions, visible in the
**project-scoped** Agent View. Reach it with `code <repo>/.claude/worktrees/<name>`
or `cd`.

**Why:** The user needs to inspect code and run scripts per agent (which is why
sibling worktrees + VS Code were adopted). Agent View does NOT take that away —
it's a session dashboard, not an IDE, and every session's worktree is a real
folder. So siblings remain first-class; native is only required when you want the
project-scoped Agent View list.

**How to apply:** Default to sibling worktrees for hands-on VS Code work
(`git worktree add ../bess-manager-<name> -b <branch>`); view Agent View unscoped
(`claude agents`) to see them. Use native `.claude/worktrees/` when you want the
project-scoped dashboard. Find a session's path via `claude agents --json` (`cwd`).
