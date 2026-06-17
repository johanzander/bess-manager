# Feature Lifecycle Skill

Drive a new integration feature (e.g. a price provider or inverter platform)
through its **full lifecycle**: research → ship experimental → collect a real
user config → lock it into the regression suite → re-ship green → user confirms
→ graduate (strip "experimental"). Designed to be run by an autonomous agent
that communicates with the user **in the PR and the originating issue**, runs
the `release` skill, and polls CI between human gates.

This skill orchestrates other skills — it does not re-implement them:
- **Implementation** → `add-price-provider` (or the equivalent for the feature).
- **Deployment** → `release` (`release beta`, then `release` for prod).

## Operating principles for the autonomous agent

- **Gates are human-in-the-loop.** Stages 2 and 5 wait for the user. Do not
  fabricate logs or confirmation. Post a clear ask, then stop and poll.
- **Communicate in the open.** Use `gh pr comment` / `gh issue comment` for every
  ask and every result. The PR is the source of truth for lifecycle state.
- **Never claim real-world validation** until Stage 5. Keep the `experimental`
  marker until the user confirms against their own hardware.
- **Track state with a checklist** in the PR body (one box per stage) so a
  resumed agent knows where it is.
- Honour repo rules: tests green before push, draft PRs, beta vs prod remotes
  (`release` skill owns the remote logic), CHANGELOG always updated.

## Stage 1 — Research, implement, ship experimental

1. Run the **implementation skill** end-to-end (`add-price-provider`): verified
   discovery from integration source, source class + wiring + frontend, unit +
   discovery tests, a **source-derived** scenario fixture, and the wizard E2E.
2. Mark the feature **experimental** everywhere the user sees it:
   - UI: provider/platform option label or help text (e.g. "(experimental)").
   - Docs: `README.md` tag + `docs/USER_GUIDE.md` note.
3. Open a **draft PR** against `main`, `Closes #<issue>`. Put the lifecycle
   checklist in the body (see template below).
4. Ship to beta: run `release beta`. Comment on the issue that an experimental
   build is available and **ask the user to install it and report back**.
- **Exit:** beta build published, issue comment posted requesting a trial.

## Stage 2 — User provides logs (GATE)

The user installs the experimental build and exports a **debug report**
(`docs/bess-debug-*.md`) — which includes the **entity snapshot** (their full
config: inverter platform, sensors, and the new provider entity).

1. Poll the issue/PR for the user's debug log (or a "it works / it doesn't"
   report). If absent, wait — re-ask politely on a sensible cadence.
2. When the log arrives, **verify it against the real data**:
   - Confirm the new integration's entity + attributes are present and parse.
   - If discovery/parse fails, this is a real bug — loop back to Stage 1
     (fix, re-ship beta) before proceeding. Do not skip.
- **Exit:** a real debug log is in hand and the feature demonstrably works on it.

## Stage 3 — Lock the user's real config into the regression suite

This is the durable payoff: the user's **whole rig** becomes a permanent
regression test, not just the price source — so their inverter, sensors, and
provider together never silently break.

1. Generate a verbatim-replay scenario from their log:
   ```
   python scripts/mock_ha/scenarios/from_debug_log.py docs/bess-debug-<ts>.md
   # → scripts/mock_ha/scenarios/<ts>.json  (every entity state, verbatim)
   ```
2. **Anonymize**: strip/replace serial numbers, device IDs, API keys, MPANs,
   coordinates, and any account identifiers — keep the structure and entity
   shapes. (The debug export allowlist already drops most secrets; double-check
   the snapshot.)
3. Add an `expected_discovery` block (and `required_sensors`) so the scenario
   runs as a **discovery regression** in `test_scenario_discovery.py`.
4. Wire it into the **frontend wizard E2E** too: `wizard-expectations.ts`,
   `setup-wizard.spec.ts` (if a new provider label/branch is needed),
   `e2e/run-e2e.sh`, and `.github/workflows/ci.yml` (per-scenario step).
5. Rename the fixture meaningfully (e.g. `ci-wizard-<provider>-<user>.json`) and
   reference the issue number in its `description`.
- **Exit:** the user's anonymized config is a green regression scenario in both
  the backend suite and the frontend E2E.

## Stage 4 — Re-ship, all tests pass

This stage is usually a **loop of rapid minor fixes** (the feature can't be
self-validated, so issues surface only against real configs). **Batch them** —
do NOT cut a beta release + CHANGELOG entry per fix; that spams users and the
changelog. Accumulate fixes as commits on the PR and cut a *consolidated* beta
drop only at a meaningful checkpoint, with one combined CHANGELOG entry.

1. Local gate on each iteration: `pytest -m "not slow"`, `black`/`ruff`,
   `tsc`/`vitest`/build, and the new scenario's wizard E2E.
2. At a checkpoint (not per fix): `release beta` with the accumulated fixes +
   regression fixture, one consolidated CHANGELOG entry.
3. **Poll CI** until green:
   ```
   gh pr checks <pr> --repo <repo> --watch
   ```
   On failure: `gh run view <id> --log-failed`, fix locally, re-push, re-poll.
   Keep batching — fold the CI fix into the same checkpoint, don't cut a new
   release for it.
- **Exit:** beta CI green with the user's scenario in the matrix.

## Stage 5 — User confirms (GATE)

1. Comment on the issue/PR: the regression test for their config is in and CI is
   green — **ask them to confirm the experimental build works as expected.**
2. Wait for explicit confirmation. If they report a problem, loop to Stage 1/2.
- **Exit:** user has confirmed it works on their hardware.

## Stage 6 — Graduate (remove experimental)

1. Strip the `experimental` markers added in Stage 1 (UI label/help, README tag,
   USER_GUIDE note).
2. Update the maturity record (the project maturity memory / docs) to list the
   feature as real-world tested, crediting the confirming user's scenario.
3. Run the production `release` skill (`release` / `release prod`): version bump,
   CHANGELOG "Added — now stable", PR to `origin/main`, CI green, tag, GitHub
   Release.
4. Mark the PR ready (un-draft), ensure it closes the issue, and post a final
   thank-you comment to the user.
- **Exit:** feature stable in a production release; issue closed.

## PR body checklist template

```
### Lifecycle: <feature> (#<issue>)
- [x] 1. Implemented + shipped experimental (beta vX.Y.Zb_)
- [ ] 2. User debug log received + verified
- [ ] 3. Anonymized user-config regression scenario added (backend + E2E)
- [ ] 4. Re-shipped beta, CI green
- [ ] 5. User confirmed on their hardware
- [ ] 6. Experimental removed, promoted to stable (prod vX.Y.Z)
```

## Reference

| Concern | Where |
|---------|-------|
| Implementation steps | `.claude/skills/add-price-provider/SKILL.md` |
| Beta + prod deploy | `.claude/skills/release/SKILL.md` |
| Debug log → scenario | `scripts/mock_ha/scenarios/from_debug_log.py` |
| Backend regression harness | `core/bess/tests/unit/test_scenario_discovery.py` |
| Frontend wizard E2E | `e2e/tests/setup-wizard.spec.ts`, `e2e/run-e2e.sh`, `.github/workflows/ci.yml` |
| Maturity record | project maturity memory (`docs/agents/memory/`) + `README.md` |
| Agent comms | `gh pr comment`, `gh issue comment`, `gh pr checks --watch` |
