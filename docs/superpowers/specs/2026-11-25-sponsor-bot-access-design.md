# Sponsor self-serve `@claude-bot` — design

Status: draft for maintainer approval · 2026-11-25

## Intent

Let GitHub Sponsors of `johanzander` trigger the agent pipeline themselves on
**their own** issues: `@claude-bot analyze` (diagnosis) and `@claude-bot fix`
(draft PR for a small bug fix). The purpose is to **attract new sponsors**
(there are currently 0 active sponsorships) by offering a visible,
generous perk — not to reward an existing base.

Today both commands are owner-only (`analyze` also accepts
`bess-product-owner`). Each run is paid from the maintainer's API account,
and the agent runs with `--permission-mode bypassPermissions` while holding a
token that can write to GitHub. Opening the trigger to paying strangers
therefore raises two problems this design exists to solve:

1. **Cost** — a sponsor must not be able to spend more than a bounded amount.
2. **Safety** — issue text written by a sponsor becomes input to an agent;
   prompt injection must not be able to escalate into writes, secret
   exfiltration, or policy changes.

## Goals

- A sponsor can run `analyze` and `fix` on issues **they opened**, without the
  maintainer doing anything per run (no approval label — that would defeat the
  purpose).
- Spend per sponsor is bounded by a credit allowance tied to their tier.
- Total sponsor spend per month is bounded by a maintainer-controlled ceiling.
- No AI process that reads sponsor-controlled text ever holds a GitHub write
  token, a push token, or network access alongside a secret.
- "Bug fix, low risk, non-structural" is enforced by **deterministic checks**,
  not by an AI's reading of the issue.
- Non-sponsors who try the command learn it is a sponsor perk, with a link.

## Non-goals

- Changing the owner / `bess-product-owner` flows (Stages 2–5 as they are).
  Hardening them with the same two-job split is a sensible follow-up but not
  part of this work.
- Sponsor commands on PRs, or on issues opened by someone else.
- Feature requests, refactors, or anything structural via sponsor `fix`.
- Sponsors merging, marking ready, or triggering Stage 4 by hand. The merge
  stays the maintainer's, always.
- Sponsor access to `integrate` (Stage 5).

## Anti-goals (would be a failure even if it "works")

- A sponsor-triggered run modifies policy or agent-instruction files:
  `.github/**`, `.claude/**` (skills, agents, settings, hooks), `CLAUDE.md`,
  `docs/agents/**`, `scripts/gh-agent.sh`.
- Any secret (Anthropic key/OAuth token, app private key, maintainer PAT) is
  readable by a process that also executes agent-written code or sponsor-
  controlled scripts.
- A sponsor can refund their own credits (e.g. by deleting a comment).
- The maintainer pays more than the monthly ceiling, whatever sponsors do.

## Constraints

- GitHub Sponsors tiers (live, 2026-11-25): monthly $2 / $5 / $10; one-time
  $10 / $25 / $50 / $100.
- `GITHUB_TOKEN` cannot read the maintainer's sponsor list. That needs a
  token belonging to `johanzander` with `read:user` scope (classic PAT; verify
  whether a fine-grained PAT can read `sponsorshipsAsMaintainer` with tiers).
- Repo is public: workflows triggered by `issue_comment` run the default
  branch's workflow file with secrets available — the gate must run before any
  secret-holding step.
- Existing project rules: never name an unregistered account in a gate;
  PRs open as drafts; automation writes use role identities (`bess-developer`
  for fix PRs, `bess-reviewer` for review).

## Approaches considered

| Approach | Trade-off | Outcome |
|---|---|---|
| Maintainer approval label per sponsor fix | Safest, but the maintainer is back in the loop per run — defeats the perk | Rejected by maintainer |
| AI classifies "bug / low risk" from the issue, then fixes | Fully self-serve, but the classifier reads attacker-controlled text and can be talked into anything | Rejected as the gate; kept only as a soft pre-filter |
| **Deterministic gates + isolated reviewer + no-token agent** (chosen) | Self-serve; the binding checks are rules or an AI that never sees the issue; worst case is a draft PR the maintainer closes, paid from the sponsor's credits | **Chosen** |

