"""AI Analyst chat service for in-app BESS analysis.

Provides a streaming chat interface backed by the Claude API.  The system prompt
combines a chat-specific preamble with shared domain knowledge from
docs/agents/bess-knowledge.md and live system context.

The AI has tool-use capabilities: it can read source files, search the codebase,
and list directories — giving it full access to its own code for deep analysis.
"""

import fnmatch
import json
import logging
import re
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# In Docker the layout is /app/{*.py, core/, agents/}.
# In local dev it's <repo>/{backend/, core/, .claude/agents/}.
_APP_DIR = Path(__file__).resolve().parent

# Codebase root: the directory that contains core/ and backend/.
_CODEBASE_ROOT = _APP_DIR  # Docker: /app/
if not (_CODEBASE_ROOT / "core" / "bess").exists():
    _CODEBASE_ROOT = _APP_DIR.parent  # Local dev: repo root

# Domain knowledge file — mounted at the same path in dev and prod.
_KNOWLEDGE_MD_PATH = _APP_DIR / "agents" / "bess-knowledge.md"

# Directories the AI is allowed to read (relative to _CODEBASE_ROOT).
_ALLOWED_DIRS = ("core/", "backend/", "docs/", "scripts/", ".claude/agents/")

# Files/patterns the AI must NOT read (secrets, settings with keys).
_BLOCKED_PATTERNS = (
    "*.env",
    "*bess_settings.json",
    "*options.json",
    "*credentials*",
    "*secret*",
)

# ---------------------------------------------------------------------------
# Tool definitions (Claude API format)
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a source file from the BESS Manager codebase.  Returns the "
            "file contents with line numbers.  For large files, use start_line "
            "and end_line to read a specific range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path from the project root, e.g. "
                        "'core/bess/dp_battery_algorithm.py' or 'backend/api.py'."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-based).  Omit to start from line 1.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-based).  Omit to read to end of file.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search the BESS Manager codebase for a regex pattern.  Returns "
            "matching lines with file paths and line numbers.  Use to find "
            "functions, variables, error messages, or trace code paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for, e.g. 'cost_basis' or 'def optimize_.*schedule'.",
                },
                "file_glob": {
                    "type": "string",
                    "description": "Optional glob to filter files, e.g. '*.py' or 'core/bess/*.py'.  Default: '*.py'.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "List source files in a directory of the BESS Manager codebase.  "
            "Returns file names with sizes.  Useful for understanding project "
            "structure before reading specific files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative directory path, e.g. 'core/bess/' or 'backend/'.  "
                        "Omit or use '' for the project root."
                    ),
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

_MAX_TOOL_ITERATIONS = 20
_MAX_FILE_READ_LINES = 500
_MAX_SEARCH_RESULTS = 50
_MAX_TOOL_RESULT_CHARS = 200_000

# Preamble prepended to the agent definition to adapt it for in-app use.
_PREAMBLE = """\
You are an AI analyst embedded in the BESS Manager web UI.  The user is a
home owner looking at their battery dashboard.  They ask you questions about
performance, optimization decisions, savings, and configuration.

You have THREE sources of information:

1. **Domain knowledge** — provided below (how the system works, key source
   files, how savings are calculated).
2. **Live system state** — tables of current sensor data, schedules,
   prediction snapshots, and logs (in "Current System State" below).
3. **Source code access** — you have tools to read any source file, search
   the codebase, and list directories.

## How you MUST respond

**Style:**
- Write flowing prose, not bullet lists.  Use short paragraphs.
- Be concise — get straight to the answer.  Do not restate what the user
  already said or knows.  Do not add preamble like "Let me check..." or
  "Looking at the data..." — just state your findings.
- Do NOT use markdown headings (##, ###).
- Use human-friendly language.  Say "at 13:00" not "period 52".  The user
  is not a developer — never expose period indices, class names, or
  internal data structures.  Do not name tables or data sources — just
  state the facts.
- Do NOT suggest the user look at code or run commands.  YOU read code on
  their behalf using tools.
- Use the currency from the system settings for monetary values.

**Analysis — EVERY claim must have evidence:**
- Before stating any cause or explanation, you MUST point to the specific
  evidence: a row in the data tables, a log line, or a line of source code.
  If you cannot cite evidence, do not make the claim.
- NEVER use "likely", "probably", "suggests", "may have", "possibly", or
  "could have".  Either state what happened with evidence, or say "I don't
  have enough data to determine the cause."
- When analyzing savings changes:
  1. Find the exact timestamps in Prediction Snapshots where savings changed.
  2. For each significant change, check the data to find the cause:
     - Check if tomorrow's prices appeared (price data, logs).
     - Compare Historical Data vs Schedule for the same time to find
       solar or consumption differences.
     - Check if Predicted Count changed (horizon expansion).
  3. Report ONLY what the data shows, with specific numbers.

  Good: "At 13:00, tomorrow's prices became available.  The optimizer
  shifted 15 SEK of discharge value to tomorrow where evening prices are
  0.50 SEK/kWh higher."

  Bad: "The optimizer likely received updated data that made it recalculate
  profitability."  (This says nothing — what data?  What changed?)

- If the data is insufficient, say so rather than inventing an explanation.

---

"""

