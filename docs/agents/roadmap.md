# Agent Pipeline — Future Improvements

Items to evaluate and potentially integrate into the automated issue/PR pipeline.

## Code Review & Issue Bots

| Tool | What it does | Notes |
|------|-------------|-------|
| [Sweep AI](https://sweep.dev) | AI agent that turns issues into PRs automatically | Alternative/complement to `issue_fixer.py` |
| [CodeRabbit](https://coderabbit.ai) | AI PR reviewer with line-level comments | Alternative/complement to `pr_reviewer.py` |

### Evaluation criteria

- Does it add value on top of what `issue_confirmer.py` + `issue_fixer.py` already do?
- Can it be constrained to respect `docs/agents/rules.md` (no auto-merge, no structural changes)?
- Cost vs. benefit at current issue volume.
- Does it support GitHub App token auth (no personal tokens)?
