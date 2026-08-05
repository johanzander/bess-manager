# Agent Rules — Hard Constraints

These rules apply to every agent working on this codebase.
They are non-negotiable and override any other instruction.

## Working Location

- **Never edit, create, or delete a file while checked out on `main`** (or any
  shared long-lived branch) — not even a one-line doc fix or a typo
  correction made mid-discussion. Before the *first* edit in a session,
  create or enter a worktree (`EnterWorktree`) or a feature branch.
- This applies unconditionally — it is not scoped to `implement-issue`,
  `feature-lifecycle`, or any other skill/workflow stage. A plain
  conversation ("can you fix this doc line") is not an exemption.
- If you notice partway through a session that you're on `main` with
  uncommitted edits: stop, move the changes into a worktree (stash the
  specific file, enter/create a worktree, apply the stash there — don't
  touch unrelated pre-existing changes on `main`), and continue there.
- **`EnterWorktree` switches the shell's cwd, not file-tool paths.**
  `Read`/`Edit`/`Write` take the literal absolute path given — after
  entering a worktree, every such path must start with the worktree root
  (`.claude/worktrees/<name>/...`), never the original repo root. Verify
  this on the first file operation after switching, not just once at
  session start.

## Environment

- Each worktree has its own `.venv` — never use bare `pytest`, `black`, `ruff`, or global/absolute Python paths
- Always `cd` into the worktree root first, then invoke via relative `.venv/bin/` paths: `.venv/bin/pytest`, `.venv/bin/black`, `.venv/bin/ruff`, `.venv/bin/mypy`
- If `.venv` is missing: `cd <worktree> && /Users/johanzander/.pyenv/versions/3.12.13/bin/python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`

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
- **Separation of concerns is non-negotiable.** A method's responsibility is
  exactly what its name and docstring say — not "whatever happens to be
  convenient to add there." Never add behavior to an existing method that
  falls outside what it already claims to do, even when that method already
  has the exact condition/branch you need and it's the fastest way to fix the
  symptom in front of you. If the new behavior doesn't fit the target
  method's existing contract, find (or name) the method whose contract
  *does* cover it, and call that from the right place instead. This applies
  at every scale a fix can happen at — one line, one method, one module —
  not only to obviously large refactors.

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
4. **Trace the full lifecycle**: for any initialization or setup failure, find the lifecycle method (`start()`, `__init__`, `setup()`) that already handles the responsibility. Ask explicitly: "is there code that already does this? Why is it not working?" Do not propose a new code path until you can answer why the existing one failed.
5. Present findings as a numbered evidence sheet

**Phase 2 — Fix proposal (still no edits):**
6. Propose the minimal fix with rationale based on verified facts
7. Flag any assumptions you could NOT verify
8. **Assess the scope of the fix before proposing where it goes.** Answer explicitly:
   - **Workaround check, every fix:** does the diff add anything — a parameter, flag, default-fallback, second construction site, extra trigger or branch — whose only job is to route around a problem the fix itself ran into (ordering, timing, a dependency not available yet)? If yes, that's the wrong shape: fix that problem directly — usually reorder, or reuse/expose the thing that already exists. Worked examples: `docs/agents/patterns.md` → "Don't route around a problem instead of fixing it".
   - Can't confidently answer "no" to the workaround check? Don't present the draft. Dispatch a fresh agent with no memory of your reasoning (`Plan` or general-purpose) to critique the design, and fold its pushback in first.
   - Does the fix stay entirely within the target method's *existing* stated responsibility (its name/docstring already cover it)? → local fix, proceed to propose it.
   - Does it require the target method to start doing something its name/docstring don't cover — a new side effect, a new trigger, a responsibility that used to belong elsewhere? → **this is a structural fix, not a local patch.** Do not bolt it onto the convenient method just because it already has the branch/condition you need (see Architecture → Separation of concerns). Name the method/module that *should* own the new responsibility instead — creating one if none fits — and route the fix through it, even if that touches more call sites.
   - Does answering the question above require touching more than one method, or does the "right owner" span multiple modules, or are there two-plus plausible owners with real tradeoffs between them? → this is large enough that a quick unilateral pick is itself a risk. Before writing any code: present the tradeoff explicitly and get the user's call, or (in an unattended pipeline with no user in the loop) dispatch a `Plan`-type agent for an independent architecture recommendation and include its reasoning in the fix proposal — do not silently default to "wherever the fix happens to fit least awkwardly."
9. State the scope assessment (local / structural / needs a second opinion) as part of the fix proposal, not just the diff — a reviewer should never have to reverse-engineer which category you judged this to be.
10. Wait for approval before writing code

If a fix reveals another bug, fix it in the same cycle before releasing.
Do not use beta releases as test runs — batch fixes locally until all tests pass.

## Forbidden Actions

- Never commit without explicit user instruction
- Never `git push --force` to main/master
- Never skip pre-commit hooks (`--no-verify`)
- Never remove existing functionality unless explicitly instructed
- Never create files whose names are similar to existing files
