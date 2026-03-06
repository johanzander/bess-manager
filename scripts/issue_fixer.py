"""Claude Issue Fixer.

Reads a GitHub issue, explores the codebase via tool use, implements a fix,
commits to a new branch, and opens a draft PR — all as the claude-reviewer[bot].

GitHub Actions usage (env vars set by claude-bot.yml):
    python scripts/issue_fixer.py

CLI usage (from within the repo directory):
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/issue_fixer.py --issue 15
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/issue_fixer.py --issue 15 --repo owner/repo
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import anthropic
from github import Github

# ---------------------------------------------------------------------------
# Tools available to Claude during the agentic fix loop
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
            "Returns matching lines with file paths and line numbers."
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
        "name": "write_file",
        "description": "Write or overwrite a file. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from the repo root",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
]


def handle_tool(name: str, inputs: dict, repo_root: str, written_files: dict) -> str:
    if name == "read_file":
        full = Path(repo_root) / inputs["path"]
        if not full.exists():
            return f"ERROR: file not found: {inputs['path']}"
        text = full.read_text(errors="replace")
        # Cap at 8000 chars to stay within context
        if len(text) > 8000:
            text = text[:8000] + f"\n... (truncated, {len(text)} chars total)"
        return text

    if name == "list_directory":
        rel_path = inputs.get("path", ".")
        full = Path(repo_root) / rel_path
        if not full.exists():
            return f"ERROR: directory not found: {rel_path}"
        items = sorted(full.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = []
        for item in items:
            if item.name.startswith(".") and item.name not in (".github",):
                continue  # skip hidden except .github
            suffix = "/" if item.is_dir() else ""
            lines.append(f"{item.name}{suffix}")
        return "\n".join(lines) if lines else "(empty)"

    if name == "search_files":
        pattern = inputs["pattern"]
        file_glob = inputs.get("file_glob", "")
        results = []
        search_root = Path(repo_root)
        glob_pattern = f"**/{file_glob}" if file_glob else "**/*"
        for path in search_root.glob(glob_pattern):
            if not path.is_file():
                continue
            # Skip binary-ish and cache dirs
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
        return "\n".join(results) if results else "No matches found."

    if name == "write_file":
        rel_path = inputs["path"]
        content = inputs["content"]
        full = Path(repo_root) / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        written_files[rel_path] = content
        return f"Written: {rel_path}"

    return f"ERROR: unknown tool: {name}"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def git(args: list, cwd: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def push_branch(
    branch: str, repo_root: str, github_token: str, repo_full_name: str
) -> None:
    remote = f"https://x-access-token:{github_token}@github.com/{repo_full_name}.git"
    git(["push", remote, branch], cwd=repo_root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_command(comment_body: str) -> str:
    match = re.search(r"@claude-bot\s+(.*)", comment_body, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return "fix this issue"


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


def slugify(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].rstrip("-")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Issue Fixer")
    parser.add_argument("--issue", type=int, help="Issue number (CLI mode)")
    parser.add_argument("--repo", help="owner/repo (CLI mode)")
    parser.add_argument("--command", default="", help="Override command (CLI mode)")
    args = parser.parse_args()

    github_token = os.environ["GITHUB_TOKEN"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    repo_full_name = args.repo or os.environ["REPO_FULL_NAME"]
    repo_root = os.getcwd()

    if args.issue:
        issue_number = args.issue
        command = args.command or "fix this issue"
    else:
        issue_number = int(os.environ["ISSUE_NUMBER"])
        command = extract_command(os.environ["COMMENT_BODY"])

    print(f"Fixing issue #{issue_number} in {repo_full_name}")
    print(f"Command: {command}")

    gh = Github(github_token)
    gh_repo = gh.get_repo(repo_full_name)
    issue = gh_repo.get_issue(issue_number)

    claude_md = read_file_if_exists(Path(repo_root) / "CLAUDE.md")

    system_parts = [
        "You are claude-fixer, an autonomous software engineer bot.",
        "Your job is to implement a fix for a GitHub issue by reading the codebase,",
        "understanding the problem, and making targeted, minimal code changes.",
        "Follow the project's coding guidelines exactly.",
        "Use the available tools to explore and modify the repository.",
        "When you are done making changes, stop calling tools and write a clear",
        "summary of what you changed and why, in Markdown.",
    ]
    if claude_md:
        system_parts.append(
            f"\nThis repository's coding guidelines (CLAUDE.md):\n\n<claude_md>\n{claude_md}\n</claude_md>"
        )
    system_prompt = "\n".join(system_parts)

    user_message = "\n".join(
        [
            f"## Issue #{issue_number}: {issue.title}",
            "",
            "**Description:**",
            issue.body or "(no description)",
            "",
            "**Labels:** " + ", ".join(lbl.name for lbl in issue.labels)
            if issue.labels
            else "",
            "",
            "## Your task",
            command,
            "",
            "Start by reading CLAUDE.md (if present) and listing the top-level directory to",
            "understand the codebase structure. Then read relevant files and implement the fix.",
            "Make only the changes necessary to resolve the issue.",
        ]
    )

    # Agentic tool-use loop
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    messages = [{"role": "user", "content": user_message}]
    written_files: dict = {}
    summary = ""

    print("Starting agentic fix loop...")
    for iteration in range(20):  # hard cap to prevent runaway loops
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8192,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Extract the final text summary
            for block in response.content:
                if hasattr(block, "text"):
                    summary = block.text
                    break
            print(f"Agent finished after {iteration + 1} iterations.")
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  Tool call: {block.name}({list(block.input.keys())})")
                    result = handle_tool(
                        block.name, block.input, repo_root, written_files
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result)[:4000],  # cap per result
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"Unexpected stop_reason: {response.stop_reason}")
            break
    else:
        print("WARNING: reached iteration cap.")

    if not written_files:
        # Claude analysed but made no changes — post the analysis as a comment
        print("No files written. Posting analysis comment.")
        run_url = build_run_url()
        footer = f"\n\n---\n*Analysis by claude-fixer bot{' · [View run](' + run_url + ')' if run_url else ''}*"
        issue.create_comment(
            (summary or "I analysed this issue but did not make any code changes.")
            + footer
        )
        return

    # Commit the changes
    branch_name = f"fix/issue-{issue_number}-{slugify(issue.title)}"
    print(f"Committing {len(written_files)} file(s) to branch: {branch_name}")

    git(["config", "user.name", "claude-reviewer[bot]"], cwd=repo_root)
    git(
        ["config", "user.email", "claude-reviewer[bot]@users.noreply.github.com"],
        cwd=repo_root,
    )
    git(["checkout", "-b", branch_name], cwd=repo_root)
    git(["add", "-A"], cwd=repo_root)

    commit_message = f"Fix #{issue_number}: {issue.title}"
    git(["commit", "-m", commit_message], cwd=repo_root)

    push_branch(branch_name, repo_root, github_token, repo_full_name)
    print("Branch pushed.")

    # Open draft PR
    pr_body = "\n".join(
        [
            f"Fixes #{issue_number}",
            "",
            "## Changes",
            summary or "See commits for details.",
            "",
            "## Files modified",
            "\n".join(f"- `{p}`" for p in sorted(written_files)),
            "",
            "---",
            f"*Implemented by claude-fixer bot{' · [View run](' + build_run_url() + ')' if build_run_url() else ''}*",
        ]
    )

    pr = gh_repo.create_pull(
        title=f"Fix #{issue_number}: {issue.title}",
        body=pr_body,
        head=branch_name,
        base=gh_repo.default_branch,
        draft=True,
    )
    print(f"Draft PR created: {pr.html_url}")

    # Post a link on the issue
    issue.create_comment(
        f"I've implemented a fix and opened a draft PR: {pr.html_url}\n\n"
        f"Please review before merging."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
