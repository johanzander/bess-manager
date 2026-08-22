# Local Agent Environment

How an agent's own machine is configured for this repo: worktree layout,
the permission rules, the OS sandbox, and the tooling failures each of those
produced. Relocated here from `CLAUDE.md` in #650 — it was 74% of a file that
every bot stage loads on every turn, and none of it applies on a CI runner.

Read this before running autonomous local work, changing `.claude/settings.json`,
or debugging a tool that fails for no visible reason. It does not apply to the
`@claude-bot` CI stages, which run on a fresh `ubuntu-latest` checkout under
`--permission-mode bypassPermissions`.

## Worktree Conventions

Both layouts are first-class — either way the worktree is a normal git checkout,
so per-agent inspect / test / run (`./deploy.sh`, `pytest`, the app) works the
same. Choose by how you want to reach an agent's work:

- **Sibling folders** (e.g. `../bess-manager-feature/`) — open cleanly in their
  own VS Code window; this is the go-to when you actively inspect code and run
  scripts per agent. They work with Agent View too: start the background session
  *inside* the sibling (it's a linked git worktree, so Claude won't relocate it).
  Caveat: a sibling only appears in **unscoped** `claude agents` (or
  `--cwd ~/GitHub`), not in the project-scoped `claude agents --cwd <repo>` view.
- **Native `.claude/worktrees/`** (`claude agents` / `--worktree` /
  `EnterWorktree`) — auto-created for background sessions and visible in the
  **project-scoped** Agent View. Still a real checkout: `code
  <repo>/.claude/worktrees/<name>` or `cd` into it to run tests/scripts.

Find any session's worktree path by peeking/attaching it in Agent View, or via
`claude agents --json` (the `cwd` field).

**Run `./scripts/worktree-setup.sh` once in every new worktree, before any
test/build/verify step.** A fresh worktree has no `.venv` and no
`node_modules`, and reinstalling them costs ~35 minutes against ~5 minutes of
actual testing. The script shares all three dependency trees with the main
checkout (falling back to a real `npm install` only for a package root whose
lockfile actually diverged) and repairs a Playwright browser cache left
unusable by an interrupted install.

Those shared trees are symlinks, so they are read-shared but **not**
write-isolated: `npm install` or `pip install` inside a worktree writes through
the link and changes dependencies for the main checkout and every other
worktree at once. Running tests and builds is safe; when a branch needs its own
dependency set, replace the symlink with a real install (`rm .venv` / `rm
frontend/node_modules` first) rather than installing through it. Re-running
`worktree-setup.sh` handles the node case automatically once
`package-lock.json` diverges — `requirements.txt` drift is not detected.

### Permissions

**An agent should run end-to-end without approving anything that the sandbox
already contains.** Prompts are the cost, not the safety: a stalled autonomous
run is a guaranteed loss, while anything the sandbox bounds is recoverable.
`rm`, `git reset --hard`, `rebase`, `merge`, `git branch -D` all run
unattended. **`git worktree remove`/`prune` are the one exception to that
list** — the sandbox does not make them safe, it makes them destructively
unsafe (see "What stays denied" below): they delete the working tree before
failing on the denied `.git/worktrees/<name>` unlink. **`git push` also runs
unattended, in every spelling including `--force`** — not because pushing is
safe, but because the refs worth protecting are protected on GitHub itself. See
"Pushing is guarded server-side" below.

What still asks is one closed list, and every entry is there because the
**sandbox cannot contain it** — it bounds the filesystem, not the network, and
not `.git`'s own recovery data:

| Category | Rules |
|---|---|
| Escapes to GitHub | **every `gh api` WRITE** (see below), `gh pr merge`, `gh release create` / `edit` / `delete` / `delete-asset` / `upload`, `gh repo edit`, `gh secret`, `gh workflow run` |
| Destroys the recovery mechanism | `git gc`, `git prune`, `git repack`, `git maintenance`, `git reflog expire`, `git reflog delete`, `git update-ref`, `git tag -d` / `--delete` / `-f` |
| Leaves the user boundary | `sudo` |

Each of those also has a `git -* <verb>` twin covering the global-option
spelling (`git -C <path> gc`, `git -C sub tag -d`). The twins name a **verb**
on purpose: a blanket `Bash(git -*)` was tried and put read-only inspection —
`git -C sub status`, `git -C <wt> diff`, the verify step of the cross-checkout
patch recipe — behind a prompt, and it shadowed the `git commit` allow via
`git -c user.email=… commit`.