## Design

### 1. Sponsor gate (first step of every sponsor workflow, no AI)

On an `issue_comment` containing `@claude-bot analyze` or `@claude-bot fix`
from someone who is **not** the owner or `bess-product-owner`:

1. If the workflow kill switch `vars.SPONSOR_BOT_ENABLED != 'true'` → stop silently.
2. Comment must be on an **issue** (not a PR) whose author == commenter.
   Otherwise reply (once per issue) that sponsor commands work on your own
   issues only.
3. Look up the commenter in `sponsorshipsAsMaintainer` (active monthly +
   one-time within the last 12 months) using the maintainer PAT secret
   (`SPONSORS_READ_TOKEN`). Not a sponsor → reply **once per issue**:
   "`@claude-bot` commands are a sponsor perk — [Sponsor on GitHub](https://github.com/sponsors/johanzander)."
4. Issue must carry a debug log (same definition triage uses: in the body or a
   comment, linked gist counts). Otherwise reply that a debug log is needed —
   no credit spent.
5. Compute credits (section 2). Insufficient, or global ceiling reached →
   reply with balance / "paused until next month", no run.
6. Post the **ledger comment** (section 2) *before* the run starts — the
   attempt is charged whether or not it succeeds.

The owner/`bess-product-owner` path is untouched: existing workflows keep
their current `if:`; sponsor handling lives in new, separate workflow files
(`sponsor-analyze.yml`, `sponsor-fix.yml`) whose `if:` excludes those two
accounts.

### 2. Credits

| Sponsorship | Credits |
|---|---|
| $2 / month | 3 per month |
| $5 / month | 10 per month |
| $10 / month | 25 per month |
| One-time | 2.5 per dollar ($10 → 25, $25 → 60, $50 → 125, $100 → 250), valid 12 months from the sponsorship date |

- `analyze` costs **1** credit, `fix` costs **3**.
- Monthly credits reset on the calendar month (UTC). If someone has both a
  monthly and a one-time sponsorship, spend monthly credits first.
- **Ledger:** the gate posts a bot comment on the issue in a fixed,
  machine-parseable form, e.g.
  `<!-- sponsor-ledger login=alice cmd=fix cost=3 -->` plus a human line
  ("Sponsor run: 3 credits used, 7 left this month"). Usage = sum of ledger
  comments for that login in the window, found via the search API restricted
  to the bot author. Ledger comments are authored by the bot, so an issue
  author cannot delete them (only collaborators can) — no self-refund.
- **Global ceiling:** `vars.SPONSOR_MONTHLY_CREDIT_CEILING` (maintainer's call
  to set; suggested start: 100 credits ≈ $50–100) summed across all sponsors'
  ledger comments in the calendar month.
- Generosity note: at ~$0.5–1 per analyze credit, a $10/month sponsor who
  uses all 25 credits can cost more than they pay. That is intentional
  (attraction); the global ceiling is what bounds total exposure.

### 3. Run cost bounding

Sponsor runs use Sonnet (`claude-sonnet-5-5`), a fixed `--max-turns` (builder
picks; aim for a predictable ≤ $1 analyze, ≤ $3 fix), and a job
`timeout-minutes`. They never use `bypassPermissions`; tools are an explicit
allowlist (sections 4–5).

### 4. Sponsor `analyze` — two-job split

- **Job A (agent).** `permissions: contents: read` only; no app token
  minted. Has the Anthropic credential. Tools: `Read`, `Grep`, `Glob`, `Write`
  (to one output path), and Bash restricted to the existing debug-log analysis
  scripts the `bess-analyst` uses (exact allowlist is the builder's call — must
  exclude `curl`, `gh`, `git push`, package installs, arbitrary `python -c`).
  Writes the report to a file, uploaded as an artifact. The report ends with a
  machine-readable verdict line:
  `<!-- sponsor-verdict: bug-fixable | bug-not-fixable | not-a-bug | inconclusive -->`.
- **Job B (poster, no AI).** Mints the app token, downloads the artifact,
  sanitises (strip/neutralise `@mentions` other than the issue author, cap
  size, reject if empty) and posts it as the analysis comment.

