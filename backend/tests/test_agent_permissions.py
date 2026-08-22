"""Pins the permission profile in `.claude/settings.json` to what the skills run.

`implement-issue` drives an issue end-to-end inside a worktree. Every command
it needs must run unattended, or the skill stalls overnight waiting for an
approval nobody is awake to give; every command that is the maintainer's call
must stop and ask. Those two lists are derivable — they are written down in
`.claude/skills/*/SKILL.md` — so they can be pinned instead of remembered.

`gh api` is deliberately a blanket `ask`, not an allow-plus-enumeration. The
write forms put their marker at an arbitrary argument position (`gh api <path>
-X PUT`), which a prefix glob cannot reach, and enumerating them left real
holes twice (see quality-check.sh). A blanket `Bash(gh *)` allow inverts that,
letting `gh auth token` and `gh issue close` through — so there is none, and
every interactive `gh api` prompts once instead. Dispatched agents bypass
permissions entirely, so headless runs are unaffected.

**What this test does and does not prove.** It models the matcher as
`deny > ask > allow` with `fnmatch` over the rule strings. Claude Code's real
matcher parses shell more carefully than that, so this asserts *the rule set
expresses the intent* — not that the harness behaves this way. The one
behaviour verified against the real matcher by hand is that mid-string
wildcards match (`git -c core.pager=cat stash --help` is caught by
`Bash(git -* stash --*)`).
"""

import fnmatch
import json
import os
import re
from pathlib import Path

import pytest

