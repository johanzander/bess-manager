# Agent Fleet — Sandboxing, Model Routing & Visualization — Design

**Status:** Finalized, nothing implemented yet — ready for implementation.
**Date:** 2026-08-20

## Problem

The interactive track (worktrees + local Claude Code) and the autonomous
track (`issue-triage → issue-analyze → issue-fix → pr-review → issue-integrate`
on `claude-code-action`) both work, but two things cost real time on every
session:

1. **Permissions are a flat allowlist, not a boundary.** `.claude/settings.json`
   pattern-matches Bash command shapes (`Bash(gh pr create *)`,
   `Bash(podman-compose *)`, …) against a real filesystem and real `gh`
   credentials, gated by a macOS `sandbox-exec` config. Every new command
   shape — a new `gh api` flag, a new script — means another manual rule, and
   the `ask` list keeps growing. This is optimizing the wrong lever: it is
   trying to buy safety from pattern-matching instead of from isolation, and
   it does not scale as the skill fleet grows.
2. **No visibility across a growing fleet.** With worktrees regularly in the
   dozens (`implement-issue`'s own audit found 34 dead-session worktrees),
   there is no single place to see which agents are live, what they're
   working on, which model they're running, or what state they're in —
   short of `git worktree list`, `claude agents --json`, and reading through
   `backlog-digest.sh` output by hand.

Separately, the maintainer wants to stop paying Claude-tier prices for every
token of implementation work, using a cheaper model for the coding grind
while keeping Claude for planning/diagnosis quality (`product-owner`,
`bess-analyst`).

## Goals

- Replace pattern-matched permission rules with real isolation, so most
  in-sandbox permission prompts disappear rather than needing another rule.
- Route different agents/tasks to different model providers without
  rewriting the skills or subagents that already encode this repo's process.
- A fleet dashboard: what's running, on what issue, on what model, in what
  state — separate from the GitHub Projects backlog board the `product-owner`
  agent already maintains (that board answers "what's ready to work on";
  this one answers "what's happening right now").
- Ship incrementally. Each phase is independently useful and reversible if
  the next one doesn't pan out.

## Non-goals (v1)

- No cloud sandboxes (Daytona/E2B/etc). Everything runs on the maintainer's
  laptop for v1 — no per-minute cost, no new account, no deployment surface
  beyond what already exists.
- No move to the headless Linux box (n8n, openclaw) yet. The container
  recipe from Phase 1 is designed to be portable there later, but v1 does
  not touch that machine.
- **No sandboxing of interactive, hands-on sessions — confirmed with the
  maintainer, not an oversight.** Containerization applies to *dispatched*
  work only: `run-agent.sh <issue>` for implementers, the continuous loop
  for `product-owner`. Debugging done as yourself, in a Claude terminal,
  keeps running on the host exactly as today, still under the existing
  `.claude/settings.json` allow/deny/ask list. That list's ongoing
  maintenance cost is accepted for this one case rather than solved by this
  design.
- No replacement of Claude Code, the skills, or the subagents. This design
  adds sandboxing and routing *underneath* `implement-issue`, `backlog`,
  `product-owner`, `bess-analyst`, etc. — it does not re-implement any of
  their process.
- No change to the autonomous GitHub Actions track in v1. `issue-fix.yml`
  already runs isolated (a throwaway Actions runner) — the permission-boundary
  problem is specific to the interactive/local track.

## Prior art considered

| Tool | What it is | Verdict |
|---|---|---|
| [Vibe Kanban](https://vibekanban.com/) | Kanban UI for orchestrating multiple coding-agent CLIs via git worktrees; plan/prompt/review columns; auto-updates from issue/PR state. | **Revised, 2026-08-20:** bloop (the company) shut down 2026-04-10; remote/cloud features were cut 30 days later; the project is now "community maintained" open source (Apache 2.0) with no dedicated team. The promised community roadmap had not shipped as of the last check, and there's been no release since 2026-04-24 — four-plus months of apparent inactivity. Star count (27k) is a lagging signal, not evidence of ongoing development. **No longer recommended to build on.** Skip the Phase 0 trial; go straight to the small custom dashboard originally scoped for Phase 3, built on the fleet manifest Phase 1 already requires — that manifest was always the more durable dependency anyway. |
| [claude-code-router](https://github.com/musistudio/claude-code-router) | Local proxy in front of Claude Code; routes requests to different providers (DeepSeek, OpenRouter, Ollama, …) by task type (default/background/think/longContext), with a `<CCR-SUBAGENT-MODEL>` tag for pinning a specific subagent to a specific model. | Adopt for Phase 1 — maps directly onto the existing subagent structure. |
| Cloud sandboxes (Daytona, E2B, Modal) | Managed per-session VM/container sandboxes for agent code execution. | Rejected for v1 per the maintainer's explicit no-cloud-cost, no-new-deployment-surface constraint. Revisit if laptop-local parallelism becomes the bottleneck. |
| Full harness replacement (OpenHands, Aider-as-driver, etc.) | Alternative agent frameworks with their own sandboxing/orchestration. | Rejected — would discard `implement-issue`, `backlog`, `advance-pr`, `sweep-prs`, and the hooks/rules encoded in `docs/agents/`. The permission problem is a config/isolation problem, not evidence the harness itself is wrong. |
| [Crystal](https://github.com/stravu/crystal) | Desktop app for running multiple Claude Code/Codex sessions in parallel worktrees. | **Checked 2026-08-20, same pattern as Vibe Kanban:** deprecated February 2026, superseded by a commercial product (Nimbalyst). Two data points now in this exact space (Vibe Kanban, Crystal) of a VC-backed OSS coding-agent-orchestrator pivoting away from free/open — reinforces building the dashboard in-house rather than adopting a third one. Rejected. |
| [Agent Deck](https://github.com/asheshgoplani/agent-deck) | Terminal (TUI) session manager for AI coding agents — status per session, git-worktree support, Docker sandboxing, GitHub-webhook/push-notification watchers, MIT. | Smaller and less commercially exposed than the two above (615 stars, one maintainer merging PRs within ~24h) — real but modest activity, so still a bus-factor risk, just a cheaper one to take. Directionally close to what the maintainer actually wants here. **Parked, 2026-08-20** — not evaluated now; revisit once Phase 1's own `wait-for-reply.sh`/manifest exist as a baseline to compare it against, rather than trialling it cold. |

## Handing off from an interactive spec session to a dispatched agent

Most of the maintainer's interactive terminal time isn't line-by-line
debugging — it's a conversation about a specific issue or a topic an agent
raised that needs a human decision, the shape of the conversation that
produced this document. `docs/superpowers/specs/` (this file's own
directory) is already that conversation's normal output — the
`superpowers:brainstorming` skill is what produces it, same artifact type
as every other file already in that directory. For a non-trivial bug or
feature request, this stays required: the maintainer stays in the loop for
exactly this session, dispatch only happens after it.

**The gap this session is a live example of:** a spec produced this way
exists only as an uncommitted file on the maintainer's own disk until
someone commits it. Dispatch, per this whole design, works from a fresh
clone of `origin/main` — an uncommitted file on the laptop is invisible to
that clone no matter how the container gets its checkout, because clone
reads committed history, not a working tree. So a spec has to cross that
line before any container can act on it. Concretely:

1. The brainstorming session ends with a file under `docs/superpowers/specs/`,
   as it already does today.
2. **Commit it on a short-lived branch and open a PR — never a direct push,
   for anyone, maintainer included.** Corrected 2026-08-20: an earlier draft
   of this section claimed `#656`'s agent-memory commit landed on `main`
   directly; that's wrong — `(#656)` in a commit message on `main` is
   GitHub's own squash-merge signature, evidence of a PR, not the absence
   of one. The real answer is stronger than that anyway: `implement-issue`
   Step 0 already documents that PR #620 established server-side branch
   protection rejecting pushes to `main`, with no exception list — nobody
   bypasses the PR, not the maintainer, not any bot.
3. **`product-owner` approves it — corrected again, in the same pass.**
   GitHub does not let a PR's own author approve their own PR, so "the
   maintainer opens it and merges it himself" (what an earlier draft of
   this section said) doesn't actually clear branch protection if approval
   is required — someone else has to press approve, same structural reason
   the Developer/Reviewer identities stay separate for agent-authored code.
   For the maintainer's own spec PRs this is a formality, not a real
   review — the judgment already happened in the brainstorming session — so
   `product-owner` (posting as `po`, once its own identity exists per the
   backlogger design) approves automatically: author is the maintainer's
   own account, not a bot, and the filtered CI checks that actually run
   (see the CI overhead discussion above) are green. This is also, not
   coincidentally, the literal Scrum sense of Product Owner — accepting
   completed work is the role's own job, per `product-owner.md`'s own
   framing, not a capability bolted on. **Keep this distinct from the
   flagged trusted-user tier below**, though: approving the maintainer's
   own docs is a rubber stamp with no judgment call in it; approving an
   *agent-authored* implementation PR for a "simple, trusted" issue is real
   judgment replacing what `advance-pr`'s independent review currently
   does, and stays unbuilt until that tier has its own explicit bar.
4. Open (or update) the GitHub issue the work will track, with a line
   pointing at the spec's path rather than restating it — this is what
   gives `run-agent.sh <n>` something to key off, and what `implement-issue`
   Step 1/2 reads.
5. Dispatch: `run-agent.sh <n>`. The container's fresh clone now genuinely
   contains the spec, because it's on `main`.

This document is the worked example: at finalization it was staged on a
branch (`git add`/`git commit`, no network required) directly on the
maintainer's disk via the device bridge, ready for `git push` and `gh pr
create`. The push, the PR, and step 3's PO approval are still the
maintainer's own to complete — pushing requires this session's network
access to reach *his* GitHub, which it doesn't have, and PO's approval
requires the `bess-product-owner` identity to exist first, which per the
backlogger design is a one-time setup step nobody has done yet.

## Architecture

Three shippable phases (a fourth, Phase 0, was scoped and then dropped —
see immediately below), presented in the order they physically appear,
which now matches the sequencing diagram further down: Phase 1 first.

### Phase 0 — Fleet dashboard, no plumbing changes

**Superseded, 2026-08-20.** This phase originally proposed trialling Vibe
Kanban unsandboxed, on the reasoning that it was the cheapest way to
validate the visualization UX before any permission or routing work. Vibe
Kanban's maintaining company has since shut down (see the tool table above)
— building a trial phase around a project with no active team and no
release in four-plus months isn't actually cheap insurance anymore, it's a
dependency on something already in decline. Dropped as a phase; Phase 3
covers the dashboard directly, reading the fleet manifest Phase 1 builds
regardless — see Phase 3's own exit criteria, this phase's would only have
duplicated it.

### Phase 1 — Real sandboxing (local containers)

This is the actual problem being solved — the permission allowlist is a
symptom of running agents unsandboxed, not the problem itself. This phase
retires it rather than routing around it, and is promoted ahead of model
routing for that reason.

**One container per agent, never a shared container running several
agents.** A container running multiple agents just relocates the
filesystem/git contention this phase exists to remove from the host to
inside the container — it solves nothing. Isolation unit = one agent = one
container = one git checkout, always.

**Two different relationships between a `claude` process and a container,
for two different kinds of session — this distinction matters for Remote
Control / `--teleport`.** [Claude Code's Remote Control](https://code.claude.com/docs/en/remote-control)
works by keeping `claude` running **locally the entire time** and relaying
the conversation to phone/browser — "your code execution and filesystem
access stay on your machine." It attaches to a real local process; it has
no defined behavior for a `claude` process whose PID 1 lives inside someone
else's container namespace.

| Session kind | Where `claude` (the interactive process) runs | Where tool execution lands | Remote Control / teleport |
|---|---|---|---|
| **Dispatched implementer** (`run-agent.sh <issue>`, fire-and-forget, Phase 1's main case) | Headless, inside the container (`claude -p` / `--bg`) | Same container | Not needed — nobody's chatting with it live; the Phase 3 dashboard and confirm-gate notifications are how the maintainer checks in, not a resumed conversation |
| **The maintainer's own driven session** (product-owner's "Conversation" surface, ad hoc local debugging — what's actually being teleported/remote-controlled today) | Stays a normal local process on the host, unchanged | Bash/file tool calls proxied into a scoped container (e.g. `podman exec` against that session's container) rather than the whole interactive process moving inside one | Preserved exactly as today — Remote Control only cares that the `claude` process it's attached to is local; it doesn't know or care where that process's shell commands are sandboxed |

So sandboxing and "can I keep chatting with this from my phone" aren't in
tension — they're just two different things being sandboxed (a whole
process vs. that process's shell/file tool calls), applied to two different
session types that already have different expectations today. One
corollary worth restating because it isn't new: Remote Control still needs
the host machine on and reachable, same limitation the backlogger design
already accepts for Rhythm ("follow-up... happens only while the maintainer
is at the machine") — this design doesn't make that better or worse.

`scripts/run-agent.sh <issue-or-pr>`:

1. Creates a **private clone, not a `git worktree`** — see below for why —
   at a host-persistent path (`.agent-clones/issue-<n>/`, sibling to the
   main checkout, gitignored). Runs the `worktree-setup.sh`-equivalent
   setup on it immediately: symlink `.venv` / `node_modules` from the main
   checkout (read-only — see below for why not read-write), same as it
   already does for worktrees, so nothing reinstalls. **This makes the
   clone directory a normal, fully-usable checkout on the maintainer's own
   host filesystem, independent of any container** — the answer to "how do
   I test what an agent built" is the same as it is for a worktree today:
   `cd .agent-clones/issue-<n>/` and run it, no branch switch in your own
   checkout required, nothing container-specific to know.
2. Starts a Podman container (reusing the existing `podman-compose`
   familiarity already in `.claude/settings.json`'s allowlist) with:
   - that same clone directory bind-mounted at the container's working
     directory — one mount, not a separate one for dependencies, since the
     symlinks from step 1 already live inside it
   - a role-scoped `gh` token (`BESS_AGENT_TOKEN` / `BESS_PO_TOKEN`, per
     `gh-agent.sh`'s existing role split) injected as an env var, never the
     maintainer's own credentials
   - network egress limited to GitHub, the Claude API, and the router
     endpoint. **Decided:** one `claude-code-router` instance runs on the
     host (`host.docker.internal:<port>`), shared by every container —
     not one instance per container. One config file holding the routing
     rules, one process, and Phase 1's image needs no router bundled into
     it at all — only egress to the host's port. This is a Phase 1
     decision even though the router itself is Phase 2 work, because it
     determines the container's network policy now.
3. Inside the container, `defaultMode` can be set far more permissively than
   today's host config — the blast radius of "just allow it" is a disposable
   container and a scoped token, not the maintainer's real filesystem and
   real `gh auth`. The macOS `sandbox-exec` block in `.claude/settings.json`
   becomes unnecessary for containerized runs (kept as-is for any session
   still run directly on the host).
4. **Container stays alive for the whole issue lifecycle, not just one
   step.** It runs Steps 4 through 11 exactly as an interactive session
   would — watching CI (`gh pr checks --watch`), self-healing a PR that
   went `CONFLICTING` because another PR merged in the meantime (Step 10's
   existing `git merge origin/main` recovery), and invoking `advance-pr`
   repeatedly through the review loop — for as long as that takes, which
   may be hours across slow CI or multiple review rounds. It exits only at
   the skill's own terminal conditions: the PR merges (see After Merge), or
   a hard stop the skill already defines (Step 12's 3-failed-quality-check
   bailout, Step 11's 3-round `CHANGES_REQUESTED` cap). A genuine judgment
   gate (Step 3, Step 7) pauses that one running process in place — see
   below — it does not end it.

**Exit criteria:** one full `implement-issue` run, start to finish, inside a
container, with a permissive in-container permission mode and zero
manually-added allowlist rules for that run.

#### Why containers change the calculus on worktrees vs. clones

`git worktree` is the right tool for *interactive* parallelism (a handful of
sessions, one maintainer typing, dispatched over minutes) because it avoids
duplicating the object database. But every worktree shares one mutable
substrate with every other worktree: the ref namespace (`refs/`,
`packed-refs`), and anything that rewrites it (`git gc`, `repack`, `prune`,
`reflog expire`, `update-ref`, `tag -d`) — which is exactly the list your
own `.claude/settings.json` already denies. That denylist is evidence the
contention is real, not hypothetical, at today's scale (~30+ worktrees, one
maintainer pacing dispatch by hand).

Containerizing removes the pacing. A dashboard that shows "12 agents
working" invites dispatching 12 at once — concurrent `git fetch --prune`,
branch creation, and push across that many worktrees is exactly the
lock-contention scenario the denylist was built to avoid, now happening at
a rate no human is throttling. **So: don't containerize worktrees. Give each
container a private clone instead.**

```bash
git clone --reference ~/GitHub/bess-manager --dissociate \
  --branch main origin <per-agent-clone-dir>
```

`--reference` sources objects from the local main checkout so the clone is
fast (no network fetch for anything already local) and disk-cheap;
`--dissociate` then drops the dependency on the reference repo, so nothing
about a later `git gc` on the main checkout can ever affect a running
agent's clone. The result is a fully independent `.git` — its own refs, its
own index, its own lockfiles — so N agents cloning, branching, committing,
and pushing concurrently touch zero shared git state with each other. This
also incidentally removes last round's absolute-path gotcha: an independent
clone has no `.git/worktrees/<name>` pointer back to the main repo to keep
in sync with a mount point.

**The cost this moves elsewhere:** `implement-issue` Step 0, `sweep-prs`,
and `backlog-digest.sh` currently treat `git worktree list` on the host as
ground truth for "what's in flight," including for sessions that have
already died — that's how the 34-orphaned-worktree audit found its evidence.
A private clone living only inside an ephemeral container has no such
host-visible trace once the container is gone. Two changes carry that
property forward:

1. **Clone directories are host-persistent, not container-ephemeral** — put
   them at e.g. `~/GitHub/bess-manager/.agent-clones/issue-<n>/` on the host
   and bind-mount into the container, the same pattern worktrees use today,
   just outside the main repo's own `.git/worktrees/` registry. A killed
   container still leaves its clone's commits and uncommitted changes on
   disk for Step 0 to find.
2. **An explicit fleet manifest replaces `git worktree list` as the thing
   Step 0 / `sweep-prs` / `backlog-digest.sh` enumerate.** **Decided:**
   SQLite, not a flat JSON file — N containers writing status updates
   concurrently is exactly the kind of write this whole phase exists to
   make safe, and SQLite's own locking handles that for free where a JSON
   file would need a hand-rolled atomic-write protocol to avoid the same
   class of race this design removed from git. **Decided:** lives at
   `.fleet/manifest.db` under the main checkout, gitignored — never
   committed, resolved the same way `gh-agent.sh` already resolves `.env`
   (`git rev-parse --git-common-dir`), so every clone/container can find it
   regardless of where it's mounted. One record per dispatch (clone path,
   issue/PR, branch, container id/name, status, model, started-at), written
   by `run-agent.sh` on start and read
   by the resume-check instead of git's own worktree registry. This is
   Phase 1 scope, not deferred to Phase 3: the dashboard in Phase 3 reads
   this same manifest rather than inventing a second one.

#### Confirm gates and errors in headless dispatched agents — poll and resume in place, don't exit

The happy path is `implement-issue` running one-shot to a merged PR
unattended. It won't always be the path — Step 3, Step 7, and the hard
review-round cap are designed to stop and ask. **The container must not
exit when that happens.** An earlier draft of this design had it push,
comment, and exit — that throws away exactly the thing this codebase has
already put real work into: Step 10's self-heal of a PR gone `CONFLICTING`
because another PR merged underneath it, and `advance-pr`'s repeated
invocation through the review loop to a terminal state. Killing the process
at every stop and requiring a fresh dispatch to pick it back up would
regress a working, hardened loop back into a sequence of manual restarts —
the opposite of the goal.

**So: one container, alive for the entire issue lifecycle, running the
skill's own steps exactly as an interactive session does — including the
parts that already don't ask.** CI watches (`gh pr checks --watch`),
merge-conflict recovery when another PR lands first, and the `advance-pr`
review-round loop all continue inside the running container with no
maintainer involvement, precisely because the skill already specifies that
behavior — the only thing headless execution changes is *who* is watching
the terminal, not what the process does. The user's merge-conflict scenario
needs no new logic at all: it's Step 10's documented `CONFLICTING` branch,
already written, and it fires correctly as long as the process watching for
it is still running when the other PR merges.

**Only a genuine judgment gate pauses the process — and "pause" means poll,
not exit:**

1. On hitting Step 3, Step 7, or the review-round cap, the container posts
   a comment via `gh-agent.sh --as dev` (to the issue if no branch/PR
   exists yet, to the PR once one does) describing what it needs decided —
   same content as before.
2. The process then polls for a reply on an interval (`gh issue/pr view
   --json comments`, e.g. every 1–2 minutes — cheap while idle, no
   different in kind from `gh pr checks --watch`'s existing blocking wait)
   instead of exiting. Nothing about the run's in-memory context is lost,
   because nothing was torn down.
3. The moment a new maintainer comment appears, it resumes **in the same
   process** — no re-dispatch, no `run-agent.sh` re-invocation, no manual
   step at all beyond the maintainer actually replying.
4. Notification is still just GitHub's own system, unchanged from before —
   a comment from a role-scoped bot on a thread the maintainer is watching
   reaches him however GitHub already reaches him (mobile push, email).
   Answering is still just replying in that thread, exactly like reviewing
   any bot comment today.

**Three layers, not one mechanism — this matters for what actually gets
built vs. what's already there:**

| Layer | What it does | How | New work? |
|---|---|---|---|
| Waiting | Blocking on CI, or on a maintainer reply | Plain shell — `gh pr checks --watch` already exists; the maintainer-reply case needs a new `scripts/wait-for-reply.sh <issue-or-pr> <since>`, a bash poll loop returning on new content, same shape as `backlog-digest.sh` | One small script |
| Judgment | Diagnosis, fix, reading review findings | Ordinary `claude -p "/implement-issue <n>"` / `/advance-pr <n>` invocations — the same slash commands used interactively today. Doesn't need one unbroken multi-hour session: Step 0's resume-check already exists so a fresh invocation can re-derive state from git/GitHub instead of conversation history | None — reuses Step 0 as designed |
| Model routing | Which backend answers a given `claude` call | `claude-code-router` as a transparent proxy (`ANTHROPIC_BASE_URL` → router) underneath every invocation in the layer above; the skills and the orchestrating script stay unaware of it | Phase 2, layered under this without changing Phase 1's loop logic |

`run-agent.sh`'s loop is therefore plain shell orchestration: run the skill
forward, drop into `wait-for-reply.sh` at a real gate, resume with a fresh
`claude` call the moment it returns, repeat until the skill's own terminal
condition is reached. Nothing about it is Claude-specific except the one
layer that's supposed to be.

This removes the earlier design's "who re-dispatches, and how" open
question entirely — there's no dispatch to repeat, just a process that was
always still running. What it costs instead is container lifetime: a
container can now sit alive, mostly idle, for as long as an issue takes
end-to-end (hours, across slow CI or several review rounds) — the same
resource shape `claude --bg` sessions already have today, so not a new
cost, just one now paid inside a container instead of on the host directly.
While that container is alive, `podman exec -it <container> claude
--resume` is always available too, for digging in live from the laptop
instead of waiting on the poll loop.

#### The general rule: private-copy-by-default, shared-only-if-safe

`.git` wasn't the only shared-write hazard — the same pattern (concurrent
containers writing into one mutable path with no lock discipline designed
for this many writers) shows up in a few more places, and the fix is the
same principle each time: give every container its own private copy of
anything it might write, and only ever mount something read-write across
containers if it's genuinely safe for concurrent writers (content-addressed,
append-only, or effectively single-writer).

- **`.claude/` inside the repo** (`settings.json`, `agents/*.md`,
  `skills/*`, `hooks/*`) needs no special handling — it comes along inside
  each private clone automatically, so every container already has its own
  copy with no shared mount at all.
- **`.claude/agent-memory/`** is git-tracked (confirmed —
  `product-owner/MEMORY.md` and the board-state notes are committed files,
  not gitignored; the one commit that's touched that path so far,
  `080baf8`/#656, landed through a normal PR). So memory writes are real
  commits, not a live shared file — but that surfaces a real gap if
  `product-owner` gets the same *ephemeral, one-clone-per-dispatch*
  treatment as implementer agents: a fresh clone per pass would mean a
  memory edit is trapped in a throwaway clone unless it's pushed and merged
  before the container tears down, which is strictly slower than today's
  "edit the file in the main checkout, done" immediacy — a genuine
  regression, not just a rephrasing of something already true. The fix is
  a different lifecycle for this one role: **`product-owner` runs as one
  long-lived, continuously-looping container** — not dispatched per pass at
  all, the containerized equivalent of the Rhythm surface's existing
  `/loop /backlog` pattern (`git pull`, one pass, sleep, repeat, forever,
  same clone throughout), rather than a fresh clone spun up and torn down
  per invocation. That makes an in-session memory edit visible to the very
  next pass exactly as it is today (same clone, same file, no teardown
  between passes at all), while durability for *other* containers still
  flows through the normal push→PR→merge path #656 already demonstrates.
  Side benefit: it removes Rhythm's current requirement of an open terminal
  actually running `/loop` — the container can be started once (e.g. on
  login) and keep looping unattended in the background. It does **not**
  remove the underlying constraint that Rhythm work only happens while the
  laptop itself is on — that's a v1, laptop-only-execution limitation, not
  a container one. The constraint the lifecycle change doesn't remove:
  only `product-owner` has
  `memory: project`, and there should only ever be one live `product-owner`
  container at a time — the fleet manifest enforces that as a singleton-role
  rule, same as it tracks everything else.
- **`~/.claude/jobs`** is different in kind from the other two — it's a
  *global*, host-level directory (not per-repo), where Claude Code tracks
  every running session for `claude agents --json`. It's also already a
  known sharp edge: `implement-issue`'s own Red Flags note that a
  **sandboxed** listing under-reports because this path is sandbox-denied
  (17 real sessions read as 1). Don't fight that by bind-mounting it
  read-write into every container and hoping Claude Code's internal,
  undocumented format tolerates N-way concurrent writers gracefully —
  instead, don't mount it into containers at all. The fleet manifest (from
  the clone-vs-worktree section above) becomes the one source of truth for
  "what's running," for both host and containerized agents; `~/.claude/jobs`
  stays host-only bookkeeping for sessions actually run on the host.
- **Dependency trees (`.venv`, `node_modules`)** are the subtle one, because
  they look read-only in the common case but aren't: `implement-issue`'s own
  allowlist includes `Bash(.venv/bin/pip install *)`, and two containers
  installing concurrently into one shared venv is a real corruption path,
  not a hypothetical. Mount them **read-only** by default — the common case
  (no new dependency) needs no write access at all. A container whose task
  actually changes `requirements.txt`/`package.json` installs into its own
  private copy inside its own container instead of the shared mount; that
  container pays a slower install, nobody else is affected. Caches that
  *are* safe to share read-write are the ones that are genuinely
  content-addressed — npm's and pip's package caches (not the venv/
  node_modules trees themselves) qualify, so those two can stay mounted
  read-write as `worktree-setup.sh` already treats them today.

#### Startup latency and whether to pre-warm

For comparison: Stripe's own writeup on their "minions" describes their
sandboxes as pre-warmed VM-based devboxes, "identical to those used by human
engineers," that spin up in about 10 seconds with code and services
pre-loaded, isolated from the internet and from production — pre-warming
exists there specifically to hide VM boot latency at their scale (many
minions dispatched in parallel, reportedly 1,000+ PRs/week).

A Podman container is lighter than a VM, so the comparable number here
should be *better* than 10 seconds — conditional on one thing: dependencies
must be **mounted, not reinstalled**. This repo's own numbers make the
stakes concrete — `worktree-setup.sh` exists precisely because a cold
`pip install` + `npm install` + Playwright browser fetch costs ~35 minutes
against ~5 minutes of actual testing. If Phase 1 containers reinstall from
scratch, sandboxed startup would cost the same ~35 minutes, every dispatch.
If instead the container bind-mounts the same shared `.venv`, `node_modules`,
pip/npm caches, and Playwright browser cache that `worktree-setup.sh`
already sets up for worktrees on the host, there's nothing left to install —
startup is just container-process start plus a health check, realistically
low single digits of seconds (once `podman machine` itself is already
running; that VM's own boot is a once-a-day cost, not a per-dispatch one,
and is already in the settings.json allowlist).

Given that, **a pre-warmed pool of ready containers is not needed for v1.**
Stripe warms a pool because their unit is a VM and their concurrency is in
the hundreds; here the unit is a container with mounted (not installed)
dependencies, at laptop/interactive scale — a handful of concurrent agents,
not hundreds. The complexity a warm pool adds (idle containers to
health-check, guaranteeing no state leaks between an agent that reuses a
pooled container and the one before it, memory/CPU sitting idle) buys back
a few seconds that mounting caches already mostly removes. Revisit only if
measured dispatch latency actually becomes friction — the same bar this
repo already applies elsewhere (see the backlogger design's "revisit only
if wall-clock actually hurts").

### Phase 2 — Model routing

Run `claude-code-router` locally as a proxy. Configuration:

- `product-owner` and `bess-analyst` pinned to Claude via
  `<CCR-SUBAGENT-MODEL>` in their prompt frontmatter — planning and diagnosis
  quality is where Claude's judgment earns its cost.
- `implement-issue`'s routine implementation steps (Step 5 TDD grind, Step 6
  mechanical fix-and-rerun cycles) routed to DeepSeek via the router's
  `default`/`background` rules.
- `think` scenario (root-cause diagnosis, scope assessment / Step 3 confirm
  gate) stays on Claude regardless of which subagent is running it — this is
  exactly the case the router's `think` rule exists for.

No changes to any `SKILL.md` or `.md` agent file content, beyond adding the
router-model tag where a subagent should be pinned. Fully reversible: point
`claude` back at Anthropic directly to undo. The container's network policy
for reaching the router (`host.docker.internal`, one shared instance) was
already decided under Phase 1, since it's a container-image concern that
had to be settled before Phase 1 could ship, even though the router itself
is built here.

**Exit criteria:** a full `implement-issue` run completes end-to-end with
implementation steps on DeepSeek and planning/diagnosis on Claude, at
materially lower cost than an all-Claude run, with no regression in the
Step 6/Step 11 review-round count (i.e. DeepSeek's output isn't generating
more rework than it saves).

### Phase 3 — The fleet dashboard, tailored

Built in-house, deliberately — not adopted from a third party. Two
different projects in this exact niche (Vibe Kanban, Crystal) have gone
from actively-developed open source to shut-down-or-commercial within the
same several months this design has been drafted; the fleet manifest and
the signals below are small enough to own outright, which is now the
stronger argument for building this rather than just the cheaper one.

A small custom dashboard reading the same signals `backlog-digest.sh`
already computes (`gh pr list`, `git worktree list`, `claude agents
--json`, `gh run list`/`gh run view`) plus Phase 1's fleet manifest and
container state (`podman ps` per agent). Per-agent: issue/PR, model in use
(from the router's
per-request log), state in the fleet's own vocabulary (Working / Needs
input / In review / Escalated — reusing the terms `implement-issue` and
`advance-pr` already use), and a link to the worktree/logs.

Deliberately a **second** board, not a merge into the GitHub Projects
backlog board — that board answers "what's ready and in what order" and is
the `product-owner` agent's, this one answers "what's running right now"
and has no product-priority meaning. Coupling them would make fleet plumbing
(container IDs, model names) leak into the product backlog.

**Exit criteria:** maintainer can answer "what's every agent doing right
now, on what model, and does anything need me" from one screen.

## Sequencing & reversibility

Each phase is a separate PR/branch, and each is independently valuable:

```
Phase 1 (sandboxing)  →  Phase 2 (routing)  →  Phase 3 (dashboard)
```

Phase 0 is dropped (see above — the tool it existed to trial is no longer a
safe bet to build even a throwaway trial on). Phase 1 and Phase 2 do not
depend on each other technically and could run in either order — but Phase
1 is listed first deliberately, because sandboxing is the actual problem
this design exists to solve; routing is a cost optimization on top of a
harness that already works. Phase 3 benefits from, but does not strictly
require, Phase 1's container state — it could in principle be built first,
reading only `backlog-digest.sh`'s existing signals, but there's less reason
to now that no trial phase is gating it.

## Later, explicitly out of scope for this design

- Moving the Phase 1 container recipe to the headless Linux box, for real
  parallelism without tying up the laptop.
- Replacing GitHub Actions for the autonomous track with the same
  container+router stack, with n8n picking up webhook glue.
- Cloud sandboxes, if laptop-local parallelism becomes the actual bottleneck
  rather than a hypothetical one.

## Open questions

- **A trusted-user autonomy tier for `product-owner`, flagged 2026-08-20,
  not designed.** For a simple issue from a known/trusted reporter, the
  maintainer wants the PO able to go all the way: analyze, assign to an
  implementer, approve the resulting PR, and schedule a beta release —
  with no maintainer step in between. This is a real, deliberate exception
  to `implement-issue`'s Step 12 hard constraint ("never merge, the
  maintainer is the final judgment") and to the backlogger design's
  "launching an implementation session needs explicit go-ahead" v1 limit —
  not an oversight to reconcile away. It needs its own explicit bar before
  it's built, the same way Definition of Ready and the ranking policy are
  explicit rather than left to judgment call: what makes an issue "simple"
  (bug-fix-shaped? touches one file? no DP/intent/control-mapping code per
  the Step 5 table?), and what makes a reporter "known/trusted" (a named
  allowlist? prior issues merged clean?). Non-trivial bugs and feature
  requests explicitly keep the maintainer in the loop — only this one
  narrow tier changes.
- DeepSeek output quality on this codebase's specific rules (`docs/agents/rules.md`
  — no `Optional[x]`, no silent fallbacks, the workaround-check, the
  plan-faithfulness test shape) is unverified. Phase 1's exit criteria
  includes checking this empirically rather than assuming parity with
  Claude.
- Whether `code-review` (the plugin invoked in Step 6) needs its own model
  pin or inherits whatever routes to it by default — not yet decided.