### 5. Sponsor `fix` — agent, gates, reviewer, publisher

Preconditions (checked by the gate, section 1, plus): the issue already has a
sponsor or owner analysis comment from the bot whose verdict line is
`bug-fixable`. That verdict is AI-produced from issue text, so it is only a
**soft pre-filter**; the binding checks are below.

- **Job A (agent).** Same isolation as analyze Job A: no GitHub write token,
  no network-capable tools, Sonnet, `--max-turns` bound. Tools: `Read`,
  `Grep`, `Glob`, `Edit`, `Write`. Instruction: produce a minimal bug fix
  **plus a regression test that reproduces the bug**. Output: a `git diff`
  patch file as an artifact. The agent does **not** run tests in this job
  (running agent-written code next to the Anthropic credential is exactly the
  exfiltration path we are closing). Builder may instead let it run tests
  inside `docker run --network none` with no env passed through — only if that
  container genuinely cannot see any secret.
- **Job B (deterministic gates, no AI, no secrets).**
  `permissions: contents: read`, no secrets referenced. Applies the patch to a
  fresh checkout of `main` and fails closed on any of:
  - **Path guard:** touches `.github/**`, `.claude/**`, `CLAUDE.md`,
    `docs/agents/**`, `docs/superpowers/**`, `scripts/**`, `bess_manager/config.yaml`,
    `pyproject.toml`, `requirements*.txt`, `frontend/package*.json`, the
    optimizer-core files listed in `docs/agents/optimizer-architecture.md`,
    any DB schema/migration file, `CHANGELOG.md`.
  - **Size guard:** more than N changed lines / M files (builder proposes N, M;
    suggested start: 80 lines, 4 files, tests excluded from the line count).
  - **Test-first proof:** the patch must add or modify at least one test.
    Apply **only the test changes** to `main` → those tests must **fail**;
    apply the full patch → they must **pass**.
  - **Suite:** `pytest -m "not slow"` and ruff/black on changed files pass.
- **Job C (isolated reviewer).** Sonnet, `contents: read`, no write token. Its
  prompt receives **only the diff** and a fixed rubric — never the issue title,
  body, comments, or the analysis. Question: "Is this a contained bug fix with
  a reproducing test, or a feature / behaviour change / structural change?"
  Output: `contained-fix` or `reject: <reason>` as an artifact. Because it
  never reads sponsor text, text planted in the issue cannot reach it. (Code
  comments in the diff can still carry text; the rubric must tell it to treat
  comments as data, and Job B may strip comment-only hunks.)
- **Job D (publisher, no AI).** Only if B and C pass: mint the GitHub App
  token the existing `issue-fix.yml` uses (`CLAUDE_REVIEWER_APP_*`; must not
  carry `workflows` permission), push branch
  `sponsor-fix/<issue>`, open a **draft** PR referencing the issue (no
  `Closes`), and comment on the issue. If B or C fails: comment on the issue
  with the reason ("this needs the maintainer") — credits are not refunded.

The draft PR then goes through the maintainer's normal review/merge. Sponsor
fixes are never auto-marked ready.

### 6. Messages sponsors and non-sponsors see

**Advertise up front, in the bot's existing replies — not only after a
non-sponsor tries the command.** Today Stage 1 triage (`issue-triage.yml`,
bucket `bug_with_log`) ends every reply with the fixed line
"Reply `@claude-bot analyze` to start deep code-level analysis." — which a
non-owner reporter cannot actually do (the trigger silently ignores them).
That line is the main advertisement and changes to state the perk, e.g.:

