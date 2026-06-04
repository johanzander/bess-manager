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

# Path to the bess-analyst agent definition (ships with the Docker image).
_ANALYST_MD_PATH = (
    Path(__file__).resolve().parent.parent / ".claude" / "agents" / "bess-analyst.md"
)

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
        """Gather compact debug export as context string.

        Returns:
            Tuple of (full_context_markdown, short_summary).
        """
        from core.bess.debug_data_exporter import DebugDataAggregator
        from core.bess.debug_report_formatter import DebugReportFormatter

        try:
            aggregator = DebugDataAggregator(
                system_manager,
                settings_data=self._settings_store.data,
            )
            export_data = aggregator.aggregate_all_data(compact=True)

            formatter = DebugReportFormatter()
            markdown = formatter.format_report(export_data)

            # Build a short summary for the UI.
            period_count = (
                len(export_data.historical_periods)
                if export_data.historical_periods
                else 0
            )
            schedule_count = len(export_data.schedules) if export_data.schedules else 0
            summary = (
                f"Loaded: {period_count} historical periods, "
                f"{schedule_count} schedule(s), "
                f"health check, settings, logs"
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
