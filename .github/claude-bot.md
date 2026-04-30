# Claude Bot Review Configuration

## Review checklist

Every PR review must cover these aspects, in addition to anything explicitly requested.

### Architecture compliance (`docs/agents/rules.md`)

- No `Optional[x]` — must use `x | None`
- No `hasattr`, `getattr` with defaults, or silent fallbacks
- No new classes created without approval
- All sensor access through `ha_api_controller` and `METHOD_SENSOR_MAP`
- No hardcoded entity IDs or device names
- All API responses use `convert_keys_to_camel_case()`

### Error handling

- No exception message string matching (`if "..." in str(e)` is forbidden)
- New exception types belong in `core/bess/exceptions.py`

### Code quality

- Python: Black, Ruff, mypy must pass (zero warnings)
- TypeScript: ESLint and tsc must pass
- No comments explaining what code does — only non-obvious WHY

### Tests (`docs/agents/testing.md`)

- Tests check behavior, not implementation details
- No tests of specific field names, algorithm boundaries, or exact interval counts
- Tests should survive an equivalent algorithm swap

### Security

- No credentials, tokens, or secrets in code
- No injection vectors (XSS, SQL injection, command injection)

### Fitness of approach

For every substantive change, ask:

1. Is this the best available solution, or merely better than what it replaced?
2. Does it hold for all valid inputs and configurations, not just the case that triggered it?

Name specific failure modes or better alternatives when they exist.

## Agent documentation

Full coding rules: `docs/agents/rules.md`
Architecture reference: `docs/agents/architecture.md`
Code patterns: `docs/agents/patterns.md`
Testing guidelines: `docs/agents/testing.md`
Workflow and process: `docs/agents/workflow.md`
