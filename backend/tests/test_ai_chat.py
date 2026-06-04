"""Tests for AIAnalystService — the in-app AI chat backend.

Covers: service init, status reporting, session lifecycle, message trimming,
session expiry, SSE formatting, and system prompt loading.  The anthropic
client is mocked — no real API calls are made.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from ai_chat import _MAX_MESSAGE_PAIRS, AIAnalystService, ChatSession, _sse_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings_store(section: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.get_section.return_value = section or {}
    return store


def _make_service(section: dict | None = None) -> AIAnalystService:
    """Create a service with the system prompt load patched out."""
    with patch.object(
        AIAnalystService, "_load_system_prompt", return_value="domain knowledge"
    ):
        return AIAnalystService(_make_settings_store(section))


# ---------------------------------------------------------------------------
# _sse_event formatting
# ---------------------------------------------------------------------------


class TestSSEEvent:
    def test_text_delta(self):
        result = _sse_event("text_delta", {"text": "hello"})
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        payload = json.loads(result[len("data: ") :].strip())
        assert payload == {"type": "text_delta", "text": "hello"}

    def test_done_event(self):
        result = _sse_event("done", {})
        payload = json.loads(result[len("data: ") :].strip())
        assert payload == {"type": "done"}

    def test_error_event(self):
        result = _sse_event("error", {"error": "something broke"})
        payload = json.loads(result[len("data: ") :].strip())
        assert payload == {"type": "error", "error": "something broke"}


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_unconfigured(self):
        service = _make_service()
        status = service.get_status()
        assert status["configured"] is False
        assert status["enabled"] is True
        assert "model" in status

    def test_configured(self):
        service = _make_service(
            {
                "api_key": "sk-ant-test",
                "model": "claude-opus-4-20250514",
                "enabled": True,
            }
        )
        status = service.get_status()
        assert status["configured"] is True
        assert status["model"] == "claude-opus-4-20250514"

    def test_disabled(self):
        service = _make_service({"api_key": "sk-ant-test", "enabled": False})
        status = service.get_status()
        assert status["configured"] is True
        assert status["enabled"] is False


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


class TestStartSession:
    def test_returns_session_id(self):
        service = _make_service()
        with patch.object(service, "_gather_context", return_value=("ctx", "summary")):
            result = service.start_session(MagicMock())
        assert "sessionId" in result
        assert "contextSummary" in result
        assert result["contextSummary"] == "summary"

    def test_session_stored(self):
        service = _make_service()
        with patch.object(service, "_gather_context", return_value=("ctx", "summary")):
            result = service.start_session(MagicMock())
        assert result["sessionId"] in service._sessions


class TestRefreshContext:
    def test_updates_context(self):
        service = _make_service()
        with patch.object(
            service, "_gather_context", return_value=("ctx1", "summary1")
        ):
            result = service.start_session(MagicMock())
        sid = result["sessionId"]

        with patch.object(
            service, "_gather_context", return_value=("ctx2", "new summary")
        ):
            refresh = service.refresh_context(sid, MagicMock())
        assert refresh["contextSummary"] == "new summary"
        assert service._sessions[sid].system_context == "ctx2"

    def test_missing_session_raises(self):
        service = _make_service()
        with pytest.raises(KeyError):
            service.refresh_context("nonexistent", MagicMock())


# ---------------------------------------------------------------------------
# Session expiry
# ---------------------------------------------------------------------------


class TestSessionExpiry:
    def test_expired_sessions_cleaned(self):
        service = _make_service()
        # Manually inject an expired session.
        old_session = ChatSession(session_id="old", last_active=time.time() - 99999)
        service._sessions["old"] = old_session

        service._cleanup_expired()
        assert "old" not in service._sessions

    def test_active_sessions_kept(self):
        service = _make_service()
        active = ChatSession(session_id="active", last_active=time.time())
        service._sessions["active"] = active

        service._cleanup_expired()
        assert "active" in service._sessions


# ---------------------------------------------------------------------------
# Message trimming
# ---------------------------------------------------------------------------


class TestTrimMessages:
    def test_under_limit_unchanged(self):
        service = _make_service()
        session = ChatSession(session_id="t")
        session.messages = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        service._trim_messages(session)
        assert len(session.messages) == 5

    def test_over_limit_trimmed(self):
        service = _make_service()
        session = ChatSession(session_id="t")
        max_msgs = _MAX_MESSAGE_PAIRS * 2
        session.messages = [
            {"role": "user", "content": f"m{i}"} for i in range(max_msgs + 10)
        ]
        service._trim_messages(session)
        assert len(session.messages) == max_msgs
        # Should keep most recent
        assert session.messages[-1]["content"] == f"m{max_msgs + 9}"


# ---------------------------------------------------------------------------
# stream_response — error paths (no real API call)
# ---------------------------------------------------------------------------


class TestStreamResponse:
    def _collect(self, async_gen):
        """Run an async generator to completion and return all yielded items."""
        return asyncio.run(self._alist(async_gen))

    @staticmethod
    async def _alist(gen):
        items = []
        async for item in gen:
            items.append(item)
        return items

    def test_missing_session(self):
        service = _make_service()
        events = self._collect(service.stream_response("nonexistent", "hi"))
        assert len(events) == 1
        payload = json.loads(events[0][len("data: ") :].strip())
        assert payload["type"] == "error"
        assert "not found" in payload["error"].lower()

    def test_no_api_key(self):
        service = _make_service()
        # Create a session manually.
        session = ChatSession(session_id="s1")
        service._sessions["s1"] = session

        events = self._collect(service.stream_response("s1", "hello"))
        assert len(events) == 1
        payload = json.loads(events[0][len("data: ") :].strip())
        assert payload["type"] == "error"
        assert "api key" in payload["error"].lower()


# ---------------------------------------------------------------------------
# System prompt loading
# ---------------------------------------------------------------------------


class TestLoadSystemPrompt:
    def test_strips_frontmatter(self):
        md_content = "---\nname: test\ntype: agent\n---\n\n# Domain Knowledge\nHello"
        service = _make_service()
        with patch("ai_chat._ANALYST_MD_PATH") as mock_path:
            mock_path.read_text.return_value = md_content
            result = service._load_system_prompt()
        assert result == "# Domain Knowledge\nHello"
        assert "---" not in result

    def test_file_not_found_fallback(self):
        service = _make_service()
        with patch("ai_chat._ANALYST_MD_PATH") as mock_path:
            mock_path.read_text.side_effect = FileNotFoundError
            result = service._load_system_prompt()
        assert "BESS" in result
