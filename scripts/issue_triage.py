"""Claude Issue Triage Agent.

Runs automatically when a new issue is created or when a user provides
a debug log on an issue that is waiting for one.

Responsibilities:
- Classify the issue (bug / feature / question / other)
- Apply appropriate GitHub labels
- For bugs without debug info: request a BESS debug export
- For bugs with debug info: perform initial root-cause analysis (using any
  attached debug logs, screenshots, or source code context)
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
import base64
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
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
3. Attach the downloaded `.md` file to a comment here (drag-and-drop onto the text area)

Screenshots of the UI showing the problem are also very helpful — attach those too.

The debug report contains schedule, sensor readings, price data, and recent \
error logs — everything needed to reproduce and diagnose the issue without \
requiring access to your installation.
"""

FEATURE_ACKNOWLEDGEMENT = """\
Thanks for the suggestion! I've tagged this as an enhancement for tracking.

If you can share a bit more about your use case (what you're trying to achieve \
and why the current behaviour doesn't work for you), that helps with prioritisation.
"""

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "not",
    "but",
    "when",
    "have",
    "been",
    "does",
    "after",
    "than",
    "also",
    "can",
    "will",
    "should",
    "would",
    "could",
    "into",
    "there",
    "they",
    "their",
    "which",
    "some",
    "more",
    "its",
}

# Matches both [text](url) and ![alt](url) for any GitHub user-attachment URL
# Covers /assets/ (images) and /files/ (uploaded documents)
_ATTACHMENT_RE = re.compile(
    r"!?\[([^\]]*)\]\((https://github\.com/user-attachments/(?:assets|files)/[^)]+)\)"
)

_IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


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
# Attachment fetching
# ---------------------------------------------------------------------------


def extract_attachment_urls(text: str) -> list[str]:
    """Return all GitHub user-attachment URLs found in markdown text."""
    return [url for _, url in _ATTACHMENT_RE.findall(text or "")]


class Attachment:
    """A fetched attachment — either text or an image."""

    def __init__(self, url: str, content_type: str, data: bytes) -> None:
        self.url = url
        self.content_type = content_type
        self.data = data

    @property
    def is_image(self) -> bool:
        return self.content_type.split(";")[0].strip() in _IMAGE_MEDIA_TYPES

    @property
    def as_text(self) -> str:
        return self.data.decode("utf-8", errors="replace")

    def as_claude_image_block(self) -> dict:
        media_type = self.content_type.split(";")[0].strip()
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(self.data).decode(),
            },
        }


def fetch_attachment(url: str, max_bytes: int = 200_000) -> Attachment | None:
    """Download a GitHub attachment and return an Attachment object, or None on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bess-triage-bot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            data = resp.read(max_bytes)
        return Attachment(url, content_type, data)
    except urllib.error.URLError as e:
        print(f"  Could not fetch attachment {url}: {e}")
        return None


def collect_attachments(texts: list[str]) -> list[Attachment]:
    """Fetch all unique GitHub attachments referenced in the given texts."""
    seen: set[str] = set()
    attachments: list[Attachment] = []
    for text in texts:
        for url in extract_attachment_urls(text):
            if url in seen:
                continue
            seen.add(url)
            print(f"  Fetching attachment: {url}")
            att = fetch_attachment(url)
            if att:
                attachments.append(att)
    return attachments


# ---------------------------------------------------------------------------
# Repo keyword grep
# ---------------------------------------------------------------------------


def extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", text or "")
    seen: dict[str, int] = {}
    for w in words:
        lw = w.lower()
        if lw not in _STOP_WORDS:
            seen[lw] = seen.get(lw, 0) + 1
    return [w for w, _ in sorted(seen.items(), key=lambda x: -x[1])[:12]]


def grep_repo(repo_root: str, keywords: list[str], max_lines: int = 80) -> str:
    if not keywords:
        return ""
    pattern = "|".join(re.escape(k) for k in keywords[:8])
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "-E", pattern, "--", "core/bess", "backend"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"... (truncated at {max_lines} lines)")
    return "\n".join(lines)


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
# Prompt construction (shared)
# ---------------------------------------------------------------------------


def build_user_content(
    issue_title: str,
    issue_body: str,
    attachments: list[Attachment],
    source_excerpts: str,
    closing_instruction: str = "",
) -> list[dict]:
    """Build a Claude multimodal content list from issue data and attachments."""
    parts: list[str] = [
        f"## Issue: {issue_title}",
        "",
        issue_body or "(no description provided)",
    ]

    text_logs = [a for a in attachments if not a.is_image]
    images = [a for a in attachments if a.is_image]

    for att in text_logs:
        parts += [
            "",
            f"## Attached file ({att.url.split('/')[-1]})",
            "```",
            att.as_text[:20_000],
            "```",
        ]

    if source_excerpts:
        parts += ["", "## Relevant Source Excerpts", "```", source_excerpts, "```"]

    if closing_instruction:
        parts += ["", closing_instruction]

    content: list[dict] = [{"type": "text", "text": "\n".join(parts)}]

    for img in images:
        content.append({"type": "text", "text": "## Screenshot"})
        content.append(img.as_claude_image_block())

    return content


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
                    "True if the issue has a BESS debug log (inline or attached), "
                    "a screenshot, or sufficient technical detail to begin diagnosis"
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
                    "For bugs with debug info: specific root-cause hypothesis naming "
                    "the file, function, and condition, with evidence quotes. "
                    "For other types: empty string."
                ),
            },
        },
        "required": ["type", "has_debug_info", "confidence", "summary"],
    },
}

_ANALYSIS_SYSTEM = """\
You are an expert BESS (Battery Energy Storage System) support engineer and Python developer.
Analyse this bug report. Debug logs, screenshots, and relevant source file excerpts may be provided.

