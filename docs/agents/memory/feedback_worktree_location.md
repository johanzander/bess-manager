---
name: Worktree sibling location
description: User prefers worktrees as sibling folders, not inside .claude/worktrees/
type: feedback
originSessionId: 3c427ddc-6dd1-4bc2-b841-54e3f1c0f4ba
---
Create worktrees as sibling folders to the main repo (e.g. `../bess-manager-feature-name`), not inside `.claude/worktrees/`.

**Why:** The `.claude/worktrees/` path is hard to find and open in VS Code. Sibling folders are easy to navigate to and open for local testing.

**How to apply:** Use `git worktree add ../bess-manager-<name> -b <branch>` instead of the `EnterWorktree` tool.
