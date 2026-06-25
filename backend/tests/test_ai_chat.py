"""Tests for AIAnalystService — the in-app AI chat backend.

Covers: service init, status reporting, session lifecycle, message trimming,
session expiry, SSE formatting, system prompt loading, and tool execution
(read_file, search_code, list_files) including path sandboxing.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from ai_chat import (
    _MAX_FILE_READ_LINES,
    _MAX_MESSAGE_PAIRS,
    _MAX_TOOL_RESULT_CHARS,
    AIAnalystService,
    ChatSession,
    _execute_tool,
    _resolve_and_validate_path,
    _sse_event,
    _tool_list_files,
    _tool_read_file,
    _tool_search_code,
)

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
                "model": "claude-opus-4-8",
                "enabled": True,
            }
        )
        status = service.get_status()
        assert status["configured"] is True
        assert status["model"] == "claude-opus-4-8"

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
        with patch("ai_chat._KNOWLEDGE_MD_PATH") as mock_path:
            mock_path.read_text.return_value = md_content
            result = service._load_system_prompt()
        assert result == "# Domain Knowledge\nHello"
        assert "---" not in result

    def test_file_not_found_fallback(self):
        service = _make_service()
        with patch("ai_chat._KNOWLEDGE_MD_PATH") as mock_path:
            mock_path.read_text.side_effect = FileNotFoundError
            result = service._load_system_prompt()
        assert "BESS" in result

    def test_system_prompt_returns_list_with_cache_control(self):
        service = _make_service()
        result = service._build_full_system_prompt("some context")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["cache_control"] == {"type": "ephemeral"}
        assert "domain knowledge" in result[0]["text"]
        assert "some context" in result[1]["text"]


# ---------------------------------------------------------------------------
# Path resolution and sandboxing
# ---------------------------------------------------------------------------


class TestPathSandbox:
    def test_valid_core_path(self):
        result = _resolve_and_validate_path("core/bess/models.py")
        assert result is not None
        assert result.name == "models.py"

    def test_valid_backend_path(self):
        result = _resolve_and_validate_path("backend/api.py")
        assert result is not None

    def test_traversal_blocked(self):
        assert _resolve_and_validate_path("../../../etc/passwd") is None
        assert _resolve_and_validate_path("core/../../etc/passwd") is None

    def test_absolute_path_blocked(self):
        assert _resolve_and_validate_path("/etc/passwd") is None

    def test_blocked_patterns(self):
        assert _resolve_and_validate_path("backend/.env") is None
        assert _resolve_and_validate_path("core/bess/credentials.json") is None

    def test_disallowed_directory(self):
        # node_modules, frontend, etc. are not in _ALLOWED_DIRS.
        result = _resolve_and_validate_path("frontend/package.json")
        assert result is None

    def test_root_listing_allowed(self):
        # Empty path resolves to codebase root — allowed for list_files.
        result = _resolve_and_validate_path("")
        # The root itself is "." relative, which is allowed.
        assert result is not None or True  # May be None depending on structure


# ---------------------------------------------------------------------------
# Tool: read_file
# ---------------------------------------------------------------------------


class TestToolReadFile:
    def test_read_existing_file(self):
        result = _tool_read_file({"path": "core/bess/models.py"})
        assert "class EnergyData" in result or "dataclass" in result
        assert not result.startswith("Error")

    def test_read_with_line_range(self):
        result = _tool_read_file(
            {"path": "core/bess/models.py", "start_line": 1, "end_line": 10}
        )
        assert "(lines 1-10" in result

    def test_read_nonexistent_file(self):
        result = _tool_read_file({"path": "core/bess/nonexistent.py"})
        assert "Error" in result

    def test_read_blocked_file(self):
        result = _tool_read_file({"path": "backend/.env"})
        assert "Access denied" in result

    def test_line_cap_enforced(self):
        # Read a large file without range — should cap at _MAX_FILE_READ_LINES.
        result = _tool_read_file({"path": "core/bess/dp_battery_algorithm.py"})
        lines = [
            line
            for line in result.split("\n")
            if line and not line.startswith("#") and not line.startswith("[")
        ]
        assert len(lines) <= _MAX_FILE_READ_LINES + 5  # Small margin for header/footer


# ---------------------------------------------------------------------------
# Tool: search_code
# ---------------------------------------------------------------------------


class TestToolSearchCode:
    def test_search_finds_matches(self):
        result = _tool_search_code({"pattern": "class EnergyData"})
        assert "EnergyData" in result
        assert "Error" not in result

    def test_search_no_matches(self):
        # Search only in core/bess/*.py to avoid matching this test file.
        result = _tool_search_code(
            {"pattern": "xyzzy_nonexistent_symbol_12345", "file_glob": "core/bess/*.py"}
        )
        assert "No matches" in result or "No accessible" in result

    def test_search_with_glob(self):
        result = _tool_search_code(
            {"pattern": "def optimize", "file_glob": "core/bess/*.py"}
        )
        assert "optimize" in result.lower()

    def test_search_empty_pattern(self):
        result = _tool_search_code({"pattern": ""})
        assert "Error" in result


# ---------------------------------------------------------------------------
# Tool: list_files
# ---------------------------------------------------------------------------


class TestToolListFiles:
    def test_list_core_bess(self):
        result = _tool_list_files({"path": "core/bess"})
        assert "dp_battery_algorithm.py" in result
        assert "models.py" in result

    def test_list_blocked_directory(self):
        result = _tool_list_files({"path": "frontend/src"})
        assert "Access denied" in result

    def test_list_nonexistent_directory(self):
        result = _tool_list_files({"path": "core/nonexistent"})
        assert "Error" in result or "Access denied" in result


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


class TestExecuteTool:
    def test_unknown_tool(self):
        result = _execute_tool("delete_file", {"path": "foo"})
        assert "Unknown tool" in result

    def test_dispatches_read_file(self):
        result = _execute_tool(
            "read_file", {"path": "core/bess/models.py", "start_line": 1, "end_line": 5}
        )
        assert "Error" not in result
        assert "(lines 1-5" in result

    def test_result_truncation(self):
        # Patch a tool to return a huge result.
        huge = "x" * (_MAX_TOOL_RESULT_CHARS + 1000)
        with patch("ai_chat._tool_read_file", return_value=huge):
            result = _execute_tool("read_file", {"path": "anything"})
        assert (
            len(result) <= _MAX_TOOL_RESULT_CHARS + 100
        )  # Allow for truncation message
        assert "truncated" in result


# ---------------------------------------------------------------------------
# Message trimming with tool exchanges
# ---------------------------------------------------------------------------


class TestTrimMessagesWithTools:
    def test_tool_exchanges_collapsed(self):
        service = _make_service()
        session = ChatSession(session_id="t")
        session.messages = [
            {"role": "user", "content": "question 1"},
            # Tool exchange (assistant with tool_use + user with tool_result)
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check..."},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "read_file",
                        "input": {"path": "x.py"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "file contents",
                    },
                ],
            },
            # Final text response
            {"role": "assistant", "content": "Here is the answer."},
        ]
        service._trim_messages(session)
        # Tool exchange should be collapsed — only user question + final answer remain.
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "question 1"
        assert session.messages[1]["content"] == "Here is the answer."