**`*` compiles to a greedy `.*` that spans spaces**, which bounds how precise
any of this can be. `git -* tag -d*` therefore also matches a `git -c … commit`
whose *message* contains " tag -d". That is an extra prompt, not a gap, and it
is accepted — the alternative is dropping the global-option guard on tag
deletion, which is a real bypass. When the choice is between a false prompt and
a hole, take the prompt. The one case where that trade flips is `deny`, which has no
override: an over-broad deny **blocks** documented work rather than prompting
for it, which is why `git prune` has no twin (it caught `git worktree prune`,
which the Step 4 loop used to run) and why the stash twins are per-verb.

Denied outright: the shared podman VM (`machine rm`, `system reset`) and every
mutating `git stash` form, **including `git -C <path> stash …`**. That last
clause is load-bearing rather than decorative: the global-option spelling was
briefly covered only by an `ask`, and since `deny > ask` applies by category, a
matching `ask` with no matching `deny` turns a prohibition into a prompt. The
gate checks stash and podman shapes against `deny` **only** for that reason.

The standard for adding an entry: **the effect escapes the repo and git cannot
undo it.** Not "the command looks dangerous". Both halves have to hold, which
is why **`gh pr ready` is deliberately unattended** even though it plainly
escapes to GitHub: `gh pr ready --undo` puts the PR straight back, it changes
no content (the diff was already public, pushed by Step 9), and it is the
codified endpoint of `implement-issue` Step 11's
review loop. Prompting there would stall the one flow whose entire point is to
reach that state without you. Contrast `gh pr merge` one row up, which is the
same category and *is* gated: nothing undoes a merge to `main`.

