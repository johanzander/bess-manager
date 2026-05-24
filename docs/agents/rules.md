# Agent Rules — Hard Constraints

These rules apply to every agent working on this codebase.
They are non-negotiable and override any other instruction.

## Python

- Use `x | None`, never `Optional[x]` (no `Optional`/`Union` imports from `typing`)
- Never use `hasattr`, `getattr(obj, key, default)`, or any silent fallback
- Explicit failure over silent degradation — raise or assert, never degrade gracefully
- All code must pass `black`, `ruff check`, `mypy` with zero errors/warnings

## Architecture

- All HA sensor access goes through `ha_api_controller` and `METHOD_SENSOR_MAP`
- Never hardcode device names or entity IDs — use centralized mapping
- **Never create a new class without explicit user approval**
- Extend existing components; never build parallel implementations
- Search for existing code before writing new code

## Key Files — Read Before Changing Anything

| File | Purpose |
|------|---------|
| `backend/api_dataclasses.py` | API models — use these, do not create new ones |
| `backend/api_conversion.py` | Serialization utilities — use these |
| `core/bess/exceptions.py` | Exception types — add here, nowhere else |
| `core/bess/ha_api_controller.py` | All sensor/device access |
| `frontend/src/types.ts` | TypeScript interfaces — keep in sync with backend |

## API Layer

- All API responses must use `convert_keys_to_camel_case()` from `api_conversion.py`
- Use `APIBatterySettings`, `APIPriceSettings` — never create ad-hoc response dicts

## Error Handling

- **Never** match on exception message strings (`if "price data" in str(e)` is forbidden)
- Create specific exception types in `core/bess/exceptions.py` when needed

## Comments

- Never comment what code does — well-named identifiers do that
- Only comment the non-obvious WHY: hidden constraints, workarounds, subtle invariants

## Testing

- Tests must verify **behavior** (what the system does), not **implementation** (how)
- A test that breaks when an equivalent algorithm replaces another is a bad test
- Never test: internal field names, algorithm-specific boundaries, exact interval counts

## Debugging Protocol

When fixing bugs, follow this two-phase approach:

**Phase 1 — Investigation (read-only, no edits):**
1. Reproduce or verify the bug from logs/error output — do not guess at root causes
2. Read the relevant source code and cite file:line for each finding
3. List all callers and consumers of the affected code path (blast radius)
4. Present findings as a numbered evidence sheet

**Phase 2 — Fix proposal (still no edits):**
5. Propose the minimal fix with rationale based on verified facts
6. Flag any assumptions you could NOT verify
7. Wait for approval before writing code

If a fix reveals another bug, fix it in the same cycle before releasing.
Do not use beta releases as test runs — batch fixes locally until all tests pass.

## Forbidden Actions

- Never commit without explicit user instruction
- Never `git push --force` to main/master
- Never skip pre-commit hooks (`--no-verify`)
- Never remove existing functionality unless explicitly instructed
- Never create files whose names are similar to existing files
