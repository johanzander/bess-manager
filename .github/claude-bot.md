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
- If the diff adds or changes an HA entity, service call, or REST endpoint
  the backend depends on, `scripts/mock_ha/server.py` and a scenario under
  `scripts/mock_ha/scenarios/` should cover it — a client-side unit test with
  stubbed responses is not enough on its own. If the feature it belongs to
  hasn't merged yet, this is fine to defer to that PR, but say so explicitly
  rather than silently skipping it (#782).

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

6. **One fact, one declaration** (`docs/agents/rules.md` → Architecture): does the diff encode a fact (a slot count, a required-key list, a platform capability) that is already encoded elsewhere, or add a filter / hand-listed subset that narrows another list? CONFIRMED finding regardless of whether tests pass. Grep the literal across `backend/` and `core/` (e.g. `tou_time_`, `[2-9]`, the count) and check every hit derives from one declaration. Worked example: `docs/agents/patterns.md` → "One fact, one declaration" (issue #794).

7. **Escape analysis and guidance budget** (fix PRs; `implement-issue` Step 9): is the `## Escape analysis` section present, with all four fields filled from evidence rather than "n/a"? Missing or vague is a CONFIRMED finding, like missing mutation evidence; a `pending Step 11` stub is fine while the PR is a draft awaiting its first review. If the diff edits `docs/agents/`, `.claude/skills/`, `.claude/agents/` or this file, check that: a prose rule is justified over a mechanical guard or skill step, states a generic principle with a `(#NNN)` origin, and has a second documented escape of the same class; it replaces or merges an existing rule rather than only appending; and any raise to `docs/agents/guidance-budget.txt` has a stated reason you accept. A rule that names an instance instead of a principle, or a cap raised to fit an appended rule, is a CONFIRMED finding.

Name specific failure modes or better alternatives when they exist.

## Agent documentation

Full coding rules: `docs/agents/rules.md`
Architecture reference: `docs/agents/architecture.md`
Code patterns: `docs/agents/patterns.md`
Testing guidelines: `docs/agents/testing.md`
Workflow and process: `docs/agents/workflow.md`
