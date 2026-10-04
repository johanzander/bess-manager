#!/usr/bin/env python3
"""Fail when an agent-guidance file differs from its recorded line budget.

Caps are exact (a ratchet): growth must be paid for by pruning, and a prune
must lower the cap so the room it frees is not spent silently.

Every fix PR carries an `## Escape analysis` (see `.claude/skills/implement-issue/SKILL.md`
Step 9) that may add guidance. Without a ceiling, each PR adds a line and the
non-negotiable files stop carrying weight. The ceilings live in
`docs/agents/guidance-budget.txt`, one `<path> <max-lines>` per line.

Adding guidance past a ceiling means pruning something else in the same change.
Raising a ceiling is allowed, but it is a visible diff to the budget file that
the Stage 4 reviewer must accept — state the reason in the PR's Escape analysis.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET_FILE = ROOT / "docs" / "agents" / "guidance-budget.txt"


def main() -> int:
    failures = []
    for raw in BUDGET_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, limit = line.rsplit(maxsplit=1)
        actual = len((ROOT / path).read_text().splitlines())
        if actual > int(limit):
            failures.append(f"{path}: {actual} lines, budget {limit} (over)")
        elif actual < int(limit):
            failures.append(
                f"{path}: {actual} lines, budget {limit} (under: lower the cap to {actual})"
            )
    if failures:
        print("Guidance files off budget:")
        for failure in failures:
            print(f"  {failure}")
        print(
            "Over: prune or merge existing guidance, or raise the cap in "
            "docs/agents/guidance-budget.txt and state why in the PR's Escape "
            "analysis. Under: lower the cap, so freed room is not spent silently."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