# Session expiry: 2 hours of inactivity.
_SESSION_TTL_SECONDS = 2 * 60 * 60

# Maximum conversation pairs to keep (sliding window).
_MAX_MESSAGE_PAIRS = 20

# Conservative token estimate: ~4 chars per token.
_CHARS_PER_TOKEN = 4

# Maximum characters for the system context.
_MAX_CONTEXT_CHARS = 600_000


@dataclass
class ChatSession:
    """In-memory chat session state."""

    session_id: str
    messages: list[dict] = field(default_factory=list)
    system_context: str = ""
    context_summary: str = ""
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


# ======================================================================
# Tool execution
# ======================================================================


def _resolve_and_validate_path(relative_path: str) -> Path | None:
    """Resolve a relative path and validate it's within the sandbox.

    Returns the resolved absolute Path, or None if access is denied.
    """
    # Normalize separators.
    cleaned = relative_path.replace("\\", "/")

    # Block absolute paths.
    if cleaned.startswith("/"):
        return None

    # Block obvious traversal attempts.
    if ".." in cleaned.split("/"):
        return None

    resolved = (_CODEBASE_ROOT / cleaned).resolve()

    # Must be under the codebase root.
    try:
        resolved.relative_to(_CODEBASE_ROOT.resolve())
    except ValueError:
        return None

    # Must be in an allowed directory (or be the root itself for listing).
    rel_str = str(resolved.relative_to(_CODEBASE_ROOT.resolve()))
    if resolved.is_file() or resolved.is_dir():
        if not any(rel_str.startswith(d.rstrip("/")) for d in _ALLOWED_DIRS):
            # Allow listing the root directory itself.
            if rel_str != ".":
                return None

    # Must not match blocked patterns.
    filename = resolved.name.lower()
    for pattern in _BLOCKED_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return None

    return resolved


def _tool_read_file(params: dict) -> str:
    """Read a source file, optionally a line range."""
    path_str = params.get("path", "")
    resolved = _resolve_and_validate_path(path_str)
    if resolved is None:
        return f"Error: Access denied for path '{path_str}'."
    if not resolved.is_file():
        return f"Error: File not found: '{path_str}'."

    try:
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return f"Error reading file: {e}"

    start = max(1, params.get("start_line", 1))
    end = params.get("end_line", len(lines))
    end = min(end, len(lines))

    # Cap the range.
    if end - start + 1 > _MAX_FILE_READ_LINES:
        end = start + _MAX_FILE_READ_LINES - 1
        truncated = True
    else:
        truncated = False

    numbered = [f"{i}: {lines[i - 1]}" for i in range(start, end + 1)]
    result = f"# {path_str} (lines {start}-{end} of {len(lines)})\n"
    result += "\n".join(numbered)
    if truncated:
        result += f"\n\n[Truncated — showing {_MAX_FILE_READ_LINES} lines. Use start_line/end_line to read more.]"
    return result


