"""Claude Issue Triage Agent.

Runs automatically when a new issue is created or when a user provides
a debug log on an issue that is waiting for one.

Responsibilities:
- Classify the issue (bug / feature / question / other)
- Apply appropriate GitHub labels
- For bugs without debug info: request a BESS debug export
- For bugs with debug info: perform initial root-cause analysis
- For features/questions: acknowledge and guide the contributor

GitHub Actions usage (env vars set by issue-triage.yml):
    python scripts/issue_triage.py

CLI usage:
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/issue_triage.py --issue 42
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/issue_triage.py --issue 42 --repo owner/repo
    # Simulate debug-log-provided trigger:
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... \\
      python scripts/issue_triage.py --issue 42 --mode analyze_log
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from github import Github

# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

DEBUG_LOG_REQUEST = """\
Thanks for the report! To investigate this I need a BESS debug log.

**How to get it:**

1. In the BESS Manager web interface, go to **System Health**
2. Click **Download Debug Report** (or use the API: `GET /api/debug`)
3. Paste the contents of the downloaded JSON file as a code block in a comment here

The debug report contains schedule, sensor readings, price data, and recent \
error logs — everything needed to reproduce and diagnose the issue without \
requiring access to your installation.
"""

FEATURE_ACKNOWLEDGEMENT = """\
Thanks for the suggestion! I've tagged this as an enhancement for tracking.