When diagnostic material is available your response MUST:
1. Name the exact file and function where the bug most likely occurs.
2. Quote specific evidence from the debug log or source that supports your hypothesis \
(use inline code or a short block quote).
3. Describe the exact condition that triggers the bug \
(e.g. "after midnight, `current_period` wraps to 0 before `schedule_store` is cleared").
4. Propose a concrete fix sketch — the actual change needed, not just a direction.

Do NOT paraphrase the issue description. Focus on root cause, evidence, and fix.
Format your response in Markdown. Keep it under 500 words.\
"""


def triage_with_claude(
    client: anthropic.Anthropic,
    issue_title: str,
    issue_body: str,
    rules_md: str,
    arch_md: str,
    attachments: list[Attachment],
    source_excerpts: str,
) -> dict:
    system = "\n\n".join(
        filter(
            None,
            [
                "You are an expert BESS (Battery Energy Storage System) support engineer.",
                "Your job is to triage GitHub issues for the bess-manager project.",
                "Classify issues accurately. If a debug log, screenshot, or source context "
                "is provided, use it to form a specific root-cause hypothesis.",
                f"<rules>\n{rules_md}\n</rules>" if rules_md else "",
                f"<architecture>\n{arch_md}\n</architecture>" if arch_md else "",
            ],
        )
    )

    user_content = build_user_content(
        issue_title, issue_body, attachments, source_excerpts
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=system,
        tools=[TRIAGE_SCHEMA],
        tool_choice={"type": "tool", "name": "triage_result"},
        messages=[{"role": "user", "content": user_content}],
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
    attachments: list[Attachment],
    source_excerpts: str,
) -> str:
    system = "\n\n".join(
        filter(
            None,
            [
                _ANALYSIS_SYSTEM,
                f"<rules>\n{rules_md}\n</rules>" if rules_md else "",
                f"<architecture>\n{arch_md}\n</architecture>" if arch_md else "",
            ],
        )
    )

    user_content = build_user_content(
        issue_title,
        issue_body,
        attachments,
        source_excerpts,
        closing_instruction="Identify the root cause as described in your instructions.",
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_content}],
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

    def build_context(extra_texts: list[str]) -> tuple[list[Attachment], str]:
        texts = [issue.body or "", *extra_texts]
        attachments = collect_attachments(texts)
        keywords = extract_keywords(f"{issue.title} {issue.body or ''}")
        print(f"  Keywords: {keywords}")
        source_excerpts = grep_repo(repo_root, keywords)
        return attachments, source_excerpts

    # -----------------------------------------------------------------------
    # Mode: analyze_log — user has provided debug data in a comment
    # -----------------------------------------------------------------------
    if mode == "analyze_log":
        print("Running debug log analysis...")
        comment_body = os.environ.get("COMMENT_BODY", "")
        attachments, source_excerpts = build_context([comment_body])

        analysis = analyze_debug_log(
            client,
            issue.title,
            issue.body or "",
            rules_md,
            arch_md,
            attachments,
            source_excerpts,
        )
        comment = "\n".join(
            [
                "## Debug Log Analysis",
                "",
                analysis,
                "",
                "If this looks correct, trigger an automated fix with:",
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
    attachments, source_excerpts = build_context([])
    has_attachments = bool(attachments)

    result = triage_with_claude(
        client,
        issue.title,
        issue.body or "",
        rules_md,
        arch_md,
        attachments,
        source_excerpts,
    )
    print(
        f"Classification: type={result['type']} has_debug_info={result.get('has_debug_info')}"
    )

    issue_type = result["type"]
    has_debug_info = result.get("has_debug_info", False) or has_attachments
    initial_analysis = result.get("initial_analysis", "")

    if issue_type == "bug":
        if has_debug_info:
            analysis = initial_analysis or analyze_debug_log(
                client,
                issue.title,
                issue.body or "",
                rules_md,
                arch_md,
                attachments,
                source_excerpts,
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
            issue.create_comment(DEBUG_LOG_REQUEST + bot_footer())
            apply_labels(issue, add=["bug", "needs-debug-log"])

    elif issue_type == "feature":
        issue.create_comment(FEATURE_ACKNOWLEDGEMENT + bot_footer())
        apply_labels(issue, add=["enhancement"])

    else:
        apply_labels(issue, add=["question"])

    print(f"Triage complete: {issue_type}, has_debug_info={has_debug_info}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
