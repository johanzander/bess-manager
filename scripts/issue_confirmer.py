"""Claude Issue Confirmer.

Read-only agentic script that verifies whether a reported bug actually exists in
the current codebase before any fix is attempted.

The confirmer:
1. Checks the reported version against the current version in config.yaml.
2. Uses an agentic read loop (read_file, list_directory, search_files) to trace
   the exact code path described in the bug report.
3. Returns a structured verdict — only "confirmed_bug" triggers the fix pipeline.

GitHub Actions usage (env vars set by claude-bot.yml):
    python scripts/issue_confirmer.py

CLI usage:
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/issue_confirmer.py --issue 42
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/issue_confirmer.py --issue 42 --repo owner/repo
"""

import argparse
import os
import re
import sys
from pathlib import Path

import anthropic
from github import Github

# ---------------------------------------------------------------------------
# Read-only tools for the agentic loop (no write_file)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the repository. Returns its full contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from the repo root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "List the contents of a directory (files and subdirectories).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from the repo root (default: .)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_files",
        "description": (
            "Search for a text pattern across files. "
            "Returns matching lines with file paths and line numbers. "
            "Use this to locate relevant code, then read_file to examine it in full."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (substring)",
                },
                "file_glob": {
                    "type": "string",
                    "description": "Optional glob to restrict search, e.g. '*.py'",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "report_verdict",
        "description": (
            "Report the final verdict on whether the reported bug exists in the "
            "current codebase. Call this exactly once when your investigation is complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": [
                        "confirmed_bug",
                        "likely_user_error",
                        "version_mismatch",
                        "cannot_confirm",
                        "needs_more_info",
                    ],
                    "description": (
                        "confirmed_bug: you read the code and the defect is present. "
                        "likely_user_error: user misconfiguration or misunderstanding. "
                        "version_mismatch: reported version differs from current, bug may be fixed. "
                        "cannot_confirm: evidence is inconclusive after thorough inspection. "
                        "needs_more_info: insufficient information to investigate."
                    ),
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "How confident are you in this verdict.",
                },
                "code_evidence": {
                    "type": "string",
                    "description": (
                        "Specific evidence quoted DIRECTLY from files you read with read_file. "
                        "Format each reference as 'file.py:LINE: <code snippet>'. "
                        "DO NOT use grep output as evidence — you must have read the file. "
                        "For confirmed_bug: quote the defective code. "
                        "For likely_user_error: quote the correct behaviour in the code. "
                        "Leave empty only for needs_more_info."
                    ),
                },
                "explanation": {
                    "type": "string",
                    "description": (
                        "Clear explanation of your verdict: what you found (or didn't find), "
                        "why the bug does or does not exist, and what the user should do next."
                    ),
                },
                "fix_hint": {
                    "type": "string",
                    "description": (
                        "For confirmed_bug only: the exact file, function, and what change is needed. "
                        "Be specific — reference line numbers and show before/after if helpful. "
                        "Leave empty for all other verdicts."
                    ),
                },
            },
            "required": ["verdict", "confidence", "explanation"],
        },
    },
]


