"""Claude PR Reviewer.

Posts a review comment on a pull request as the claude-reviewer[bot].

GitHub Actions usage (env vars set by claude-bot.yml):
    python scripts/pr_reviewer.py

CLI usage (from within the repo directory):
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/pr_reviewer.py --pr 42
    GITHUB_TOKEN=... ANTHROPIC_API_KEY=... python scripts/pr_reviewer.py --pr 42 --repo owner/repo
"""

import argparse
import os
import re
import sys

import anthropic
from github import Github


def extract_command(comment_body: str) -> str:
    match = re.search(r"@claude-bot\s+(.*)", comment_body, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return "review this pull request"


def get_pr_diff(pull) -> str:
    parts = []
    for f in pull.get_files():
        parts.append(f"--- a/{f.filename}\n+++ b/{f.filename}")
        parts.append(f.patch if f.patch else f"(binary or empty, status: {f.status})")
    return "\n".join(parts)


def get_existing_comments(pull) -> str:
    parts = []
    for comment in pull.get_issue_comments():
        parts.append(f"[{comment.user.login}]: {comment.body}")
    for review in pull.get_reviews():
        if review.body:
            parts.append(f"[{review.user.login} review]: {review.body}")
    for comment in pull.get_review_comments():
        parts.append(f"[{comment.user.login} on {comment.path}]: {comment.body}")
    return "\n\n".join(parts)


def read_file_if_exists(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path) as f:
        return f.read()


def build_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("REPO_FULL_NAME", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude PR Reviewer")
    parser.add_argument("--pr", type=int, help="PR number (CLI mode)")
    parser.add_argument(
        "--repo", help="owner/repo (CLI mode; defaults to REPO_FULL_NAME env var)"
    )
    parser.add_argument(
        "--command", default="review this pull request", help="Review command"
    )
    args = parser.parse_args()

    github_token = os.environ["GITHUB_TOKEN"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    repo_full_name = args.repo or os.environ["REPO_FULL_NAME"]

    if args.pr:
        # CLI mode
        pr_number = args.pr
        command = args.command
        repo_root = os.getcwd()
    else:
        # GitHub Actions mode
        pr_number = int(os.environ["PR_NUMBER"])
        command = extract_command(os.environ["COMMENT_BODY"])
        repo_root = os.getcwd()

    print(f"Reviewing PR #{pr_number} in {repo_full_name}")
    print(f"Command: {command}")

    gh = Github(github_token)
    repo = gh.get_repo(repo_full_name)
    pull = repo.get_pull(pr_number)

    diff = get_pr_diff(pull)
    existing_comments = get_existing_comments(pull)
    claude_md = read_file_if_exists(os.path.join(repo_root, "CLAUDE.md"))
    bot_config = read_file_if_exists(
        os.path.join(repo_root, ".github", "claude-bot.md")
    )

    system_parts = [
        "You are claude-bot, a code review bot. Provide focused, actionable feedback.",
        "Format your response in Markdown. Be concise but thorough on issues that matter.",
    ]
    if bot_config:
        system_parts.append(
            f"\nReview configuration — always apply these checks:\n\n<review_config>\n{bot_config}\n</review_config>"
        )
    if claude_md:
        system_parts.append(
            f"\nThis repository's coding guidelines (CLAUDE.md):\n\n<claude_md>\n{claude_md}\n</claude_md>"
        )
    system_prompt = "\n".join(system_parts)

    user_parts = [
        f"## PR #{pr_number}: {pull.title}",
        f"**Branch**: `{pull.head.ref}` → `{pull.base.ref}`",
        f"**Description**: {pull.body or '(none)'}",
        "",
        "## Changed files",
        "```diff",
        diff or "(no diff available)",
        "```",
    ]
    if existing_comments:
        user_parts += ["", "## Existing discussion", existing_comments]
    user_parts += ["", "## Your task", command]

    print("Calling Claude API...")
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": "\n".join(user_parts)}],
    )

    review_text = response.content[0].text
    run_url = build_run_url()
    footer = f"\n\n---\n*Review by claude-reviewer bot{' · [View run](' + run_url + ')' if run_url else ''}*"
    pull.create_issue_comment(review_text + footer)
    print(f"Comment posted ({len(review_text)} chars).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
