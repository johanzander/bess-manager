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
3. **Separation of concerns** (`docs/agents/rules.md` → Architecture, and → Debugging Protocol's fix-scope-assessment step): for every line added to an *existing* method, does it match what that method's name and docstring already promise? A diff that adds a side effect outside a method's stated contract — because that method happened to already have the branch/condition needed — is a CONFIRMED finding regardless of whether tests pass. Grep the method's other call sites and check whether any of them run at a different point in the lifecycle (startup vs periodic vs on-demand) than the one the fix targets. Worked example: `docs/agents/patterns.md` → "Don't route around a problem instead of fixing it" (issue #399).
4. **Workaround check:** does the diff add anything — a parameter, flag, default-fallback, second construction site, extra trigger or branch — whose only job is to route around a problem the fix ran into (ordering, timing, a dependency not available yet) rather than fix it? If yes, CONFIRMED finding regardless of whether tests pass; the direct fix is usually to reorder or reuse/expose the thing that already exists. Worked example: `docs/agents/patterns.md` → same section (issue #440).
5. Does the PR description state the fix's scope assessment (local fix within an existing method's contract vs. structural fix routed to a new/different owner vs. escalated for a second opinion), per `rules.md`'s Debugging Protocol step 9? If a structural-looking change has no such statement, ask for it rather than guessing which category the author judged it to be.

Name specific failure modes or better alternatives when they exist.

## Agent documentation

Full coding rules: `docs/agents/rules.md`
Architecture reference: `docs/agents/architecture.md`
Code patterns: `docs/agents/patterns.md`
Testing guidelines: `docs/agents/testing.md`
Workflow and process: `docs/agents/workflow.md`