def _tool_search_code(params: dict) -> str:
    """Search the codebase using grep."""
    pattern = params.get("pattern", "")
    file_glob = params.get("file_glob", "*.py")

    if not pattern:
        return "Error: pattern is required."

    # Search only within allowed directories.
    search_dirs = []
    for d in _ALLOWED_DIRS:
        search_path = _CODEBASE_ROOT / d.rstrip("/")
        if search_path.is_dir():
            search_dirs.append(str(search_path))
    if not search_dirs:
        return "Error: No searchable directories found."

    # Use grep for search — available in both Docker (Alpine) and local dev.
    cmd = [
        "grep",
        "-rn",
        "--include",
        file_glob,
        "-E",
        pattern,
        *search_dirs,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "Error: Search timed out."
    except FileNotFoundError:
        return "Error: grep not available."

    if result.returncode not in (0, 1):
        return f"Error: Search failed: {result.stderr[:200]}"

    if not result.stdout.strip():
        return f"No matches found for pattern '{pattern}' in {file_glob}."

    # Convert absolute paths to relative and filter blocked files.
    root_str = str(_CODEBASE_ROOT.resolve())
    output_lines = []
    for line in result.stdout.splitlines():
        # Strip the codebase root prefix for cleaner output.
        if line.startswith(root_str):
            line = line[len(root_str) :].lstrip("/")

        # Skip blocked files and test directories in results.
        skip = False
        for bp in _BLOCKED_PATTERNS:
            if fnmatch.fnmatch(line.split(":")[0].split("/")[-1].lower(), bp):
                skip = True
                break
        if skip:
            continue

        output_lines.append(line)
        if len(output_lines) >= _MAX_SEARCH_RESULTS:
            output_lines.append(
                f"\n[Showing first {_MAX_SEARCH_RESULTS} matches — narrow your search pattern.]"
            )
            break

    return (
        "\n".join(output_lines)
        if output_lines
        else f"No accessible matches for '{pattern}'."
    )


def _tool_list_files(params: dict) -> str:
    """List files in a directory."""
    path_str = params.get("path", "")

    if not path_str:
        # List top-level directories.
        entries = []
        for d in sorted(_CODEBASE_ROOT.iterdir()):
            rel = d.name
            if d.is_dir() and any(
                rel.rstrip("/").startswith(a.rstrip("/")) for a in _ALLOWED_DIRS
            ):
                entries.append(f"  {rel}/")
            elif d.is_file() and d.suffix in (".py", ".md", ".yaml", ".yml", ".txt"):
                entries.append(f"  {rel} ({d.stat().st_size:,} bytes)")
        return (
            "Project root:\n" + "\n".join(entries)
            if entries
            else "No accessible files."
        )

    resolved = _resolve_and_validate_path(path_str)
    if resolved is None:
        return f"Error: Access denied for path '{path_str}'."
    if not resolved.is_dir():
        return f"Error: Not a directory: '{path_str}'."

    entries = []
    for item in sorted(resolved.iterdir()):
        rel_name = item.name
        if rel_name.startswith("__pycache__") or rel_name.startswith("."):
            continue
        if item.is_dir():
            entries.append(f"  {rel_name}/")
        elif item.is_file():
            entries.append(f"  {rel_name} ({item.stat().st_size:,} bytes)")

    return (
        f"{path_str}:\n" + "\n".join(entries)
        if entries
        else f"No files in '{path_str}'."
    )


def _execute_tool(name: str, tool_input: dict) -> str:
    """Dispatch a tool call and return the result string."""
    handlers = {
        "read_file": _tool_read_file,
        "search_code": _tool_search_code,
        "list_files": _tool_list_files,
    }
    handler = handlers.get(name)
    if handler is None:
        return f"Error: Unknown tool '{name}'."

    result = handler(tool_input)

    # Cap total result size.
    if len(result) > _MAX_TOOL_RESULT_CHARS:
        result = (
            result[:_MAX_TOOL_RESULT_CHARS]
            + "\n\n[... result truncated to fit token limit]"
        )
    return result


# ======================================================================
# Main service
# ======================================================================


class AIAnalystService:
    """Manages AI chat sessions and Claude API interactions."""

    def __init__(self, settings_store) -> None:
        self._settings_store = settings_store
        self._sessions: dict[str, ChatSession] = {}
        self._system_prompt_base: str = self._load_system_prompt()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return whether the AI analyst is configured and which model is active."""
        cfg = self._get_config()
        api_key = cfg.get("api_key", "")
        return {
            "configured": bool(api_key),
            "enabled": cfg.get("enabled", True),
            "model": cfg.get("model", "claude-sonnet-4-6"),
        }

    def start_session(self, system_manager) -> dict:
        """Create a new chat session with fresh system context.

        Args:
            system_manager: BatterySystemManager instance for context gathering.

        Returns:
            Dict with sessionId and contextSummary.
        """
        self._cleanup_expired()

        session_id = str(uuid.uuid4())
        context, summary = self._gather_context(system_manager)

        session = ChatSession(
            session_id=session_id,
            system_context=context,
            context_summary=summary,
        )
        self._sessions[session_id] = session
        logger.info("AI chat session started: %s", session_id)
        return {"sessionId": session_id, "contextSummary": summary}

    async def stream_response(
        self, session_id: str, user_message: str
    ) -> AsyncIterator[str]:
        """Stream an AI response as SSE events, with tool-use loop.

        The model may request tool calls (read_file, search_code, list_files).
        Each tool call is executed locally and the result sent back to the model.
        Text deltas are streamed to the frontend in real-time.  Tool activity
        is reported via ``tool_use`` SSE events.

        Args:
            session_id: Active session UUID.
            user_message: The user's question.

        Yields:
            SSE-formatted strings: ``data: {...}\\n\\n``
        """
        session = self._sessions.get(session_id)
        if session is None:
            yield _sse_event("error", {"error": "Session not found or expired."})
            return

        session.last_active = time.time()

        # Add user message to history.
        session.messages.append({"role": "user", "content": user_message})

        # Trim conversation if too long.
        self._trim_messages(session)

        cfg = self._get_config()
        api_key = cfg.get("api_key", "")
        if not api_key:
            yield _sse_event(
                "error",
                {"error": "API key not configured. Go to Settings > AI Analyst."},
            )
            return

        model = cfg.get("model", "claude-sonnet-4-6")
        system_prompt = self._build_full_system_prompt(session.system_context)

        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            final_text = ""

            for _iteration in range(_MAX_TOOL_ITERATIONS):
                # Stream the model response.
                text_so_far = ""
                response = None

                async with client.messages.stream(
                    model=model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=_TOOLS,
                    messages=session.messages,
                ) as stream:
                    # Stream text deltas to the frontend as they arrive.
                    async for event in stream:
                        if hasattr(event, "type"):
                            if event.type == "content_block_delta":
                                if hasattr(event.delta, "text"):
                                    text_so_far += event.delta.text
                                    yield _sse_event(
                                        "text_delta", {"text": event.delta.text}
                                    )

                    response = await stream.get_final_message()

                # Check for tool use blocks.
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                if not tool_use_blocks:
                    # No tools requested — this is the final answer.
                    final_text = text_so_far
                    break

                # Model wants to use tools.  Serialize the full response
                # (may contain both text and tool_use blocks) to messages.
                assistant_content = []
                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )
                session.messages.append(
                    {"role": "assistant", "content": assistant_content}
                )

                # Execute each tool and build results.
                tool_results = []
                for block in tool_use_blocks:
                    # Notify frontend about tool activity.
                    yield _sse_event(
                        "tool_use",
                        {"tool": block.name, "input": block.input},
                    )
                    logger.info(
                        "AI tool call: %s(%s)",
                        block.name,
                        json.dumps(block.input, default=str)[:200],
                    )

                    result_str = _execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        }
                    )

                session.messages.append({"role": "user", "content": tool_results})

            else:
                # Hit the iteration limit.
                yield _sse_event(
                    "text_delta",
                    {
                        "text": "\n\n*[Reached maximum tool call limit — "
                        "please refine your question.]*"
                    },
                )

            # Store the final text in a simplified form for conversation
            # history (collapse tool_use/tool_result pairs).
            if final_text:
                session.messages.append({"role": "assistant", "content": final_text})
            yield _sse_event("done", {})

        except anthropic.AuthenticationError:
            yield _sse_event(
                "error", {"error": "Invalid API key. Check Settings > AI Analyst."}
            )
        except anthropic.RateLimitError:
            yield _sse_event(
                "error",
                {
                    "error": "Rate limited by Claude API. Please wait a moment and try again."
                },
            )
        except anthropic.APIError as e:
            logger.error("Claude API error: %s", e)
            yield _sse_event("error", {"error": f"AI service error: {e.message}"})
        except Exception as e:
            logger.exception("Unexpected error in AI chat stream: %s", e)
            yield _sse_event("error", {"error": "An unexpected error occurred."})

    def refresh_context(self, session_id: str, system_manager) -> dict:
        """Re-gather system context for an existing session.

        Args:
            session_id: Active session UUID.
            system_manager: BatterySystemManager instance.

        Returns:
            Dict with contextSummary.

        Raises:
            KeyError: If session not found.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found or expired")

        context, summary = self._gather_context(system_manager)
        session.system_context = context
        session.context_summary = summary
        session.last_active = time.time()
        logger.info("AI chat context refreshed for session %s", session_id)
        return {"contextSummary": summary}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_config(self) -> dict:
        """Read the ai_analyst settings section."""
        return self._settings_store.get_section("ai_analyst")

    def _load_system_prompt(self) -> str:
        """Load the bess-knowledge.md domain knowledge file."""
        try:
            raw = _KNOWLEDGE_MD_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "bess-knowledge.md not found at %s — using minimal prompt",
                _KNOWLEDGE_MD_PATH,
            )
            return "You are a BESS (Battery Energy Storage System) analyst."

        # Strip YAML frontmatter if present (between --- markers at the start).
        stripped = re.sub(r"\A---\n.*?\n---\n*", "", raw, count=1, flags=re.DOTALL)
        return stripped.strip()

    def _build_full_system_prompt(self, context: str) -> list[dict]:
        """Combine preamble + domain knowledge + live context.

        Returns a list of content blocks for the ``system`` parameter.
        The static portion (preamble + bess-knowledge.md) is marked with
        cache_control for Anthropic prompt caching.
        """
        static = _PREAMBLE + self._system_prompt_base
        blocks = [
            {
                "type": "text",
                "text": static,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if context:
            blocks.append(
                {
                    "type": "text",
                    "text": "\n\n---\n\n# Current System State\n\n" + context,
                }
            )
        return blocks

    def _gather_context(self, system_manager) -> tuple[str, str]:
        """Build a token-efficient context from the debug export.

        The full DebugReportFormatter output is ~200K+ tokens (includes raw
        JSON dumps for file-based debugging).  For the chat context we only
        need the human-readable tables and small JSON blocks — no raw entity
        snapshots, no full schedule JSON, no full historical JSON.

        Returns:
            Tuple of (context_markdown, short_summary).
        """
        from core.bess.debug_data_exporter import DebugDataAggregator

        try:
            aggregator = DebugDataAggregator(
                system_manager,
                settings_data=self._settings_store.data,
            )
            export = aggregator.aggregate_all_data(compact=True)

            sections = []

            # System info (tiny)
            sections.append(
                f"## System\nVersion: {export.bess_version}, "
                f"Uptime: {export.system_uptime_hours:.1f}h, "
                f"TZ: {export.timezone}"
            )

            # Health status (small)
            checks = export.health_check_results.get("checks", [])
            errors = [c for c in checks if c.get("status") == "ERROR"]
            warnings = [c for c in checks if c.get("status") == "WARNING"]
            health_lines = [
                f"## Health: {len(errors)} errors, {len(warnings)} warnings"
            ]
            for c in errors + warnings:
                health_lines.append(
                    f"- **{c.get('status')}** {c.get('name', '?')}: {c.get('message', '')}"
                )
            sections.append("\n".join(health_lines))

            # Settings (small JSON blocks — battery, pricing, home)
            settings_parts = ["## Settings"]
            for label, data in [
                ("Battery", export.battery_settings),
                ("Pricing", export.price_settings),
                ("Home", export.home_settings),
            ]:
                settings_parts.append(
                    f"### {label}\n```json\n{json.dumps(data, indent=1, default=str)}\n```"
                )
            sections.append("\n\n".join(settings_parts))

            # Price data (can be large with 96 periods — include as compact JSON)
            if export.price_data:
                sections.append(
                    f"## Price Data\n```json\n{json.dumps(export.price_data, indent=1, default=str)}\n```"
                )

            # Entity snapshot — table only, no raw JSON
            if export.entity_snapshot:
                rows = [
                    "## Entity Snapshot",
                    "| Entity | State | Unit |",
                    "|---|---|---|",
                ]
                for eid, state in sorted(export.entity_snapshot.items()):
                    if isinstance(state, dict):
                        val = state.get("state", "")
                        unit = state.get("attributes", {}).get(
                            "unit_of_measurement", ""
                        )
                    else:
                        val, unit = str(state), ""
                    rows.append(f"| `{eid}` | {val} | {unit} |")
                sections.append("\n".join(rows))

            # TOU segments (small)
            if export.inverter_tou_segments:
                sections.append(
                    f"## Inverter TOU ({len(export.inverter_tou_segments)} segments)\n"
                    f"```json\n{json.dumps(export.inverter_tou_segments, indent=1, default=str)}\n```"
                )

            # Historical data — table only, no raw JSON
            period_count = (
                len(export.historical_periods) if export.historical_periods else 0
            )
            if export.historical_periods:
                rows = [
                    f"## Historical Data ({period_count} quarter-hours)",
                    "| Time | Intent | Observed | SOE kWh | Solar | Import | Savings |",
                    "|------|--------|----------|---------|-------|--------|---------|",
                ]
                for p in export.historical_periods:
                    if p is None:
                        continue
                    ts = str(p.get("timestamp", ""))
                    dec = p.get("decision", {})
                    en = p.get("energy", {})
                    econ = p.get("economic", {})
                    rows.append(
                        f"| {ts[11:16] if len(ts) >= 16 else ''} "
                        f"| {(dec.get('strategic_intent') or '')[:16]} "
                        f"| {(dec.get('observed_intent') or '')[:16]} "
                        f"| {en.get('battery_soe_start', 0):.1f}→{en.get('battery_soe_end', 0):.1f} "
                        f"| {en.get('solar_production', 0):.2f} "
                        f"| {en.get('grid_imported', 0):.2f} "
                        f"| {econ.get('hourly_savings', 0):.4f} |"
                    )
                sections.append("\n".join(rows))

            # Latest schedule — table only
            schedule_count = len(export.schedules) if export.schedules else 0
            if export.schedules:
                sched = export.schedules[0]
                opt_result = sched.get("optimization_result", {})
                econ_summary = opt_result.get("economic_summary", {})
                period_data = opt_result.get("period_data", [])

                sched_parts = [
                    "## Latest Schedule",
                    f"```json\n{json.dumps(econ_summary, indent=1, default=str)}\n```",
                ]

                if period_data:
                    rows = [
                        "| Time | Intent | BattAct | SOE kWh | BuyPrice | Savings |",
                        "|------|--------|---------|---------|----------|---------|",
                    ]
                    for p in period_data:
                        dec = p.get("decision", {})
                        en = p.get("energy", {})
                        econ = p.get("economic", {})
                        ts = str(p.get("timestamp", ""))
                        rows.append(
                            f"| {ts[11:16] if len(ts) >= 16 else ''} "
                            f"| {(dec.get('strategic_intent') or '')[:16]} "
                            f"| {(dec.get('battery_action', 0) or 0):>+.3f} "
                            f"| {en.get('battery_soe_start', 0):.1f}→{en.get('battery_soe_end', 0):.1f} "
                            f"| {econ.get('buy_price', 0):.4f} "
                            f"| {econ.get('hourly_savings', 0):.4f} |"
                        )
                    sched_parts.append("\n".join(rows))

                sections.append("\n\n".join(sched_parts))

            # Prediction snapshots — evolution table
            if export.snapshots:
                rows = [
                    f"## Prediction Snapshots ({len(export.snapshots)})",
                    "| Timestamp | Total Savings | Actual Count | Predicted Count |",
                    "|-----------|---------------|--------------|-----------------|",
                ]
                for sn in export.snapshots:
                    rows.append(
                        f"| {str(sn.get('snapshot_timestamp', ''))[:16]} "
                        f"| {(sn.get('total_savings', 0) or 0):.4f} "
                        f"| {sn.get('actual_count', 0)} "
                        f"| {sn.get('predicted_count', 0)} |"
                    )
                sections.append("\n".join(rows))

            # Logs — key events only, capped
            if (
                export.todays_log_content
                and "not found" not in export.todays_log_content.lower()
            ):
                log_lines = export.todays_log_content.split("\n")
                # Cap at 200 lines to stay within budget.
                if len(log_lines) > 200:
                    log_lines = log_lines[-200:]
                    sections.append(
                        f"## Logs (last 200 of {len(export.todays_log_content.splitlines())} lines)\n"
                        f"```\n{chr(10).join(log_lines)}\n```"
                    )
                else:
                    sections.append(
                        f"## Logs ({len(log_lines)} lines)\n```\n{chr(10).join(log_lines)}\n```"
                    )

            markdown = "\n\n".join(sections)

            # Final safety net: hard truncate if still too large.
            if len(markdown) > _MAX_CONTEXT_CHARS:
                markdown = (
                    markdown[:_MAX_CONTEXT_CHARS]
                    + "\n\n[... context truncated to fit token limit]"
                )

            summary = (
                f"Loaded: {period_count} historical periods, "
                f"{schedule_count} schedule(s), "
                f"health, settings, logs "
                f"({len(markdown) // 1000}KB)"
            )

            return markdown, summary

        except Exception as e:
            logger.exception("Failed to gather AI chat context: %s", e)
            return "", "Warning: Could not load full system context."

    def _trim_messages(self, session: ChatSession) -> None:
        """Keep conversation within budget by collapsing old tool exchanges.

        Strategy: keep the most recent _MAX_MESSAGE_PAIRS simple
        user/assistant exchanges.  Older tool_use/tool_result message
        pairs are collapsed to just the final assistant text.
        """
        # First pass: collapse old tool exchanges into simple text messages.
        collapsed = []
        i = 0
        while i < len(session.messages):
            msg = session.messages[i]

            # Check if this is an assistant message with tool_use content.
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
                # This is a tool-use exchange.  Skip it and the following
                # tool_result message — they'll be naturally replaced by
                # the final text response that follows.
                i += 1
                # Skip the tool_result message too.
                if (
                    i < len(session.messages)
                    and isinstance(session.messages[i].get("content"), list)
                    and any(
                        isinstance(c, dict) and c.get("type") == "tool_result"
                        for c in session.messages[i].get("content", [])
                    )
                ):
                    i += 1
                continue

            collapsed.append(msg)
            i += 1

        session.messages = collapsed

        # Second pass: enforce max message count.
        max_messages = _MAX_MESSAGE_PAIRS * 2
        if len(session.messages) > max_messages:
            session.messages = session.messages[-max_messages:]

    def _cleanup_expired(self) -> None:
        """Remove sessions that have been inactive beyond the TTL."""
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_active > _SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.info("AI chat session expired: %s", sid)


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event string."""
    payload = {"type": event_type, **data}
    return f"data: {json.dumps(payload)}\n\n"
