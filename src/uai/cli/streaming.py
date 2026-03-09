"""Utilities for streaming responses with Rich Live rendering."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text


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
    timing: dict | None = None,
) -> str:
    """
    Consume an async token stream and render it incrementally using Rich Live.

    Phase 1 — Waiting: spinner shows routing progress.
      The spinner.text is mutated by on_status() callbacks fired inside
      execute_stream() during async awaits — Rich picks up the change on the
      next 15fps refresh cycle, so the text updates before the first token.

    Phase 2 — Streaming: switches to incremental Markdown on first token.
      Any pending status.lines (fallback events) are printed above the
      response content just before the first Markdown render.

    timing (optional dict) is populated with:
      ttft_s   — seconds from Live start to first token (Time To First Token)
      stream_s — seconds spent streaming after first token
      total_s  — total seconds inside the Live context

    Returns the full accumulated text.
    """
    status = live_status or StreamStatus()
    accumulated = ""
    first_token = True
    t_live_start = time.monotonic()
    t_first_token: float | None = None

    with Live(
        status.spinner,
        console=console,
        refresh_per_second=15,
        transient=False,
    ) as live:
        async for token in token_stream:
            # Flush pending status lines (fallback warnings) above the content
            while status.lines:
                live.console.print(status.lines.pop(0))

            accumulated += token

            if first_token:
                first_token = False
                t_first_token = time.monotonic()

            live.update(Markdown(accumulated))

    t_end = time.monotonic()
    if timing is not None:
        ttft = (t_first_token - t_live_start) if t_first_token else 0.0
        total = t_end - t_live_start
        timing["ttft_s"] = ttft
        timing["stream_s"] = max(0.0, total - ttft)
        timing["total_s"] = total

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
