# Agent Fleet Sandboxing — Plan

Execution scaffolding for Phase 1 of
`docs/superpowers/specs/2026-08-20-agent-fleet-sandbox-router-design.md`
("Real sandboxing (local containers)") only — the dashboard (Phase 2) and
model routing (descoped) are not covered here. Delete this file once the
code is the source of truth, per this repo's own convention; keep the spec.

Exit criteria this plan drives toward (from the spec, verbatim): one full
`implement-issue` run, start to finish, inside a container, with a
permissive in-container permission mode and zero manually-added allowlist
rules for that run.

## 0. Prerequisites (one-time, before any task below)

- Confirm `podman machine` is running (`podman machine start` if not —
  already allowlisted in `.claude/settings.json`).
- Decide and record the container base image target: Python 3.13 (must
  match `ci.yml`'s pinned version, per that workflow's own comment about
  why), Node (match `frontend/package.json`'s engines field), `gh` CLI,
  the `claude` CLI, and whatever Playwright needs system-side (`ci.yml`'s
  Playwright cache paths give the list).

## 1. Repo scaffolding

1.1. Add to `.gitignore`: `.agent-clones/`, `.fleet/`. Verify:
     `git check-ignore .agent-clones/x .fleet/manifest.db` both match.

1.2. Create `.fleet/` directory with a `.gitkeep` is unnecessary — the
     directory is created at first `run-agent.sh` invocation; skip.

## 2. Fleet manifest (SQLite, `.fleet/manifest.db`)

2.1. Write `scripts/fleet-manifest.sh` (or a small Python module if the
     surrounding scripts end up Python-heavy — match whatever
     `run-agent.sh` ends up being written in) exposing four operations:
     `register <clone_path> <issue> <branch> <container_id> <role>`,
     `update-status <container_id> <status>`, `get <container_id>`,
     `list [--status X]`. Schema:

     ```sql
     CREATE TABLE dispatches (
       container_id TEXT PRIMARY KEY,
       clone_path   TEXT NOT NULL,
       issue_or_pr  INTEGER,
       branch       TEXT,
       role         TEXT NOT NULL,   -- 'dev' | 'po'
       status       TEXT NOT NULL,   -- 'working' | 'needs_input' | 'in_review' | 'escalated' | 'done'
       started_at   TEXT NOT NULL
     );
     ```

     Resolve the db path the same way `gh-agent.sh` resolves `.env`:
     `git rev-parse --git-common-dir`, so it works from a clone directory
     too, not just the main checkout.

2.2. Verification: from a scratch tmpdir, register a fake dispatch, list
     it back, update its status, confirm the update is visible. No live
     container needed for this step.

2.3. Enforce the `product-owner` singleton rule here, not later: `register`
     refuses (non-zero exit, clear stderr message) a second `role=po` row
     while one with `status != 'done'` already exists.

## 3. `scripts/run-agent.sh` — clone + setup (spec section: "Why containers
   change the calculus on worktrees vs. clones")

3.1. Argument: an issue or PR number (`run-agent.sh 502`), same contract
     `implement-issue` Step 0 already parses (number could be either).

3.2. Clone step:

     ```bash
     clone_dir=".agent-clones/issue-${n}"
     git clone --reference "$(git rev-parse --show-toplevel)" --dissociate \
       --branch main origin "$clone_dir"
     ```

3.3. Dependency setup — port `worktree-setup.sh`'s symlink logic to also
     accept a clone-dir target (it's currently worktree-specific; check
     whether it already generalizes or needs a `--target-dir` flag added).
     Symlinks must be **read-only** from the container's perspective — the
     symlink itself is fine to create normally; read-only enforcement
     happens at the container mount step (4.3), not here.

3.4. Verification: run 3.1–3.3 by hand for a real issue number, `cd` into
     the resulting clone dir, confirm `.venv/bin/pytest -m "not slow"`
     runs immediately with no install step, confirm `git log`/`git status`
     behave like a normal repo (independent of the main checkout).

## 4. Containerfile + `run-agent.sh` container start

4.1. Write `Containerfile.agent` (or similar name — check whether one
     already half-exists given `podman-compose` is already in use) from
     the base image decided in Task 0.

4.2. `run-agent.sh` continues: start the container with:
     - the clone dir bind-mounted at the container's workdir (one mount,
       per the spec — no separate dependency mount, the symlinks from 3.3
       are already inside it)
     - `BESS_AGENT_TOKEN` or `BESS_PO_TOKEN` injected per role (never the
       maintainer's own `gh auth`)
     - network egress limited to GitHub + api.anthropic.com (no router
       endpoint — out of scope per the finalized spec)
     - a permissive `defaultMode` in the container's own
       `.claude/settings.json` override (mounted or baked into the image —
       decide which; baked-in is simpler and the container is disposable
       either way)

4.3. Enforce read-only on the dependency symlinks specifically: mount
     `.venv`/`node_modules` (the targets the symlinks point at) read-only
     even though the clone dir itself is read-write. Verify: from inside
     a running container, `.venv/bin/pip install some-harmless-package`
     should fail with a read-only-filesystem error, not silently succeed.

4.4. Register the dispatch in the manifest (Task 2) immediately after the
     container starts, before any real work happens — this is what makes
     the container visible to Step 0's resume-check even if it dies in
     the first second.

4.5. Verification: `podman ps` shows the container; `.fleet/manifest.db`
     has a matching row; `cd` into the clone dir from the host (separately
     from the container) and confirm it's a normal, working checkout per
     3.4 — this double-checks the bind mount didn't change anything about
     host-side accessibility.

## 5. `scripts/wait-for-reply.sh` — the one new blocking-wait primitive

5.1. Signature: `wait-for-reply.sh <issue-or-pr-number> <since-iso8601>`.
     Polls `gh issue view <n> --json comments` / `gh pr view <n> --json
     comments` (whichever the number resolves to, same resolution
     `implement-issue` Step 0 already does) every 60–120s, exits 0 and
     prints the new comment body the moment one appears with
     `created_at > since`.

5.2. Verification: run it against a real (or throwaway test) issue in one
     terminal, post a comment from another terminal/browser, confirm it
     returns promptly with the right content and exits 0.

## 6. Teach `implement-issue` a "Headless local mode" — mirrors the
   existing "CI mode" table, doesn't duplicate the CI mode table itself

6.1. Add a new section to `.claude/skills/implement-issue/SKILL.md`,
     structurally parallel to the existing "## CI mode (GitHub Actions)"
     table, for headless-but-not-CI dispatch (i.e., running inside a
     Phase 1 container via `run-agent.sh` rather than via
     `claude-code-action`). Key rows:
     - Step 3 / Step 7 confirm gates: post via `gh-agent.sh --as dev`,
       then call `wait-for-reply.sh` and continue in-process on return —
       **not** the CI-mode behavior of stopping the whole run or
       delegating the gate to a separate trigger comment.
     - Step 10 (watch to green) and Step 11 (`advance-pr` loop): apply
       verbatim, unchanged from interactive mode — these already don't
       ask, and headless execution doesn't change that.
     - Step 8 (local run & observe): applies, unlike CI mode which skips
       it — but only on a `--with-compose` dispatch, the only one that
       mounts the podman socket (the socket is authority over the host,
       so it is opt-in by design; see `scripts/lib/agent-dispatch.sh`). A
       plain dispatch follows CI mode's skip-and-say-so rule.

6.2. This is a documentation/process change, not code — but it's the
     piece that makes `run-agent.sh` actually correct rather than just
     "a script that happens to start a container." Treat it as load-bearing
     as any of the code tasks above.

6.3. Verification: read the new table against every numbered step in the
     main body and confirm every step that could plausibly block has an
     explicit headless-mode row — the same completeness check the existing
     CI-mode table passes.

## 7. `product-owner`'s continuous-loop container

7.1. A separate small script, `scripts/run-po.sh` (no issue argument) —
     creates its clone once (Task 3's logic, reused), starts its container
     once, and inside the container runs a loop: `git pull`, one
     `claude -p "/backlog"` pass, sleep (interval TBD — start at 15–30 min,
     matching Rhythm's existing informal cadence), repeat.

7.2. Registers itself in the manifest with `role=po` (Task 2.3's singleton
     check fires here if a second one is started by mistake).

7.3. Verification: start it, confirm one backlog pass completes and the
     board/comments update exactly as an interactive `/backlog` pass would;
     leave it running and confirm a second pass fires after the sleep
     interval without manual intervention.

## 8. End-to-end exit criteria (do this last, only once 1–7 are done)

8.1. Pick one real, currently-open, genuinely small issue.

8.2. `run-agent.sh --with-compose <n>` and don't touch anything else —
     the flag is what makes Step 8 runnable from inside the container, and
     Step 8 is part of the flow being validated. Let it run to a merged PR
     (or as far as a real confirm gate takes it, answered through the
     normal GitHub-comment flow from Task 6).

8.3. Confirm afterward: zero new lines added to `.claude/settings.json`'s
     `allow`/`deny`/`ask` lists for anything that happened during this run
     (the actual pass/fail signal for "the permission allowlist problem is
     solved," per the spec's stated Goal).

## Explicitly not in this plan

- Phase 2 (the fleet dashboard) — separate plan, once this one's exit
  criteria are met.
- Model routing — descoped from the spec entirely; would be its own spec
  and plan if picked up later.
- Moving any of this to the headless Linux box — stays laptop-only per the
  spec's non-goals.
