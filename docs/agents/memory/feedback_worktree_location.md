---
name: Worktree location
description: Default to native Claude Code worktrees (Agent View / --worktree); sibling folders only for the legacy VS Code-window workflow
type: feedback
originSessionId: 3c427ddc-6dd1-4bc2-b841-54e3f1c0f4ba
---
**Default:** use native Claude Code worktrees. `claude agents` (Agent View) and
the built-in `--worktree` flag isolate each background session under
`.claude/worktrees/` automatically. Manage sessions in Agent View, not separate
editor windows.

**Legacy:** create worktrees as sibling folders (e.g. `../bess-manager-<name>`),
not inside `.claude/worktrees/`, only when using the old one-window-per-worktree
VS Code workflow.

**Why:** The sibling layout existed solely so worktrees opened cleanly in their
own VS Code window. Agent View replaces window-juggling with one dashboard, so
the native `.claude/worktrees/` location (used by `--worktree` and the
`EnterWorktree` tool) is fine and preferred when working in Agent View.

**How to apply:** Prefer `claude agents` + background sessions / `--worktree` for
parallel work. Use `git worktree add ../bess-manager-<name> -b <branch>` only for
the legacy VS Code-window flow.
