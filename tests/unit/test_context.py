"""Tests for ContextManager."""
from __future__ import annotations
import pytest
from uai.models.context import MessageRole


def test_get_or_create_session(context_mgr):
    session = context_mgr.get_session("test")
    assert session.name == "test"


def test_add_messages(context_mgr):
    session = context_mgr.get_session("test")
    context_mgr.add_user_message(session, "hello")
    context_mgr.add_assistant_message(session, "hi there", "gemini", "gemini-flash")

    msgs = context_mgr.get_messages(session)
    assert len(msgs) == 2
    assert msgs[0].role == MessageRole.USER
    assert msgs[0].content == "hello"
    assert msgs[1].role == MessageRole.ASSISTANT
    assert msgs[1].provider == "gemini"


def test_session_persistence(context_mgr):
    """Messages survive across separate get_session calls."""
    s1 = context_mgr.get_session("persist-test")
    context_mgr.add_user_message(s1, "persistent message")

    s2 = context_mgr.get_session("persist-test")
    msgs = context_mgr.get_messages(s2)
    assert any(m.content == "persistent message" for m in msgs)


def test_list_sessions(context_mgr):
    context_mgr.get_session("session-a")
    context_mgr.get_session("session-b")
    sessions = context_mgr.list_sessions()
    names = [s.name for s in sessions]
    assert "session-a" in names
    assert "session-b" in names


def test_delete_session(context_mgr):
    context_mgr.get_session("to-delete")
    context_mgr.delete_session("to-delete")
    sessions = context_mgr.list_sessions()
    names = [s.name for s in sessions]
    assert "to-delete" not in names


def test_clear_messages(context_mgr):
    session = context_mgr.get_session("clear-test")
    context_mgr.add_user_message(session, "msg1")
    context_mgr.add_user_message(session, "msg2")
    context_mgr.clear_messages(session)
    assert context_mgr.get_messages(session) == []


def test_export_markdown(context_mgr):
    session = context_mgr.get_session("export-test")
    context_mgr.add_user_message(session, "what is uai?")
    context_mgr.add_assistant_message(session, "UAI is a unified AI CLI.", "gemini", "flash")

    md = context_mgr.export_session(session, fmt="markdown")
    assert "what is uai?" in md
    assert "UAI is a unified AI CLI." in md


def test_export_json(context_mgr):
    import json
    session = context_mgr.get_session("json-test")
    context_mgr.add_user_message(session, "hello")
    result = context_mgr.export_session(session, fmt="json")
    data = json.loads(result)
    assert isinstance(data, list)
    assert data[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_prepare_context_full(context_mgr):
    from unittest.mock import MagicMock
    session = context_mgr.get_session("ctx-full")
    for i in range(3):
        context_mgr.add_user_message(session, f"question {i}")
        context_mgr.add_assistant_message(session, f"answer {i}", "gemini", "flash")

    mock_provider = MagicMock()
    mock_provider.context_window_tokens = 1_000_000

    msgs = await context_mgr.prepare_context(session, mock_provider, strategy="full")
    assert len(msgs) == 6


@pytest.mark.asyncio
async def test_prepare_context_windowed(context_mgr):
    from unittest.mock import MagicMock
    session = context_mgr.get_session("ctx-windowed")
    for i in range(15):
        context_mgr.add_user_message(session, f"q{i}")
        context_mgr.add_assistant_message(session, f"a{i}", "gemini", "flash")

    mock_provider = MagicMock()
    mock_provider.context_window_tokens = 100_000

    msgs = await context_mgr.prepare_context(
        session, mock_provider, strategy="windowed", keep_recent_turns=5
    )
    assert len(msgs) <= 10  # 5 turns * 2 messages
