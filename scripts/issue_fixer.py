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
import smtplib
import subprocess
import sys
from email.mime.text import MIMEText
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
    {
        "name": "run_tests",
        "description": (
            "Run the project test suite (pytest) and return the output. "
            "Call this after writing all fixes to verify nothing is broken. "
            "If tests fail, read the failing tests, fix the code, and run again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Optional: path to a specific test file or directory. "
                        "Defaults to running the full suite."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_lint",
        "description": (
            "Run black (formatter) and ruff (linter) on the repository. "
            "black auto-fixes formatting; ruff --fix auto-fixes safe issues. "
            "Call this after run_tests passes. If ruff reports remaining errors, "
            "read the output and fix them manually."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "finish",
        "description": (
            "Signal that you are done. Call this when: (a) you have written all fixes "
            "and tests+lint pass, OR (b) you investigated but determined no code change "
            "is needed. Provide a summary of what you did and why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "Markdown summary of changes made (or explanation of why no "
                        "changes were made). Be specific: list files modified and what changed."
                    ),
                },
                "changed": {
                    "type": "boolean",
                    "description": "True if you wrote any code changes, False otherwise.",
                },
            },
            "required": ["summary", "changed"],
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

    if name == "run_tests":
        test_path = inputs.get("path", "")
        cmd = ["python", "-m", "pytest", "--tb=short", "-q"]
        if test_path:
            cmd.append(test_path)
        result = subprocess.run(
            cmd, cwd=repo_root, capture_output=True, text=True, timeout=120
        )
        output = result.stdout + result.stderr
        if len(output) > 6000:
            output = output[-6000:] + "\n... (truncated, showing last 6000 chars)"
        status = "PASSED" if result.returncode == 0 else "FAILED"
        return f"Tests {status} (exit code {result.returncode}):\n\n{output}"

    if name == "run_lint":
        return _run_lint(repo_root)

    return f"ERROR: unknown tool: {name}"


def _run_lint(repo_root: str) -> str:
    lines = []
    # black auto-formats in place
    r = subprocess.run(
        ["black", "--quiet", "."], cwd=repo_root, capture_output=True, text=True
    )
    if r.stdout or r.stderr:
        lines.append(f"black:\n{(r.stdout + r.stderr).strip()}")
    else:
        lines.append("black: OK (no changes needed)")

    # ruff --fix applies safe auto-fixes
    subprocess.run(
        ["ruff", "check", "--fix", "--quiet", "."],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    # ruff check (no fix) reports what remains
    r2 = subprocess.run(
        ["ruff", "check", "."], cwd=repo_root, capture_output=True, text=True
    )
    if r2.returncode == 0:
        lines.append("ruff: OK")
    else:
        output = (r2.stdout + r2.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n... (truncated)"
        lines.append(f"ruff ERRORS (fix these):\n{output}")

    passed = r2.returncode == 0
    status = "PASSED" if passed else "FAILED"
    return f"Lint {status}\n\n" + "\n\n".join(lines)


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


def notify_email(
    to_addr: str,
    smtp_password: str,
    pr_url: str,
    issue_number: int,
    title: str,
    test_status: str,
    lint_status: str,
) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("SMTP_FROM", to_addr)

    body = (
        f"Draft PR ready for your review\n\n"
        f"Issue #{issue_number}: {title}\n"
        f"Tests: {test_status}\n"
        f"Lint:  {lint_status}\n\n"
        f"{pr_url}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"[bess-manager] PR ready: Fix #{issue_number}: {title}"
    msg["From"] = from_addr
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.starttls()
            smtp.login(from_addr, smtp_password)
            smtp.sendmail(from_addr, to_addr, msg.as_string())
        print(f"Email notification sent to {to_addr}.")
    except Exception as e:
        print(f"Email notification failed (non-fatal): {e}")


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

    rules_md = read_file_if_exists(Path(repo_root) / "docs/agents/rules.md")
    arch_md = read_file_if_exists(Path(repo_root) / "docs/agents/architecture.md")
    patterns_md = read_file_if_exists(Path(repo_root) / "docs/agents/patterns.md")

    system_parts = [
        "You are claude-fixer, an autonomous software engineer bot.",
        "Your job is to implement a fix for a GitHub issue by reading the codebase,",
        "understanding the problem, and making targeted, minimal code changes.",
        "Use the available tools to explore and modify the repository.",
        "After writing all changes: (1) call run_tests, fix any failures;",
        "(2) call run_lint, fix any ruff errors (black auto-formats for you).",
        "When both pass, call finish() with a Markdown summary of what you changed and why.",
        "If you investigated and determined no change is needed, call finish(changed=False).",
        "You MUST call finish() to end your session — do not stop without calling it.",
    ]
    if rules_md:
        system_parts.append(f"\n<hard_constraints>\n{rules_md}\n</hard_constraints>")
    if arch_md:
        system_parts.append(
            f"\n<architecture_reference>\n{arch_md}\n</architecture_reference>"
        )
    if patterns_md:
        system_parts.append(f"\n<code_patterns>\n{patterns_md}\n</code_patterns>")
    system_prompt = "\n".join(system_parts)

    user_message = "\n".join(
        [
            f"## Issue #{issue_number}: {issue.title}",
            "",
            "**Description:**",
            issue.body or "(no description)",
            "",
            (
                "**Labels:** " + ", ".join(lbl.name for lbl in issue.labels)
                if issue.labels
                else ""
            ),
            "",
            "## Your task",
            command,
            "",
            "Start by listing the top-level directory to understand the codebase structure.",
            "Read docs/agents/architecture.md for component overview and key file locations.",
            "Then read the relevant source files and implement the minimal fix.",
            "After writing changes: call run_tests (fix failures), then call run_lint (fix ruff errors).",
        ]
    )

    # Agentic tool-use loop
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    messages = [{"role": "user", "content": user_message}]
    written_files: dict = {}
    summary = ""
    tests_passed: bool | None = None
    lint_passed: bool | None = None

    print("Starting agentic fix loop...")
    done = False
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

            if block.name == "finish":
                summary = block.input.get("summary", "")
                done = True
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": "Done."}
                )
                break

            result = handle_tool(block.name, block.input, repo_root, written_files)
            if block.name == "run_tests":
                tests_passed = "Tests PASSED" in str(result)
            if block.name == "run_lint":
                lint_passed = "Lint PASSED" in str(result)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result)[:4000],
                }
            )

        if done:
            print(f"Agent called finish after {_iteration + 1} iterations.")
            break
        messages.append({"role": "user", "content": tool_results})
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

    # Always auto-format before committing, even if the agent already ran lint.
    # This is the final gate — prevents any formatting drift from reaching the PR.
    print("Running pre-commit quality gate...")
    lint_result = _run_lint(repo_root)
    print(lint_result)
    if lint_passed is None:
        lint_passed = "Lint PASSED" in lint_result

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
    test_status = (
        "✅ Tests passed"
        if tests_passed is True
        else (
            "⚠️ Tests failed — review required"
            if tests_passed is False
            else "⚪ Not run"
        )
    )
    lint_status = (
        "✅ Lint passed"
        if lint_passed is True
        else (
            "⚠️ Lint errors remain — review required"
            if lint_passed is False
            else "⚪ Not run"
        )
    )

    pr_body = "\n".join(
        [
            f"Fixes #{issue_number}",
            "",
            f"**Tests**: {test_status} | **Lint**: {lint_status}",
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

    # Assign the repo owner so GitHub sends a native notification email.
    try:
        pr.add_to_assignees(gh_repo.owner.login)
    except Exception as e:
        print(f"Could not assign PR (non-fatal): {e}")

    # Optional email notification.
    notification_email = os.environ.get("NOTIFICATION_EMAIL", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    if notification_email and smtp_password:
        notify_email(
            notification_email,
            smtp_password,
            pr.html_url,
            issue_number,
            issue.title,
            test_status,
            lint_status,
        )

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
