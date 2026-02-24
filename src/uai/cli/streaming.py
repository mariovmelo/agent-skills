"""Utilities for streaming responses with Rich Live rendering."""
from __future__ import annotations
import asyncio
from typing import AsyncIterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner


async def stream_to_live(
    token_stream: AsyncIterator[str],
    console: Console,
    show_spinner: bool = True,
) -> str:
    """
    Consume an async token stream and render it incrementally using Rich Live.

    Shows a spinner while waiting for the first token, then switches to
    streaming Markdown rendering as tokens arrive.

    Returns the full accumulated text.
    """
    accumulated = ""
    first_token = True

    with Live(
        Spinner("dots", text=" Thinking..."),
        console=console,
        refresh_per_second=15,
        transient=False,
    ) as live:
        async for token in token_stream:
            accumulated += token
            if first_token:
                first_token = False
            # Render accumulated text as Markdown in-place
            live.update(Markdown(accumulated))

    return accumulated


async def show_spinner_while(coro, console: Console, message: str = "Working..."):
    """
    Show a spinner while awaiting a coroutine that does not stream.
    Used for non-streaming operations (health checks, setup, etc.).
    """
    with Live(
        Spinner("dots", text=f" {message}"),
        console=console,
        transient=True,
    ):
        return await coro