def handle_tool(name: str, inputs: dict, repo_root: str) -> tuple[str, dict | None]:
    """Returns (result_text, verdict_dict_or_None)."""
    if name == "read_file":
        full = Path(repo_root) / inputs["path"]
        if not full.exists():
            return f"ERROR: file not found: {inputs['path']}", None
        text = full.read_text(errors="replace")
        if len(text) > 10_000:
            text = text[:10_000] + f"\n... (truncated, {len(text)} chars total)"
        return text, None

    if name == "list_directory":
        rel_path = inputs.get("path", ".")
        full = Path(repo_root) / rel_path
        if not full.exists():
            return f"ERROR: directory not found: {rel_path}", None
        items = sorted(full.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = []
        for item in items:
            if item.name.startswith(".") and item.name not in (".github",):
                continue
            suffix = "/" if item.is_dir() else ""
            lines.append(f"{item.name}{suffix}")
        return "\n".join(lines) if lines else "(empty)", None

    if name == "search_files":
        pattern = inputs["pattern"]
        file_glob = inputs.get("file_glob", "")
        results = []
        search_root = Path(repo_root)
        glob_pattern = f"**/{file_glob}" if file_glob else "**/*"
        for path in search_root.glob(glob_pattern):
            if not path.is_file():
                continue
            skip_dirs = {
                ".git",
                "__pycache__",
                "node_modules",
                ".venv",
                "dist",
                "build",
            }
            if any(part in skip_dirs for part in path.parts):
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.lower() in line.lower():
                    rel = path.relative_to(search_root)
                    results.append(f"{rel}:{i}: {line.rstrip()}")
            if len(results) > 200:
                results.append("... (truncated at 200 matches)")
                break
        return "\n".join(results) if results else "No matches found.", None

    if name == "report_verdict":
        return "Verdict recorded.", inputs

    return f"ERROR: unknown tool: {name}", None


# ---------------------------------------------------------------------------
# Version extraction
# ---------------------------------------------------------------------------


def read_current_version(repo_root: str) -> str:
    config_path = Path(repo_root) / "config.yaml"
    if not config_path.exists():
        return ""
    text = config_path.read_text()
    m = re.search(r"^\s*version\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?", text, re.MULTILINE)
    return m.group(1) if m else ""


def extract_reported_version(text: str) -> str:
    """Try to find a version number mentioned in the issue body."""
    m = re.search(r"\b(\d+\.\d+\.\d+(?:[.-]\w+)?)\b", text or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    return f"\n\n---\n*Verified by claude-confirmer bot{suffix}*"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_VERDICT_LABELS = {
    "confirmed_bug": "bug",
    "likely_user_error": "question",
    "version_mismatch": "question",
    "cannot_confirm": "question",
    "needs_more_info": "needs-debug-log",
}

_VERDICT_HEADING = {
    "confirmed_bug": "Bug Confirmed",
    "likely_user_error": "Likely User Configuration Issue",
    "version_mismatch": "Version Mismatch — May Be Fixed",
    "cannot_confirm": "Could Not Confirm Bug",
    "needs_more_info": "More Information Needed",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Issue Confirmer")
    parser.add_argument("--issue", type=int, help="Issue number (CLI mode)")
    parser.add_argument("--repo", help="owner/repo (CLI mode)")
    args = parser.parse_args()

    github_token = os.environ["GITHUB_TOKEN"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    repo_full_name = args.repo or os.environ["REPO_FULL_NAME"]
    repo_root = os.getcwd()

    issue_number = args.issue or int(os.environ["ISSUE_NUMBER"])

    print(f"Confirming issue #{issue_number} in {repo_full_name}")

    gh = Github(github_token)
    gh_repo = gh.get_repo(repo_full_name)
    issue = gh_repo.get_issue(issue_number)

    current_version = read_current_version(repo_root)
    reported_version = extract_reported_version(issue.body or "")

    rules_md = read_file_if_exists(Path(repo_root) / "docs/agents/rules.md")
    arch_md = read_file_if_exists(Path(repo_root) / "docs/agents/architecture.md")

    # Gather issue comments so the confirmer sees any debug logs already posted
    comments_text = ""
    for comment in issue.get_comments():
        comments_text += (
            f"\n\n---\n**Comment by {comment.user.login}:**\n{comment.body}"
        )

    version_note = ""
    if current_version:
        version_note = f"\nCurrent codebase version: **{current_version}**"
        if reported_version:
            version_note += f"\nReported version in issue: **{reported_version}**"
            if reported_version != current_version:
                version_note += (
                    "\n⚠️ Versions differ — check whether the bug still exists in the "
                    "current code before confirming."
                )

    system_parts = [
        "You are claude-confirmer, a careful software verification bot.",
        "Your ONLY job is to determine whether the reported bug actually exists in the "
        "CURRENT codebase by reading the source files.",
        "",
        "RULES:",
        "- You MUST call read_file on the relevant source files before forming any conclusion.",
        "- search_files and list_directory are for LOCATING code only — they are NOT evidence.",
        "- code_evidence in your verdict must be quoted from files you personally read with "
        "read_file, citing exact file:line references.",
        "- Do NOT claim a bug is confirmed based on grep output or log entries alone.",
        "- If you cannot read the relevant code (file not found, etc.), verdict = cannot_confirm.",
        "- Be conservative: if you are unsure, prefer cannot_confirm over confirmed_bug.",
        "- You MUST finish by calling report_verdict. Do NOT stop without calling it.",
        "- If you feel done but haven't called report_verdict, call it immediately.",
    ]
    if rules_md:
        system_parts.append(f"\n<hard_constraints>\n{rules_md}\n</hard_constraints>")
    if arch_md:
        system_parts.append(
            f"\n<architecture_reference>\n{arch_md}\n</architecture_reference>"
        )
    system_prompt = "\n".join(system_parts)

    user_message = "\n".join(
        [
            f"## Issue #{issue_number}: {issue.title}",
            "",
            "**Description:**",
            issue.body or "(no description)",
            version_note,
            comments_text,
            "",
            "## Your task",
            "Investigate whether this bug exists in the current codebase.",
            "",
            "Step-by-step approach:",
            "1. Read docs/agents/architecture.md to understand the codebase layout.",
            "2. Use search_files to locate the relevant code paths mentioned in the report.",
            "3. Use read_file to read those files in full — do NOT skip this step.",
            "4. Trace the specific code path that would produce the reported behaviour.",
            "5. Call report_verdict with your findings, quoting the exact lines you read.",
            "",
            "Remember: you MUST read the source files with read_file before you can claim "
            "a bug is confirmed or denied. Grep results are starting points, not conclusions.",
        ]
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    messages = [{"role": "user", "content": user_message}]
    verdict: dict | None = None

    print("Starting agentic confirmation loop...")
    for _iteration in range(25):
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8192,
            system=system_prompt,
            tools=TOOLS,
            tool_choice={"type": "any"},  # model MUST call a tool every turn
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  Tool call: {block.name}({list(block.input.keys())})")
            result_text, maybe_verdict = handle_tool(block.name, block.input, repo_root)
            if maybe_verdict is not None:
                verdict = maybe_verdict
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text[:5000],
                }
            )

        if verdict is not None:
            print(f"Verdict received: {verdict['verdict']} ({verdict['confidence']})")
            break
        messages.append({"role": "user", "content": tool_results})
    else:
        print("WARNING: reached iteration cap without verdict.")

    if verdict is None:
        issue.create_comment(
            "I investigated this issue but was unable to reach a conclusive verdict "
            "after examining the codebase. A human reviewer should look at this."
            + bot_footer()
        )
        return

    v = verdict["verdict"]
    confidence = verdict["confidence"]
    explanation = verdict.get("explanation", "")
    code_evidence = verdict.get("code_evidence", "")
    fix_hint = verdict.get("fix_hint", "")

    heading = _VERDICT_HEADING.get(v, "Analysis Complete")
    confidence_badge = f"**Confidence**: {confidence}"

    parts = [f"## {heading}", "", confidence_badge, "", explanation]

    if code_evidence:
        parts += [
            "",
            "**Code evidence:**",
            "```",
            code_evidence,
            "```",
        ]

    if fix_hint:
        parts += ["", "**Fix hint:**", fix_hint]

    # Call to action based on verdict
    if v == "confirmed_bug" and confidence in ("high", "medium"):
        parts += [
            "",
            "The bug is present in the current code. To trigger an automated fix:",
            "",
            "> `@claude-bot fix this`",
        ]
    elif v == "version_mismatch":
        parts += [
            "",
            f"This was reported against version **{reported_version}** but the current "
            f"codebase is **{current_version}**. Please verify the issue still occurs on "
            "the latest version before requesting a fix.",
        ]
    elif v == "needs_more_info":
        parts += [
            "",
            "Please provide a BESS debug report (System Health → Download Debug Report) "
            "so the investigation can continue.",
        ]
    elif v == "confirmed_bug" and confidence == "low":
        parts += [
            "",
            "The evidence is weak — a human should review before triggering a fix. "
            "If you are confident the bug exists, comment `@claude-bot fix this`.",
        ]

    comment_body = "\n".join(parts) + bot_footer()
    issue.create_comment(comment_body)

    # Apply labels based on verdict
    label = _VERDICT_LABELS.get(v, "question")
    current_labels = {lbl.name for lbl in issue.labels}
    if label not in current_labels:
        issue.add_to_labels(label)
    if "bot-analyzed" not in current_labels:
        issue.add_to_labels("bot-analyzed")

    print(f"Confirmation comment posted. Verdict: {v} ({confidence})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
