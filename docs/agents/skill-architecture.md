# Skill & Agent Architecture

How the project's AI skills, subagents, and GitHub automation fit together to add
a new integration (a price provider or an inverter platform) and drive it from
research → experimental beta → real-user validation → stable release.

Read this before working on the skills, the `@claude-bot` pipeline, or the
autonomous integration workflow. For the staged roadmap to full autonomy, see
[`docs/superpowers/specs/2026-06-15-autonomous-inverter-integration-design.md`](../superpowers/specs/2026-06-15-autonomous-inverter-integration-design.md).

## Two layers

Integration work spans two layers that meet at the lifecycle.

### 1. Skills (the "how", run by an agent in a session)

Skills live in `.claude/skills/<name>/SKILL.md`. They compose:

```
                       feature-lifecycle  (orchestrator)
                      /        |          \
       add-price-provider  add-inverter-platform   release
        (implementation)    (implementation)       (deploy: beta + prod)
```

| Skill | Role |
|-------|------|
| [`add-price-provider`](../../.claude/skills/add-price-provider/SKILL.md) | **Implementation** recipe for a new electricity-price integration. Every file, in order, with the "read the integration source, never guess `unique_id`s" rule. |
| [`add-inverter-platform`](../../.claude/skills/add-inverter-platform/SKILL.md) | **Implementation** recipe for a new inverter platform. The inverter counterpart of `add-price-provider`. Starts by placing the inverter on the two control axes (see below). |
| [`feature-lifecycle`](../../.claude/skills/feature-lifecycle/SKILL.md) | **Orchestrator.** Drives either implementation skill through the 6-stage experimental→stable lifecycle, calls `release`, communicates in the issue/PR, and polls CI between human gates. Does not re-implement the others. |
| [`release`](../../.claude/skills/release/SKILL.md) | **Deploy.** Owns beta vs prod remotes, version bump, CHANGELOG, tag, GitHub Release. |

**Composition rule:** orchestrator calls implementation + deploy; implementation
skills never deploy and never own the lifecycle. A new integration *type* adds a
new implementation skill; `feature-lifecycle` and `release` are reused as-is.

### 2. GitHub automation (the "when", event-driven, stateless CI)

Each stage is a self-contained workflow in `.github/workflows/` with an inline
prompt running on `anthropics/claude-code-action@v1`, gated on an owner
`@claude-bot <cmd>` comment.

| Workflow | Trigger | Role |
|----------|---------|------|
| `issue-triage.yml` | auto on issue open/edit | classify + label (bug / question / enhancement / needs-info) |
| `issue-analyze.yml` | `@claude-bot analyze` | deep root-cause; dispatches the **`bess-analyst`** subagent |
| `issue-fix.yml` | `@claude-bot fix` | minimal bug fix → draft PR |
| `pr-review.yml` | `@claude-bot` on a PR | review the diff against the rules |

This pipeline is built for **minimal bug fixes → one PR**. Integration work
(multi-day, human-gated) is driven by the skill layer, not these workflows.

### Subagents

| Subagent | Defined in | Role |
|----------|-----------|------|
| `bess-analyst` | [`.claude/agents/bess-analyst.md`](../../.claude/agents/bess-analyst.md) | Read-only issue analysis / debugging. Invoked by `issue-analyze.yml`. |

## The integration lifecycle (6 stages)

`feature-lifecycle` runs these. Two are **human gates** — do not fabricate logs
or confirmations.

1. **Implement + ship experimental.** Run the implementation skill end-to-end
   (incl. a source-derived regression fixture), mark the feature *experimental*,
   open a draft PR with a stage checklist in the body, ship to beta.
2. **User debug log (GATE).** The user installs the beta and exports a debug
   report; verify the integration parses against their real registry.
3. **Lock the real config into the regression suite.** The user's whole rig
   becomes a permanent regression scenario (backend discovery + frontend E2E).
4. **Re-ship, CI green.** A loop of rapid minor fixes — **batched** into one
   consolidated beta, not a release per fix. Poll CI to green.
5. **User confirms on hardware (GATE).** Never claim real-world validation before
   this.
6. **Graduate.** Strip the *experimental* marker, update the maturity record,
   run the prod `release`, close the issue.

**State machine:** the PR-body checklist is the durable state. A resumed agent
reads it to know where it is. This is what lets the multi-day, human-gated
lifecycle run on stateless CI (see the grand-plan spec for the resume-trigger
design).

## Inverter-specific: the two control axes

Inverter control is two orthogonal axes, not a flat list of patterns (see
[`docs/INVERTER_PLATFORMS.md`](../INVERTER_PLATFORMS.md) → "Inverter Integration
Patterns"):

- **Transport** — how commands reach the inverter (TX-Cloud `growatt_server`
  service calls; TX-Modbus `solax_modbus` multi-brand entity writes;
  TX-Vendor-service e.g. `huawei_solar`; future TX-REST/MQTT).
- **Scheduling model** — how a plan is expressed (numbered TOU slots; charge/
  discharge period lists; mode-specific slots; ephemeral duration-bounded
  commands).

A new inverter's (transport × scheduling-model) coordinate determines which
existing controller to model on and how much is new. The architecture
(`InverterController` ABC + per-platform suffix maps + a generic
`/api/services/{domain}/{name}` layer) absorbs new inverters **additively** — no
core refactor required.

## Where to go next

| Concern | File |
|---------|------|
| Autonomy roadmap (Stages A–D) | `docs/superpowers/specs/2026-06-15-autonomous-inverter-integration-design.md` |
| Inverter patterns + per-platform reference | `docs/INVERTER_PLATFORMS.md` |
| Hard constraints | `docs/agents/rules.md` |
| Commit / PR / release process | `docs/agents/workflow.md` |
| Maturity conventions (experimental→stable) | `docs/agents/memory/` |
