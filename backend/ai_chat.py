"""AI Analyst chat service for in-app BESS analysis.

Provides a streaming chat interface backed by the Claude API.  The system prompt
is loaded directly from .claude/agents/bess-analyst.md (single source of truth)
and augmented with live system context from the debug data exporter.
"""

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

# Path to the bess-analyst agent definition.
# In Docker the file is at /app/agents/bess-analyst.md.
# In local dev it lives at <repo>/.claude/agents/bess-analyst.md.
_APP_DIR = Path(__file__).resolve().parent
_ANALYST_MD_PATH = _APP_DIR / "agents" / "bess-analyst.md"
if not _ANALYST_MD_PATH.exists():
    _ANALYST_MD_PATH = _APP_DIR.parent / ".claude" / "agents" / "bess-analyst.md"

# Preamble prepended to the agent definition to adapt it for in-app use.
_PREAMBLE = """\
You are an AI analyst embedded in the BESS Manager web UI.  A user is asking
you questions about their battery energy storage system — its performance,
optimization decisions, savings, and configuration.

You have access to a complete snapshot of the live system state (settings,
sensor data, schedules, predictions, logs) provided below.  Use this data to
give specific, evidence-based answers.  Reference actual numbers from the data
when possible.

Important guidelines:
- Be concise and direct.  The user is looking at their dashboard while chatting.
- When discussing savings deviations, cite the specific periods and values.
- If the data is insufficient to answer, say so clearly.
- Format responses with markdown (bold, lists, code blocks) for readability.
- Do NOT suggest the user look at code or run commands — they are end users.
- Monetary values should use the currency from the system settings.

Below is your domain knowledge about the BESS system, followed by the current
system state.

"""

# Session expiry: 2 hours of inactivity.
_SESSION_TTL_SECONDS = 2 * 60 * 60

# Maximum conversation pairs to keep (sliding window).
_MAX_MESSAGE_PAIRS = 20

# Conservative token estimate: ~4 chars per token.
_CHARS_PER_TOKEN = 4

# Maximum characters for the system context.  Leaves room for the system
# prompt base (~12K chars), preamble (~2K), and conversation history.
# 150K tokens * 4 chars/token = 600K chars.
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
            "model": cfg.get("model", "claude-sonnet-4-20250514"),
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
        """Stream an AI response as SSE events.

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

        model = cfg.get("model", "claude-sonnet-4-20250514")
        system_prompt = self._build_full_system_prompt(session.system_context)

        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            assistant_text = ""

            async with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=session.messages,
            ) as stream:
                async for text in stream.text_stream:
                    assistant_text += text
                    yield _sse_event("text_delta", {"text": text})

            # Store assistant response in history.
            session.messages.append({"role": "assistant", "content": assistant_text})
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
        """Load the bess-analyst.md file, stripping YAML frontmatter."""
        try:
            raw = _ANALYST_MD_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "bess-analyst.md not found at %s — using minimal prompt",
                _ANALYST_MD_PATH,
            )
            return "You are a BESS (Battery Energy Storage System) analyst."

        # Strip YAML frontmatter (between --- markers at the start).
        stripped = re.sub(r"\A---\n.*?\n---\n*", "", raw, count=1, flags=re.DOTALL)
        return stripped.strip()

    def _build_full_system_prompt(self, context: str) -> str:
        """Combine preamble + domain knowledge + live context."""
        parts = [_PREAMBLE, self._system_prompt_base]
        if context:
            parts.append("\n\n---\n\n# Current System State\n\n" + context)
        return "\n".join(parts)

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
                    f"## Historical Data ({period_count} periods)",
                    "| Per | Time | Intent | Observed | SOE kWh | Solar | Import | Savings |",
                    "|-----|------|--------|----------|---------|-------|--------|---------|",
                ]
                for p in export.historical_periods:
                    if p is None:
                        continue
                    ts = str(p.get("timestamp", ""))
                    dec = p.get("decision", {})
                    en = p.get("energy", {})
                    econ = p.get("economic", {})
                    rows.append(
                        f"| {p.get('period', ''):>3} "
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
                    f"## Latest Schedule (period {sched.get('optimization_period', '?')})",
                    f"```json\n{json.dumps(econ_summary, indent=1, default=str)}\n```",
                ]

                if period_data:
                    rows = [
                        "| Per | Time | Intent | BattAct | SOE kWh | BuyPrice | Savings |",
                        "|-----|------|--------|---------|---------|----------|---------|",
                    ]
                    for p in period_data:
                        dec = p.get("decision", {})
                        en = p.get("energy", {})
                        econ = p.get("economic", {})
                        ts = str(p.get("timestamp", ""))
                        rows.append(
                            f"| {p.get('period', ''):>3} "
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
                    "| Timestamp | Per | Total Savings | Actual | Predicted |",
                    "|-----------|-----|---------------|--------|-----------|",
                ]
                for sn in export.snapshots:
                    rows.append(
                        f"| {str(sn.get('snapshot_timestamp', ''))[:16]} "
                        f"| {sn.get('optimization_period', '')} "
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
        """Keep at most _MAX_MESSAGE_PAIRS user/assistant pairs."""
        max_messages = _MAX_MESSAGE_PAIRS * 2
        if len(session.messages) > max_messages:
            # Keep the most recent messages.
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