# A dispatched container runs bypassPermissions by design: the clone's
# .claude/settings.json is shadowed by container/agent-settings.json, so the
# host permission profile is not what executes there. These pins validate that
# host profile -- meaningless (and failing) inside a container.
pytestmark = pytest.mark.skipif(
    os.environ.get("BESS_HEADLESS_MODE") == "1",
    reason="host permission policy is replaced by container/agent-settings.json in headless mode",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

# deny wins over ask, ask wins over allow -- by category, not by specificity.
PRECEDENCE = ("deny", "ask", "allow")


def _rules() -> dict[str, list[str]]:
    perms = json.loads(SETTINGS.read_text())["permissions"]
    out: dict[str, list[str]] = {}
    for category in PRECEDENCE:
        patterns = []
        for rule in perms.get(category, []):
            # "Bash(gh pr view *)" -> "gh pr view *"; trailing " in <repo>" scoping ignored.
            match = re.match(r"^Bash\((.*)\)$", rule.split(" in ")[0])
            if match:
                patterns.append(match.group(1))
        out[category] = patterns
    return out


def decide(command: str, rules: dict[str, list[str]]) -> str:
    for category in PRECEDENCE:
        for pattern in rules[category]:
            if command == pattern or fnmatch.fnmatchcase(command, pattern):
                return category
    return "unmatched"


@pytest.fixture(scope="module")
def rules() -> dict[str, list[str]]:
    return _rules()


# Every command `implement-issue` runs to take an issue from fetch to a ready
# PR. Sources are noted where the skill delegates rather than spelling it out.
RUNS_UNATTENDED = [
    # Step 0/1 -- resume check and scoping
    "gh issue view 275 --json title,body,comments",
    "gh pr list --state open --search 275 --json number,headRefName",
    "git branch --list *issue-275*",
    # Step 4 -- prune merged worktrees, then cut the branch.
    # `git -C <path> ...` is why git stays blanket-allowed: the flag sits
    # between the binary and the subcommand, so `git branch *` misses it.
    "gh pr list --state merged --limit 200 --json headRefName",
    "git worktree list",
    "git -C ../wt branch --show-current",
    "git -C ../wt status --porcelain -uno",
    "git worktree remove ../wt",
    "git branch -D issue-275",
    "git fetch origin --prune",
    "git worktree add ../wt origin/main",  # via superpowers:using-git-worktrees
    "./scripts/worktree-setup.sh",
    # Steps 5-8 -- TDD, quality gate, local verification
    ".venv/bin/pytest -m not slow",
    ".venv/bin/python scripts/capture_vpp_baseline.py",
    "./scripts/quality-check.sh",
    "podman-compose -f docker-compose.ci.yml up -d",
    "npm run build",
    "npx vitest run",
    # Step 9 -- commit, sync, push, draft PR.
    # via superpowers:finishing-a-development-branch (Option 2: push + PR)
    "git commit -m fix: something",
    "git fetch origin",
    "git merge origin/main",
    "git push origin HEAD",
    "gh pr create --draft --title x --body y",
    # Step 10 -- watch this PR to green
    "gh pr checks 614 --watch --fail-fast",
    "gh run list --workflow PR Review --limit 20",
    "gh run view 123 --log-failed",
    # Step 11 -- the review loop, and the flag that ends it
    "scripts/request-pr-review.sh 614",
    "scripts/gh-agent.sh --as dev pr comment 614 --body ok",
    "gh pr view 614 --json reviews",
    # Step 11's inline-review-comment read (gh api .../comments --jq .[], the
    # only way to read them) is intentionally NOT here: `gh api` is a blanket
    # ask by design (see test_gh_api_is_blanket_ask), so it prompts instead of
    # running unattended.
    "gh pr ready 614",
]

# Outward-facing, irreversible, or costly -- and none of them enforceable by a
# server-side ruleset, which only governs ref integrity on protected branches.
NEEDS_APPROVAL = [
    "gh pr merge 614 --squash",  # CLAUDE.md: the merge is the maintainer's, always
    "gh pr close 614",
    "gh issue close 275",  # only the final prod PR closes a reporter's issue
    "gh release create v9.9.0",
    "gh release delete v9.9.0",
    "gh secret set FOO",
    "gh workflow run issue-fix.yml",  # spends money on a paid agent stage
    "gh repo edit --visibility public",
]

# Prohibited outright: the skills' own "never do this" lines, plus the one
# command that would hand a credential to anything reading stdout.
FORBIDDEN = [
    "git reset --hard origin/main",  # SKILL.md:176, never on a resumed branch
    "git push --force origin HEAD",
    "git push -f origin HEAD",
    "git stash",  # denied repo-wide: one shared stack across worktrees
    "gh auth token",
]

# `deny` has no override (rules.md:21-24), so a pattern that is broader than
# the danger it targets removes a workflow outright rather than gating it.
# `git reset --hard` discards committed work; the other forms do not, and
# rules.md:36-40 prescribes `--soft` as the WIP-commit recovery pattern now
# that `git stash` is denied repo-wide. An earlier revision of this profile
# denied `git reset*` wholesale and took that recovery path with it.
MUST_NOT_BE_DENIED = [
    "git reset --soft HEAD~1",  # rules.md:36-40, picking a WIP commit back up
    "git reset HEAD backend/app.py",  # unstaging; discards nothing
]


@pytest.mark.parametrize("command", RUNS_UNATTENDED)
def test_implement_issue_runs_without_prompting(
    command: str, rules: dict[str, list[str]]
) -> None:
    verdict = decide(command, rules)
    assert verdict == "allow", (
        f"{command!r} resolves to {verdict!r}. implement-issue runs this "
        f"unattended; anything but 'allow' stalls the skill mid-issue."
    )


@pytest.mark.parametrize("command", NEEDS_APPROVAL)
def test_maintainer_decisions_still_ask(
    command: str, rules: dict[str, list[str]]
) -> None:
    verdict = decide(command, rules)
    assert verdict == "ask", (
        f"{command!r} resolves to {verdict!r}, expected 'ask'. This action is "
        f"outward-facing or irreversible and no server-side ruleset covers it."
    )


@pytest.mark.parametrize("command", FORBIDDEN)
def test_prohibited_commands_are_denied(
    command: str, rules: dict[str, list[str]]
) -> None:
    verdict = decide(command, rules)
    assert verdict == "deny", f"{command!r} resolves to {verdict!r}, expected 'deny'."


@pytest.mark.parametrize("command", MUST_NOT_BE_DENIED)
def test_non_destructive_forms_keep_an_escape_hatch(
    command: str, rules: dict[str, list[str]]
) -> None:
    verdict = decide(command, rules)
    assert verdict != "deny", (
        f"{command!r} is denied. `deny` never prompts, so this removes the "
        f"workflow entirely rather than gating it -- narrow the pattern to the "
        f"destructive form instead."
    )


def test_gh_api_is_blanket_ask(rules: dict[str, list[str]]) -> None:
    """`gh api` reads and writes all resolve to 'ask' under the blanket rule.

    The blanket `Bash(gh api *)` sits in `ask`, so argument position no longer
    matters — every `gh api` prompts once, reads included. This is the decision
    quality-check.sh enforces; the enumerated write-form rules that used to
    live here were removed because they left argument-position holes.
    """
    endpoint = "repos/johanzander/bess-manager/pulls/614/comments"
    assert decide(f"gh api {endpoint}", rules) == "ask"

    for write in (
        f"gh api {endpoint} -X POST -f body=hi",
        f"gh api -X POST {endpoint} -f body=hi",
        f"gh api {endpoint} --method DELETE",
        f"gh api --method DELETE {endpoint}",
        f"gh api {endpoint} -f body=hi",
        f"gh api -f body=hi {endpoint}",
        # Long forms. `gh api --help`: `-F, --field` and `-f, --raw-field`.
        # Enumerating only the short spellings left these reaching `allow` via
        # `Bash(gh api *)` -- a write that never prompts. This is the exact
        # leak the enumeration keeps re-opening, so it is pinned by command
        # string here rather than by asserting which rule happens to catch it.
        f"gh api {endpoint} --field body=hi",
        f"gh api --field body=hi {endpoint}",
        f"gh api {endpoint} --raw-field body=hi",
        f"gh api --raw-field body=hi {endpoint}",
        # Attached-value spellings. cobra/pflag takes `--flag=value` and
        # `-fvalue` as readily as `--flag value`; the space-separated globs
        # above end in ` --field ` (with a space) and cannot reach them, so
        # `--field=body=hi` resolved to `allow` -- a write that never prompts.
        f"gh api {endpoint} --field=body=hi",
        f"gh api --field=body=hi {endpoint}",
        f"gh api {endpoint} --raw-field=body=hi",
        f"gh api --raw-field=body=hi {endpoint}",
        f"gh api {endpoint} --method=PUT",
        f"gh api --method=PUT {endpoint}",
        f"gh api {endpoint} -XPUT",
        f"gh api -XPUT {endpoint}",
        f"gh api {endpoint} -fbody=hi",
        f"gh api -fbody=hi {endpoint}",
        f"gh api {endpoint} -Fbody=hi",
        f"gh api -Fbody=hi {endpoint}",
    ):
        assert decide(write, rules) == "ask", f"{write!r} must ask"


def test_no_client_rule_duplicates_a_server_ruleset(
    rules: dict[str, list[str]],
) -> None:
    """Ref protection is the server's job; duplicating it is pure friction.

    `main`, `beta` and tags are protected by GitHub rulesets with empty bypass
    lists, so a push that should not happen is already impossible. A
    client-side `git push` gate therefore cannot fire on the dangerous case --
    only on the routine one, prompting on every feature-branch push.
    """
    for pattern in rules["ask"]:
        assert not pattern.startswith("git push"), (
            f"{pattern!r} duplicates server-side ref protection. The dangerous "
            f"case is already blocked; this only prompts on routine pushes."
        )