> GitHub Sponsors can reply `@claude-bot analyze` to start a deep code-level
> analysis right away, and `@claude-bot fix` for a draft fix PR —
> [become a sponsor](https://github.com/sponsors/johanzander). Otherwise the
> maintainer will pick this up.

- `bug_without_log` replies add one line: once the log is attached, sponsors
  can run the analysis themselves (same link).
- Nothing parses the old closing line (checked: no other reference in the
  repo), so changing it is safe; it stays an "End EXACTLY with" instruction so
  wording is stable.
- Stage 1 is owner-trigger-free and cheap (~$0.05), so this adds no spend.

Replies from the sponsor workflows themselves:

- Non-sponsor who tries the command anyway: sponsor-perk notice + link (once
  per issue) — a fallback, since the triage reply already told them.
- Sponsor, wrong issue / no debug log / no credits / ceiling reached: one
  short explanatory reply, no credit spent.
- Ledger line on every charged run.
- README "Sponsorship" section gains a short description of the perk and the
  credit table.

## Decided by the maintainer

- Sponsors may run `analyze` and `fix`; only on issues they opened; a debug
  log is required.
- No per-run maintainer approval.
- Fix gate = failing-test-first + path/size guard + reviewer that never sees
  the issue.
- Sponsor runs may never change policy or skill files.
- Credits: $2→3, $5→10, $10→25 per month; one-time at the $10-tier rate.
- The sponsorship is advertised up front in the bot's normal triage reply
  (where it already tells reporters to use `@claude-bot analyze`), not only
  after a non-sponsor tries the command.

## Calls made in the design (check these)

- One-time = 2.5 credits/$ valid 12 months; analyze 1, fix 3 credits.
- Failed attempts are charged; ledger is bot comments (not deletable by sponsors).
- Global ceiling and kill switch as repo variables; suggested 100 credits/month.
- Sponsor runs on Sonnet with explicit tool allowlists, never `bypassPermissions`.
- Agent does not run tests in the secret-holding job.
- New separate workflow files; owner flows untouched.

## Settled after the builder check (design calls)

1. **Input fetching and log parsing happen outside the AI job.** The gate job
   (no Anthropic secret, read-only token) fetches the issue body, comments and
   the linked debug log (gist / attachment), runs the existing debug-log
   analysis scripts over it, and uploads issue text + log + digest as an
   artifact. Agent Job A downloads that artifact and has **no Bash at all**
   (`Read`, `Grep`, `Glob`, `Write` for analyze; plus `Edit` for fix).
   Attacker-supplied data is therefore only ever parsed by code in a job with
   no secret, and the agent job has no network-capable tool. This also matches
   the project lesson that analysts work best from a pre-computed digest.
2. **Write identity** is the existing GitHub App (`CLAUDE_REVIEWER_APP_*`),
   same as `issue-fix.yml` today. The ledger search filters on that app's bot
   login. PRs pushed by an App token do trigger CI (unlike `GITHUB_TOKEN`).
3. **`claude-code-action` vs raw CLI:** if the action cannot run without a
   GitHub write token in the job, call the Claude Code CLI directly in Job A.
   Hard constraint either way: no GitHub write token present in the job.
4. **Fix precondition** requires a **sponsor-analyze** verdict line on that
   issue (from the sponsor workflow). Owner analyses don't emit the line and
   owner flows stay untouched, so a sponsor whose issue was owner-analyzed
   runs a sponsor analyze first (1 credit).
5. **Balance rules:** each one-time sponsorship is its own pool (2.5 × $),
   no monthly reset, expires 12 months after its date; multiple pools stack.
   Spend order: this month's monthly credits → oldest unexpired one-time pool.
   The global monthly ceiling counts all sponsor usage in the calendar month,
   whatever pool paid for it. Ledger comments record which pool was charged.
6. **Concurrency:** `concurrency: sponsor-${{ github.event.comment.user.login }}`
   with `cancel-in-progress: false` — a sponsor's runs serialize, so the
   balance check always sees the previous ledger comment. A run is charged
   the moment its ledger comment posts; a later failure or cancellation is
   not refunded.
7. **Scope of `fix` v1: backend (Python) bug fixes only.** The test-first proof
   is pytest-based; a patch touching `frontend/**` or `e2e/**` fails the path
   guard with "needs the maintainer". Frontend fixes (vitest-based proof) are a
   possible v2.

## Left to the builder

- Exact Bash allowlist for sponsor analyze; `--max-turns` values.
- Size-guard thresholds (starting point above).
- Exact GraphQL query and whether a fine-grained PAT suffices.
- How the test-first check isolates "test changes" from the patch
  (path convention `tests/**` is the obvious rule).
- Message wording.
