"""Tests for src/uai/cli/streaming.py"""
from __future__ import annotations
import pytest
from io import StringIO
from rich.console import Console

from uai.cli.streaming import show_spinner_while, stream_to_live


def _make_console() -> Console:
    return Console(file=StringIO(), highlight=False, force_terminal=False)


async def _gen(*tokens: str):
    for t in tokens:
        yield t


@pytest.mark.asyncio
class TestStreamToLive:
    async def test_concatenates_tokens(self):
        console = _make_console()
        result = await stream_to_live(_gen("hello", " ", "world"), console)
        assert result == "hello world"

    async def test_empty_stream_returns_empty_string(self):
        console = _make_console()
        result = await stream_to_live(_gen(), console)
        assert result == ""

    async def test_single_token(self):
        console = _make_console()
        result = await stream_to_live(_gen("only"), console)
        assert result == "only"

    async def test_multiline_tokens(self):
        console = _make_console()
        result = await stream_to_live(_gen("line1\n", "line2\n"), console)
        assert result == "line1\nline2\n"

    async def test_no_show_spinner(self):
        console = _make_console()
        result = await stream_to_live(_gen("a", "b"), console, show_spinner=False)
        assert result == "ab"


@pytest.mark.asyncio
class TestShowSpinnerWhile:
    async def test_returns_coroutine_result(self):
        console = _make_console()

        async def _work():
            return 42

        result = await show_spinner_while(_work(), console)
        assert result == 42

    async def test_returns_none_from_coroutine(self):
        console = _make_console()

        async def _noop():
            return None

        result = await show_spinner_while(_noop(), console)
        assert result is None

    async def test_propagates_exception(self):
        console = _make_console()

        async def _fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await show_spinner_while(_fail(), console)

    async def test_custom_message_accepted(self):
        console = _make_console()

        async def _work():
            return "done"

        result = await show_spinner_while(_work(), console, message="Loading...")
        assert result == "done"