**`gh release` names its verbs for the same reason.** The standard is "the
effect escapes the repo *and* git cannot undo it" — `gh release list` and `gh
release view` fail the first half outright, since reading changes nothing on
GitHub. A blanket `gh release*` therefore prompted on the exact command the
release rule above *requires* ("always check the current published version
before tagging"), and on every beta/stable version comparison. `create`,
`edit`, `delete`, `delete-asset` and `upload` still ask; `list`, `view` and
`download` run unattended, and `quality-check.sh` pins both halves so the
split cannot collapse back into either a blanket rule or a hole.

The second category exists
because leaving `rm` and `reset --hard` unattended is only defensible while the
object database and reflog can recover them — a `gc --prune=now` that ran
unprompted would remove the ground that argument stands on.

**`gh api` asks on WRITES only, and the write flags are enumerated.** Reads
run unattended — `gh api <path>` and `gh api <path> --jq ...` are how a session
reads inline review comments, which no `gh pr view` field returns.

It was blanket-guarded first (`Bash(gh api)` / `Bash(gh api *)` in `ask`),
because the marker that makes a call a write sits at an arbitrary argument
position and **prefix globbing cannot reach it**:

```
gh api repos/o/r/pulls/N/merge -X PUT # merges, bypassing `gh pr merge`
gh api <path> -f key=val              # any -f/-F makes it a POST
```

The blanket cost a prompt on every read, so #657 replaced it with one rule per
write flag in each argument position. That trade is the standing one, and it
has a standing risk: **a write flag nobody enumerated resolves to `allow`.**
Not hypothetical — `-F, --field` and `-f, --raw-field` (`gh api --help`) had
only their short forms listed, so `gh api <path> --field k=v` was a GitHub
write that never prompted, until it was pinned.

So `quality-check.sh` no longer asserts the *spelling*. It used to require the
literal blanket rules, which made it fail on a clean `main` the moment #657
respelled them, while the property it cared about still held. It now asserts
the *property*, by command string, in `MUST_BE_GUARDED` — those pins survive a
respelling.

**When you add a `gh api` write flag, add its command string to
`MUST_BE_GUARDED` too**, in both argument positions **and both the
`--flag value` and `--flag=value` spellings**. That list is the guard; the
rules in `settings.json` are just how it is currently satisfied.

### Pushing is guarded server-side, not by a prompt

`git push` used to be in that same paragraph, blanket-guarded against four
spellings that a prefix glob could not reach:

```
git push origin main --force          # --force not adjacent to `push`
git push origin +beta-release-9.9     # force via refspec
git push origin --delete release-X.Y  # destroys a shared ref
git push origin v9.9.0                # moves a published release tag
```

The glob was never what made those safe — it was a blunt instrument
compensating for having no guard at the only layer that can see a *ref update*
rather than a command string. That layer now exists. Five **GitHub rulesets**,
all `enforcement=active` with an **empty `bypass_actors` list**. They refuse
every *rewrite* above; the one thing they still permit is deleting a spent
`release-*` branch, which is explained under the table:

| Repo | Ruleset | Applies to | Rules |
|---|---|---|---|
| `bess-manager` | Protect Main Branch | `~DEFAULT_BRANCH` | deletion, non_fast_forward, pull_request |
| `bess-manager` | Protect beta release branches | `beta-release-*` | deletion, non_fast_forward |
| `bess-manager` | Protect release tags | `~ALL` tags | deletion, non_fast_forward |
| `bess-manager` | Protect stable hotfix branches | `release-*` | non_fast_forward |
| `bess-manager-beta` | Protect beta main (fast-forward only) | `~DEFAULT_BRANCH` | deletion, non_fast_forward |

**`release-*` carries `non_fast_forward` and deliberately NOT `deletion`**,
which is the one asymmetry in the table and the one line of the four above that
is still permitted. It is the short-lived stable hotfix branch the `release`
skill creates (steps 2–6): it is pushed and tagged, so *rewriting* it must
fail, while deleting it once the release is out is ordinary cleanup and must
not. What makes dropping the deletion guard safe is the tag ruleset one row up
— the published tag pins the released commit, so a deleted `release-*` branch
costs nothing after tagging. Before tagging it is still recoverable only from
a local reflog, so delete it after, not during.

The empty bypass list is the load-bearing part: **local pushes authenticate as
the repo owner**, not as `bess-agent` (the credential helper is osxkeychain and
`gh auth status` reports `johanzander`). A ruleset that exempted admins would
therefore exempt every push this machine makes and protect nothing.

Read the current state before trusting this table — it is a snapshot of remote
config, not of anything in this repo:

```bash
gh api repos/johanzander/bess-manager/rulesets
gh api repos/johanzander/bess-manager-beta/rulesets
```

**Two consequences to know about.**

*Tag creation is still allowed*, only deletion and force-update are blocked —
otherwise `release` could not tag at all. The flip side: removing a tag pushed
by mistake now requires editing the ruleset, deliberately, as the owner. That
is the intended trade.

*The pending beta GHCR migration force-pushes `main` to `beta/main`*, which
`Protect beta main` now refuses. That is a one-time deliberate operation:
set that ruleset to `enforcement: "disabled"`, push, set it back to `"active"`.
Do not add a bypass actor for it — a standing exemption for the identity that
does every push is the same hole as having no rule.

**What this deliberately leaves open:** force-pushing or deleting a *feature*
branch (`fix/**`, `feat/**`) on origin, so ordinary work needs no prompt.

**Do not describe that residual as "bounded to your own unmerged branch."** It
was written that way first and the reasoning does not survive this repo's own
conventions: ~20 worktrees run in parallel, each with its own pushed branch and
open PR, and every one of them authenticates as the same owner. An unattended
`--force` or `--delete` aimed at the wrong ref destroys *another agent's*
pushed commits and closes its PR, and the local reflog that would recover it
lives in a different worktree. The bound is "one feature branch", not "one
agent's own work".

Accepted anyway, because the alternative — a `fix/**` + `feat/**`
`non_fast_forward` ruleset — also blocks the legitimate rebase-and-force-push
on your own branch, and this project's merge-based flow means a force push
appearing at all is the finding (see below). Know which trade is being made.

**Do not re-add a `Bash(git push*)` ask because pushing "looks unguarded".**
`quality-check.sh` pins the new direction: the push spellings live in
`MUST_NOT_BE_GUARDED`, so restoring the prompt fails the gate. Check the
rulesets first.

**Patterns match the command as written — prefix globbing, no normalisation.**
This is the single biggest source of rules that look right and match nothing,
and it produced a bug here in four consecutive review rounds.

**Nothing normalises `git`'s global options**, so `git -C <path> stash pop`,
`git --git-dir=… tag -d v1` and `git --no-pager gc` sidestep every
rule anchored on `git stash` / `git tag -d` / `git gc`. The deleted hook
normalised for exactly this — and this document itself teaches `git -C
.claude/worktrees/<name>` as the cross-checkout idiom, so it is the spelling an
agent reaches for first. `Bash(git -*)` covers the whole class in one rule,
including options nobody has thought of yet. Do not replace it with an
enumeration.

**`scripts/quality-check.sh` asserts this by COMMAND STRING, not by rule name.**
Presence checks — "is rule X in the list" — passed for four review rounds while
real spellings slipped through, because they answer the wrong question. The gate
now carries ~56 real command strings in three lists, using the same prefix-glob
semantics the harness applies:

- `MUST_BE_DENIED` — checked against `deny` **only**, so a matching `ask` cannot
  certify a command that policy says is unapprovable.
- `MUST_BE_GUARDED` — checked against `deny` + `ask`; a prompt is acceptable.
- `MUST_NOT_BE_GUARDED` — commands that must stay unattended: read-only git,
  and every `git push` spelling now that enforcement is server-side. This is
  what catches a rule that is too *broad*, the failure the blanket
  `Bash(git -*)` introduced — and, for push, a rule reinstated out of caution
  after the ruleset made it redundant.

When a new bypass spelling turns up, add the string to the right list first —
then fix the rule until the gate goes green.

**A rule that fails to match does not fall through to the `auto` classifier.**
It falls through to whatever `allow` rule covers the command — here `Bash(git
*)` in user settings — and runs unattended. That is exactly what `git push`
does now, by design. Precedence is `deny > ask > allow` **by category**, not by
specificity, so a broad `allow` is only ever overridden by an `ask` that
actually matches. That is why a too-narrow `ask` is worse than no rule: it
reads as covered while changing nothing.

**`defaultMode` is `auto`, and it is what makes the list above short enough to
work.** The `allow` list cannot enumerate what an issue actually needs — a
single `implement-issue` run reaches for compose, npm, python3, mkdir, cp and
a dozen one-off shapes nobody predicted — so under the plain `default` mode
everything unlisted prompts and the run stalls dozens of times. `auto` sends
those to a classifier instead, which decides without involving you; `deny` and
`ask` still bind on top of it. This lives in the **tracked** settings on
purpose: `defaultMode` is not a Bash rule, so it travels into every worktree by
itself. Putting it in the gitignored `settings.local.json` is what made an
autonomous run in the main checkout start prompting the moment it entered a
worktree, and what the deleted symlink hook existed to paper over.

The two `Bash` permission hooks that used to shape this are gone:
`auto-allow-worktree-destructive.sh` (a cwd-conditional auto-allow) and
`link-worktree-local-settings.sh` (a SessionStart symlink undoing the asymmetry
the first one created). They existed to express what settings.json could not,
and cost six false positives in a single day, *every one introduced by the fix
to the previous one*, including blocking a live beta release. With nothing left
to auto-allow around, the plain rules say it directly. Do not reintroduce a hook
to route around a prompt — delete the `ask` entry instead, and remember `deny`
beats `ask` beats `allow`, so adding an `allow` never cancels an `ask`.

`check-worktree-path.sh` stays. It guards Edit/Write, not Bash, and it is the
one thing here that has never produced a false positive: it compares two `git
rev-parse` results as strings and refuses an edit aimed at a different checkout
than the session's cwd. That is the failure this repo actually hits — a stale
absolute path from an earlier turn writing into the main checkout while ~20
worktrees are live — and unlike the Bash guards it never has to parse a command.
Anything added here must be that shape: compare resolved paths, never guess at
what a command string will touch.

**Never `git stash` — it is denied, everywhere in this repo.** There is exactly
one `refs/stash` per repository, shared by the main checkout and every worktree,
and the stack has no owner: one agent's `git stash` pushes an entry that another
agent's `git stash pop` will take, with no way to tell it was not theirs. With
~20 worktrees active that silently destroys work, and once popped and discarded
git offers no recovery. `permissions.deny` lists every mutating form (bare `git
stash`, `push`, `save`, `pop`, `apply`, `drop`, `clear`, `branch`, `create`,
`store`), **each with a `git -* stash <verb>` twin**, so the global-option
spelling `git -C <dir> stash pop` is denied too — that is the form the
cross-checkout recipe below would otherwise reach for, and it was a live
bypass until #596.

`git stash list` and `git stash show` still work, in both spellings. The twins
name a verb for exactly that reason: a blanket `git -* stash *` deny also
caught `git -C sub stash list`, and `deny` has no override, so it hard-blocked
inspection rather than merely prompting for it. `scripts/quality-check.sh` pins
both directions — the mutating forms must match a **deny**, the read-only forms
must match **nothing**.

**The OS sandbox is what makes the unattended list safe, and it is on.**
`sandbox.enabled` confines every Bash write to the repository, decided by the OS
from the actual syscall rather than guessed from a command string. That is why
`rm -rf` needs no prompt: outside the repo it cannot create *or* unlink — the
macOS profile denies `file-write-create` and `file-write-unlink` in one rule.
**`git worktree remove`/`prune` are the one destructive exception**: their
denied write is the `.git/worktrees/<name>` unlink, which comes *after* the
working tree is already gone, so the sandbox does not bound their damage — it
causes it. The bullets below are the measured record; never call either verb
from sandboxed Bash.

**`allowWrite` must name the repo root, and that is the whole trick.** Writes
are `allowOnly` minus `denyWithinAllow`, and the built-in `allowOnly` is only
`/dev/*`, `/tmp/claude`, `~/.npm/_logs` and `~/.claude/debug` — **the repository
is not in it**. So `allowWrite: ["."]` is what opens the repo at all. An earlier
attempt set `allowWrite: [".claude", ".git", "scripts"]`, three paths that are
all on the deny list, never opened the repo root, and concluded from the
resulting breakage that the sandbox was unusable. It isn't; that config was.

**What stays denied cannot be re-opened.** There is no allow-within-deny
primitive for writes (reads have one, which is why `allowRead` differs), so no
`allowWrite` entry overrides the built-in `denyWrite` list. Confirmed by
`verify-sandbox.sh`:

- **Create worktrees with `EnterWorktree`, never `git worktree add` from Bash** —
  the harness is not sandboxed; the Bash form writes `.git/config` and
  `.git/worktrees`, both denied. *(measured)*
- **`git worktree remove` is denied too, and unlike `add` it fails
  DESTRUCTIVELY.** Removal deletes the working tree *first*, then unlinks
  `.git/worktrees/<name>` — and that unlink is the denied one:

  ```
  error: failed to delete '.../.claude/worktrees/backlogger': Operation not permitted
  error: failed to delete '.git/worktrees/backlogger': Operation not permitted
  ```

  By then it has already deleted several hundred tracked files. It does not
  roll back. What is left is a **carcass**: a registered worktree whose
  `git status` is a few hundred ` D` lines and nothing else. That reads as
  "uncommitted changes" to every later prune, so the worktree is now
  permanently unprunable *by the failure itself* — re-running the removal
  hits the no-`--force` refusal instead, and `--force` re-hits the denial.

  Because the filename set is identical in every worktree, so is APFS's
  readdir order, so every carcass loses the **same** ~393 paths (`core/`,
  `frontend/`, `bess_manager/`, `pyproject.toml`, `Dockerfile`, …). Identical
  damage across many worktrees is the signature — do not read it as a
  coincidence or as real edits. *(measured — 13 carcasses accumulated over
  three sweeps before anyone noticed)*

  The denial is precisely on the `.git/worktrees/<name>` unlink, **not** on the
  working tree: `rm -rf .claude/worktrees/<name>` from Bash succeeds. So an
  agent can always destroy the files and never the registration. Do not
  half-do it — that converts a carcass into a `prunable` phantom, which still
  needs the same unsandboxed fix. *(measured)*

- **`git worktree prune` is denied by the same unlink, and it EXITS 0 while
  failing.** *(measured)* This is the nastier of the two:

  ```
  $ git worktree prune -v; echo "exit=$?"
  Removing worktrees/backlogger: gitdir file points to non-existent location
  error: failed to delete '.../.git/worktrees/backlogger': Operation not permitted
  exit=0
  ```

  The entry survives and `git worktree list` keeps showing it, now tagged
  `prunable`. `remove` at least exits 255; `prune` reports success, so
  `git worktree prune && echo done` prints `done` having done nothing. Never
  infer from its exit status — re-check `git worktree list`.

  **So there is no in-sandbox path to removing a worktree**, by either verb.
  It has to run unsandboxed — the maintainer pastes it with a `!` prefix, or
  the harness does it via `ExitWorktree` (which only ever covers the session's
  own `EnterWorktree` worktree, not a pre-existing one).
- **`git checkout -b <branch> origin/<branch>` fails**, because recording the
  upstream writes `.git/config` — and it fails *after* creating the branch, so
  the branch exists while the command reports an error and leaves you on the
  old one. Use `git checkout -b <branch> --no-track origin/<branch>`, or just
  re-run `git checkout <branch>`. *(measured)*
- **`git push -u` does not set the upstream either**, and for the same reason —
  `.git/config` is denied. This bullet used to recommend `-u` as the way around
  the previous one; it is not. What it does is **push the ref successfully and
  then report an error**:

  ```
  error: unable to write upstream branch configuration
  ```

  The branch IS on origin at that point. Verify with `git ls-remote origin
  <branch>` rather than re-pushing, and don't read the message as a failed
  push. Use a plain `git push origin <branch>`; nothing in this repo's flow
  needs the upstream recorded. *(measured)*
- **`git branch -D` prints a `.git/config` error and deletes the branch
  anyway**, exiting 0 with the noise on stderr:

  ```
  $ git branch -D worktree-backlogger; echo "exit=$?"
  error: could not lock config file .../.git/config
  warning: update of config-file failed
  Deleted branch worktree-backlogger (was 6c70a77d).
  exit=0
  ```

  Delete completed the part that matters: refs are not denied (next bullet),
  so the ref is gone. The config write it wanted was to drop the branch's
  `[branch "<name>"]` stanza — and **nothing was left behind**, verified by
  grepping `.git/config` afterwards, because the branch never had a stanza to
  drop. That is the general case under this sandbox rather than luck: writing
  one requires `git push -u` or `checkout -b --track`, both of which are
  denied by the two bullets above, so branches created here have no stanza.
  A branch predating the sandbox could still have one; whether `-D` then
  strands it is untested.

  Either way, do not re-run the delete on seeing the error and do not report
  the branch as still present — check `git branch --list <name>`. *(measured)*
- **`.git/objects`, refs and the index are NOT denied**, so commit, branch,
  reset and reflog work normally. *(measured — this is the one that matters)*
- The agent-config files are denied individually — `.claude/settings.json`,
  `.claude/hooks`, `.claude/skills`, `.claude/workflows`, `.claude/routines`,
  `.claude/output-styles`, `.claude/launch.json`, `.mcp.json` — but **not the
  `.claude` directory as a whole**. Edit those files with the Edit/Write tools,
  which the sandbox does not govern at all. *(measured)*
- `scripts/**` is **writable** from Bash. *(measured)* An earlier claim here
  that it was denied, along with `.github/` and the lockfiles, came from
  misreading the binary's *GitHub Actions* default config (it listed
  `~/actions-runner` and `GITHUB_EVENT_PATH`) as the local one.

**The sandbox captures its policy ONCE, at activation, and ignores every later
edit. You cannot iterate on `sandbox.*` in one session.** The trap is that it
*looks* like you can: editing `.claude/settings.json` mid-session does activate
the sandbox, so a session that turns it on immediately finds itself sandboxed
and concludes the config live-reloads. It does not. Every subsequent edit —
widening `allowWrite`, adding `allowMachLookup`, anything — is silently ignored
while probes keep returning confident results measured against the *first*
config. This was learned the expensive way: four knobs were "tested" that way
and none of the results meant anything. A probe write to a path added to
`allowWrite` minutes earlier still returned `Operation not permitted`, which is
what exposed it.

**So: one config change, then a genuinely fresh session, then
`verify-sandbox.sh`.** Never a second edit in the same session. If a result
contradicts the config you are looking at, the config is not what is running.

### Why each non-default knob is there

All four were verified together by a fresh-session `verify-sandbox.sh` run.
Each exists for one measured failure — don't drop one because it looks
redundant:

- **`enableWeakerNetworkIsolation`** — `gh` is a Go binary and returned
  *"tls: failed to verify certificate: x509: OSStatus -26276"*: it cannot reach
  `trustd` to verify TLS. Egress itself was never the problem — `curl
  https://github.com` returned 200 in the same sandbox. This is the documented
  knob for exactly this, and it is explicitly weaker: it opens `trustd`, which
  is a potential exfiltration path.
- **`network.allowMachLookup`** (`SecurityServer`, `securityd`, `trustd`) —
  `gh auth status` returned *"The token in keyring is invalid"*. gh reads its
  token from the macOS keychain, which is XPC, not network. The same block is
  why `git push` emitted `failed to store: 100001` — the credential helper
  could not cache the credential, though the push itself still landed.

  **When a keychain read does fail, `gh` does not error — it silently falls
  back to a token with fewer scopes**, so the symptom is a plain `Forbidden`
  on an API call that should have been permitted, and the obvious conclusion
  ("I lack permission for this operation") is wrong. Run `gh auth status`
  first: `✓ Logged in ... (keyring)` plus the expected scope line means the
  token is fine and the failure is something else. A `Failed to log in ...
  (keyring)` line means you are on the fallback token, and the fix is to
  restore keychain access or re-run `gh auth refresh`, NOT to widen anything.
  Diagnosed the expensive way: a `PUT .../dismissals` returned `Forbidden`
  in-sandbox and `DISMISSED` outside it, same account, same command.
- **`network.allowLocalBinding`** — `podman info` returned *"dial tcp
  127.0.0.1:64752: connect: operation not permitted"*. The podman VM is reached
  over a local TCP port, so `filesystem.allowRead` and
  `network.allowUnixSockets` are both the wrong knob.
- **`filesystem.allowWrite: [".", "~/GitHub/bess-manager"]`** —
  `frontend/node_modules` and `.venv` are symlinks into the main checkout, so
  writes through them land outside a worktree's own root and fail `EPERM`,
  breaking `vitest` and `vite build`. Native worktrees live under
  `.claude/worktrees/`, i.e. *inside* the main checkout, so that one entry
  covers them and every symlink target. That entry hardcodes this machine's
  layout, which is ugly in a tracked file; it is there because the alternative,
  a user-level `allowWrite`, is refused by the auto-mode classifier —
  correctly, since that is a session widening its own containment.

  **It does not cover a sibling checkout.** `../bess-manager-feature/` sits
  under `~/GitHub/`, not `~/GitHub/bess-manager`, so it is writable only via
  the `"."` entry resolving to that session's own cwd. A session working *on* a
  sibling from elsewhere — the main checkout, or another worktree — is silently
  blocked. Sibling folders are still first-class for running and inspecting
  code; they just need their own `allowWrite` entry if a session has to reach
  one from outside. `verify-sandbox.sh` skips its symlink check outside a
  linked worktree rather than reporting a PASS that proves nothing.

- **`filesystem.allowWrite: "~/.claude/jobs"`** — `claude agents --json` reads
  the session list from there, and a sandboxed call does not fail, it silently
  **TRUNCATES**. Measured in one session, seconds apart: **sandboxed returns 1
  agent, unsandboxed returns 14, of which 7 are live sessions sitting in
  worktrees.** All seven read as dead.

  That is not cosmetic. `backlog-rhythm.sh` keys `resume_implementation` off
  "worktree on disk, no live session", so with a truncated listing it told the
  maintainer to re-enter a worktree a live session was actively working — a
  second session on one branch, against commits the advice itself calls the
  only copy. `implement-issue` Step 0 reads the same list before touching a
  resumed branch, and both skills already carry a warning to run it
  unsandboxed. This makes the warning unnecessary rather than merely repeated.

  **An under-count, not an error, is the dangerous shape**: nothing about a
  short list looks wrong, so the wrong answer is acted on with full confidence.

  **`allowWrite`, not `allowRead`, and that is measured rather than assumed** —
  the obvious objection is that `claude agents --json` only *reads* the list.
  Two probes in a sandboxed session settle it:

  ```
  ls ~/.claude/jobs             ->  16 entries              # read:  ALLOWED
  touch ~/.claude/jobs/.probe   ->  Operation not permitted # write: DENIED
  ```

  Reads were never blocked; the read policy denies only `~/.claude/ide`.
  Enumeration needs to WRITE, and a dropped entry rather than an error is what
  produces the truncation. Same lesson as the podman entry below, where
  `filesystem.allowRead` was tried and disproved: read the actual error instead
  of reasoning about what ought to be blocked.

- **`filesystem.allowWrite`: the two user-level caches `worktree-setup.sh`
  writes** — `~/Library/Caches/ms-playwright` (plus its Linux spelling
  `~/.cache/ms-playwright`) and `~/.npm`. Setup runs `npm install` when a
  lockfile has diverged and then `npx playwright install chromium`; both write
  outside every repo path above, and the built-in allow list covers only
  `~/.npm/_logs`, not the package cache beside it.

  **Neither failure names the sandbox, which is the whole reason these are
  documented.** npm reports `EPERM` on `~/.npm/_cacache` as *"Your cache folder
  contains root-owned files … please run: sudo chown -R 502:20 ~/.npm"* — a
  guess, not a diagnosis: nothing is root-owned, and `sudo` is on the `ask`
  list and is the wrong fix. Playwright's step is bounded by
  `worktree-setup.sh`'s own timeout, whose message blames a slow download, so a
  blocked cache is indistinguishable from the genuine Playwright hang that
  timeout exists for (see below — a separate bug, and the two must not be
  conflated). One session lost a whole worktree setup to that before the cause
  was probed directly.

  Do **not** dodge the Playwright half by pointing `PLAYWRIGHT_BROWSERS_PATH`
  into the repo. Browsers are ~170MB and deliberately shared by every worktree;
  a per-worktree cache re-downloads them ~20 times over. `verify-sandbox.sh`
  probes both caches with `mkdir`, creating the directory first so a fresh
  machine reports a real result rather than skipping.

### The Playwright install hang is a version bug, not a slow download

Distinct from the sandbox problem above, and repeatedly misread as one. There
is **no issue tracking it** — `worktree-setup.sh` cites #556 only because that
is the work it was first seen during, and #556 (dependency caching) is closed.

Measured 2026-08-17, unsandboxed, on this machine:

| Playwright | Browser build | Result |
|---|---|---|
| 1.59.1 (the pin in `e2e/package.json`) | `chromium-1217` | stalls at **exactly** 84 files / 448K, twice |
| 1.62.1 (current latest) | `chromium-1234` | completes, minutes later, same network |

**It is not the download.** In both stalled runs the full 173MB zip had already
landed in `$TMPDIR/playwright-download-*`, and `sample`ing the process showed
`oopDownloadBrowserMain.js` idle at 0% CPU with every libuv worker parked in
`__psynch_cvwait`. The failure is in *extraction*, after a complete fetch —
which is why waiting it out never works and why the timeout's "no progress"
wording sends readers to the network.

So `worktree-setup.sh` cannot install browsers on the pinned version, and the
likely fix is bumping `@playwright/test` past 1.59.1. Not done yet: it moves
the E2E runner under 14 CI wizard scenarios and needs its own PR. Until then a
worktree needing browsers is blocked, and the workaround is to drive an
already-installed Chrome rather than to keep retrying the install.

`sandbox.excludedCommands` is **not** used and is not needed. It was tried in
both project and user settings while the four knobs above were missing, appeared
to do nothing, and is now moot.

**What the verification does and does not cover.** It exercises `gh auth
status` (the keychain and TLS paths — good coverage of what `gh pr create`
needs) and `podman info` (the socket/TCP connection only, *not* that a compose
E2E completes). A full Step 8 run and a `gh pr create` are still the first real
proof. If either fails, re-read the error before touching config: every knob
here was found by reading the actual message, and every wrong guess came from
reasoning about what *ought* to be blocked.

**Verify with `bash scripts/verify-sandbox.sh` in a FRESH session after any
change to `sandbox.*`, and let the Bash TOOL run it.** Fresh because of the
capture-once behaviour above. Bash tool because the sandbox applies only to
commands Claude Code itself runs — a `!`-prefixed or terminal-typed invocation
is unsandboxed and would pass the permissive checks while failing the
restrictive ones, which reads exactly like a real result. Check 0 catches that.

To set work aside on the branch you are on, use a temporary WIP commit — it
lives on the branch, so it is per-worktree, private to that agent, and
recoverable by SHA even if the branch moves:

```bash
git add -A && git commit -m "wip: <what>"   # set aside
git reset --soft HEAD~1                     # pick back up
```

To move changes *across* checkouts (the case stash used to cover), pipe a patch
through the shared object database — verify it landed before reverting, since
`git checkout --` is the destructive step and there is no stash to fall back on:

```bash
git diff -- <file> | git -C .claude/worktrees/<name> apply
git -C .claude/worktrees/<name> diff -- <file>   # verify
git checkout -- <file>                           # only then
```

The full procedure, including the staged-changes variant, is in
`docs/agents/rules.md` under Working Location.

**The Bash rules apply identically in the main checkout and in every worktree.**
There is no cwd-conditional behaviour left, so nothing changes when a session
enters a worktree.

**Don't add a prompt where git already refuses.** `git branch -D` is
deliberately not in the `ask` list: git refuses to delete a branch checked out
in another worktree, so nothing a prompt would add is real. `git worktree
remove`/`prune` are not in the list either, but for a different reason — a
prompt cannot make them safe, because it does not un-deny the sandboxed
`.git/worktrees/<name>` unlink that corrupts an otherwise-clean worktree
mid-removal (see "What stays denied" above). The guard is that the skills never
call them from sandboxed Bash: they report `PRUNE`/`CARCASS`/`PHANTOM` and emit
a `!`-prefixed command for the maintainer instead.

**GitHub now refuses the dangerous pushes, which is the same reasoning one
layer out.** `--force`, `--force-with-lease` and `+refspec` all used to ask,
because a prefix glob could not tell them apart from a plain push. None of them
ask now: against a protected ref GitHub rejects the push outright, and against
an unprotected feature branch it was never the case that git could not undo it.
That removed a prompt from `implement-issue` Step 9 without removing a guard —
see "Pushing is guarded server-side" above for the ruleset table and the one
residual it accepts.

**A force push should still be treated as a finding when it appears.** Neither
`implement-issue` nor `release` mentions `rebase`, `--force` or
`--force-with-lease` anywhere, and this project merges the target branch before
a PR instead of rebasing — a merge-based flow never needs one. So if a
transcript shows a force push, an agent has gone off-script into a rebase or an
amend of already-pushed commits. That is now caught by reading what happened
rather than by a prompt, which is the trade: no stall on the common path, and
the destructive path is refused by the server instead of by you.

**What the unattended set actually risks is uncommitted work**, since the
sandbox contains writes to the repo but cannot distinguish a wanted write from
an unwanted one. Tracked content
survives anything on the list — `git reset --hard` and `rm` on a tracked file
are both recoverable from the object database, and a discarded commit is
recoverable by SHA from the reflog. Uncommitted, untracked work is not. That is
the argument for the WIP-commit habit below, and it is why `git stash` is denied
rather than merely prompted: it is the one command that destroys another agent's
uncommitted work rather than your own.

**Only tracked files travel into a worktree**, and the permission setup is now
entirely tracked: `.claude/settings.json` and `.claude/hooks/*` follow every
worktree automatically, so a session behaves the same wherever it runs. Keep it
that way. `.claude/settings.local.json` is gitignored and exists only in the
main checkout; the previous design leaned on it and then needed a SessionStart
hook to symlink it into each worktree to undo the asymmetry. Anything that has
to hold in a worktree belongs in the tracked settings. The doesn't-travel
problem still applies to `.venv` and `frontend/node_modules` (see
`scripts/worktree-setup.sh`, issue #556).
