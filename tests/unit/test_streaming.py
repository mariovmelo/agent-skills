"""Tests for src/uai/cli/streaming.py"""
from __future__ import annotations
import pytest
from io import StringIO
from rich.console import Console

from uai.cli.streaming import show_spinner_while, stream_to_live, StreamStatus


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

    async def test_timing_dict_populated(self):
        """timing dict receives ttft_s, stream_s, total_s after streaming."""
        console = _make_console()
        timing: dict = {}
        await stream_to_live(_gen("a", "b", "c"), console, timing=timing)
        assert "ttft_s" in timing
        assert "stream_s" in timing
        assert "total_s" in timing
        assert timing["total_s"] >= 0
        assert timing["ttft_s"] >= 0
        assert timing["stream_s"] >= 0
        # total ≈ ttft + stream
        assert abs(timing["total_s"] - (timing["ttft_s"] + timing["stream_s"])) < 0.01

    async def test_timing_empty_stream(self):
        """timing with no tokens: ttft_s is 0, stream_s near-zero, total valid."""
        console = _make_console()
        timing: dict = {}
        await stream_to_live(_gen(), console, timing=timing)
        assert timing["ttft_s"] == 0.0
        assert timing["stream_s"] >= 0
        assert timing["total_s"] >= 0

    async def test_status_lines_flushed(self):
        """Lines in StreamStatus.lines are printed before content."""
        console = _make_console()
        status = StreamStatus()
        status.lines.append("warning: fallback to claude")

        result = await stream_to_live(_gen("ok"), console, live_status=status)
        assert result == "ok"
        # After streaming, lines should be drained
        assert status.lines == []

    async def test_live_status_no_tokens_leaves_lines(self):
        """If stream is empty, lines are never flushed (no token arrives to trigger it)."""
        console = _make_console()
        status = StreamStatus()
        status.lines.append("pending")
        await stream_to_live(_gen(), console, live_status=status)
        # Empty stream → loop body never runs → lines stay
        assert status.lines == ["pending"]


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