If you can share a bit more about your use case (what you're trying to achieve \
and why the current behaviour doesn't work for you), that helps with prioritisation.
"""


def read_file_if_exists(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text()


def build_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("REPO_FULL_NAME", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def bot_footer() -> str:
    run_url = build_run_url()
    suffix = f" · [View run]({run_url})" if run_url else ""
    return f"\n\n---\n*Triaged by claude-triage bot{suffix}*"


# ---------------------------------------------------------------------------
# Label management
# ---------------------------------------------------------------------------

LABEL_SPECS = {
    "bug": {"color": "d73a4a", "description": "Something isn't working"},
    "enhancement": {"color": "a2eeef", "description": "New feature or request"},
    "question": {"color": "d876e3", "description": "Further information is requested"},
    "needs-debug-log": {
        "color": "e4e669",
        "description": "Waiting for user to provide debug export",
    },
    "bot-analyzed": {
        "color": "0075ca",
        "description": "Triage bot has processed this issue",
    },
}


def ensure_labels(gh_repo) -> None:
    existing = {lbl.name for lbl in gh_repo.get_labels()}
    for name, spec in LABEL_SPECS.items():
        if name not in existing:
            gh_repo.create_label(name=name, **spec)


def apply_labels(issue, add: list[str], remove: list[str] | None = None) -> None:
    current = {lbl.name for lbl in issue.labels}
    for label in add:
        if label not in current:
            issue.add_to_labels(label)
    for label in remove or []:
        if label in current:
            issue.remove_from_labels(label)


# ---------------------------------------------------------------------------
# Triage via Claude
# ---------------------------------------------------------------------------

TRIAGE_SCHEMA = {
    "name": "triage_result",
    "description": "Structured triage classification for a GitHub issue",
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["bug", "feature", "question", "other"],
                "description": "Issue classification",
            },
            "has_debug_info": {
                "type": "boolean",
                "description": (
                    "True if the issue body contains a BESS debug log or "
                    "sufficient technical detail to diagnose a bug"
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence in the classification",
            },
            "summary": {
                "type": "string",
                "description": "One sentence describing the issue",
            },
            "initial_analysis": {
                "type": "string",
                "description": (
                    "For bugs with debug info: brief root-cause hypothesis. "
                    "For other types: empty string."
                ),
            },
        },
        "required": ["type", "has_debug_info", "confidence", "summary"],
    },
}


def triage_with_claude(
    client: anthropic.Anthropic,
    issue_title: str,
    issue_body: str,
    rules_md: str,
    arch_md: str,
) -> dict:
    system = "\n".join(
        [
            "You are an expert BESS (Battery Energy Storage System) support engineer.",
            "Your job is to triage GitHub issues for the bess-manager project.",
            "Classify issues accurately and identify bugs that have enough information",
            "to begin root-cause analysis.",
            "",
            f"<rules>\n{rules_md}\n</rules>" if rules_md else "",
            f"<architecture>\n{arch_md}\n</architecture>" if arch_md else "",
        ]
    )

    user = "\n".join(
        [
            f"## Issue: {issue_title}",
            "",
            issue_body or "(no description provided)",
        ]
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system,
        tools=[TRIAGE_SCHEMA],
        tool_choice={"type": "tool", "name": "triage_result"},
        messages=[{"role": "user", "content": user}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "triage_result":
            return block.input

    raise RuntimeError("Claude did not return a triage_result tool call")


# ---------------------------------------------------------------------------
# Debug log analysis via Claude
# ---------------------------------------------------------------------------


def analyze_debug_log(
    client: anthropic.Anthropic,
    issue_title: str,
    issue_body: str,
    rules_md: str,
    arch_md: str,
) -> str:
    system = "\n".join(
        [
            "You are an expert BESS (Battery Energy Storage System) support engineer.",
            "Analyze the debug log provided in the issue and identify the root cause.",
            "Be specific: name the component, the condition, and the likely fix.",
            "Format your response in Markdown. Keep it under 400 words.",
            "",
            f"<rules>\n{rules_md}\n</rules>" if rules_md else "",
            f"<architecture>\n{arch_md}\n</architecture>" if arch_md else "",
        ]
    )

    user = "\n".join(
        [
            f"## Issue: {issue_title}",
            "",
            issue_body or "(no description provided)",
            "",
            "Please analyze the debug log above and identify the root cause of the reported problem.",
        ]
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    for block in response.content:
        if hasattr(block, "text"):
            return block.text

    return "(no analysis produced)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Issue Triage Agent")
    parser.add_argument("--issue", type=int, help="Issue number (CLI mode)")
    parser.add_argument("--repo", help="owner/repo (CLI mode)")
    parser.add_argument(
        "--mode",
        default="triage",
        choices=["triage", "analyze_log"],
        help="triage = classify new issue; analyze_log = user provided debug log",
    )
    args = parser.parse_args()

    github_token = os.environ["GITHUB_TOKEN"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    repo_full_name = args.repo or os.environ["REPO_FULL_NAME"]
    issue_number = args.issue or int(os.environ["ISSUE_NUMBER"])
    mode = args.mode or os.environ.get("TRIAGE_MODE", "triage")

    repo_root = os.getcwd()
    rules_md = read_file_if_exists(Path(repo_root) / "docs/agents/rules.md")
    arch_md = read_file_if_exists(Path(repo_root) / "docs/agents/architecture.md")

    print(f"Triaging issue #{issue_number} in {repo_full_name} (mode={mode})")

    gh = Github(github_token)
    gh_repo = gh.get_repo(repo_full_name)
    issue = gh_repo.get_issue(issue_number)

    ensure_labels(gh_repo)

    client = anthropic.Anthropic(api_key=anthropic_api_key)

    # -----------------------------------------------------------------------
    # Mode: analyze_log — user has now provided debug data, run deeper analysis
    # -----------------------------------------------------------------------
    if mode == "analyze_log":
        print("Running debug log analysis...")
        analysis = analyze_debug_log(
            client,
            issue.title,
            issue.body or "",
            rules_md,
            arch_md,
        )
        comment = "\n".join(
            [
                "## Debug Log Analysis",
                "",
                analysis,
                "",
                "If this looks correct, you can trigger an automated fix with:",
                "",
                "> `@claude-bot fix this`",
                "",
                bot_footer(),
            ]
        )
        issue.create_comment(comment)
        apply_labels(issue, add=["bot-analyzed"], remove=["needs-debug-log"])
        print("Analysis comment posted.")
        return

    # -----------------------------------------------------------------------
    # Mode: triage — new issue, classify and respond
    # -----------------------------------------------------------------------
    print("Running triage classification...")
    result = triage_with_claude(
        client,
        issue.title,
        issue.body or "",
        rules_md,
        arch_md,
    )
    print(f"Classification: {json.dumps(result, indent=2)}")

    issue_type = result["type"]
    has_debug_info = result.get("has_debug_info", False)
    initial_analysis = result.get("initial_analysis", "")

    if issue_type == "bug":
        if has_debug_info:
            # We have enough to start analysis right away
            analysis = initial_analysis or analyze_debug_log(
                client,
                issue.title,
                issue.body or "",
                rules_md,
                arch_md,
            )
            comment = "\n".join(
                [
                    "## Initial Analysis",
                    "",
                    f"**Summary**: {result['summary']}",
                    "",
                    analysis,
                    "",
                    "To trigger an automated fix:",
                    "",
                    "> `@claude-bot fix this`",
                    "",
                    bot_footer(),
                ]
            )
            issue.create_comment(comment)
            apply_labels(issue, add=["bug", "bot-analyzed"])
        else:
            # Need debug log first
            issue.create_comment(DEBUG_LOG_REQUEST + bot_footer())
            apply_labels(issue, add=["bug", "needs-debug-log"])

    elif issue_type == "feature":
        issue.create_comment(FEATURE_ACKNOWLEDGEMENT + bot_footer())
        apply_labels(issue, add=["enhancement"])

    elif issue_type == "question":
        # For questions, just label — no auto-response to avoid being noisy
        apply_labels(issue, add=["question"])

    else:
        # other — label as question for now
        apply_labels(issue, add=["question"])

    print(f"Triage complete: {issue_type}, has_debug_info={has_debug_info}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
