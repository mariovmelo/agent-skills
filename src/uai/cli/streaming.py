"""Utilities for streaming responses with Rich Live rendering."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import AsyncIterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner


@dataclass
class StreamStatus:
    """
    Mutable state shared between execute_stream() and stream_to_live().

    The spinner is rendered live; mutating .spinner.text is reflected on the
    next Rich refresh cycle (every ~67ms at 15fps) — no extra calls needed.
    Status lines (fallback events, etc.) are printed above the response content
    when the first token arrives.
    """
    spinner: Spinner = field(default_factory=lambda: Spinner("dots", text=" Roteando..."))
    lines: list[str] = field(default_factory=list)


async def stream_to_live(
    token_stream: AsyncIterator[str],
    console: Console,
    show_spinner: bool = True,
    live_status: StreamStatus | None = None,
) -> str:
    """
    Consume an async token stream and render it incrementally using Rich Live.

    Phase 1 — Waiting: spinner shows routing progress (text mutated by on_status callback).
    Phase 2 — Streaming: switches to incremental Markdown rendering on first token.
    Status lines (fallback notifications) are flushed above the content just before
    the first token is rendered.

    Returns the full accumulated text.
    """
    status = live_status or StreamStatus()
    accumulated = ""
    first_token = True

    with Live(
        status.spinner,
        console=console,
        refresh_per_second=15,
        transient=False,
    ) as live:
        async for token in token_stream:
            # Flush any pending status lines (fallbacks, warnings) above content
            while status.lines:
                live.console.print(status.lines.pop(0))

            accumulated += token
            if first_token:
                first_token = False

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
