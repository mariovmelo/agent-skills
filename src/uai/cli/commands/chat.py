"""uai chat — interactive conversation session with persistent context (REPL)."""
from __future__ import annotations
import asyncio
import time
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich import print as rprint

console = Console()


def _make_on_status(status):
    """
    Build an on_status callback that populates a StreamStatus for stream_to_live().

    Events:
      "routing"  decision         → updates spinner text with provider/task/complexity
      "fallback" from, err, to   → appends a dim warning line; updates spinner
    """
    from uai.cli.streaming import StreamStatus

    def on_status(event: str, *args) -> None:
        if event == "routing":
            decision = args[0]
            model_tag = decision.model or "default"
            task_tag = decision.task_type.value.replace("_", " ")
            # Extract complexity/flags from reason string (e.g. "[simple]", "[long-ctx]")
            reason = decision.reason or ""
            complexity = ""
            for tag in ("[simple]", "[medium]", "[complex]"):
                if tag in reason:
                    complexity = f" · {tag[1:-1]}"
                    break
            long_ctx = " · long-ctx" if "[long-ctx]" in reason else ""
            free_tag = "[free]" if "[free]" in reason else ""
            status.spinner.text = (
                f" → [cyan]{decision.provider}[/cyan] · {model_tag}"
                f"  [{task_tag}{complexity}{long_ctx}]  {free_tag}"
            )

        elif event == "fallback":
            from_prov, error, to_prov = args[0], args[1], args[2]
            err_short = str(error)[:70]
            line = f"[dim red]  ✗ {from_prov}:[/dim red] [dim]{err_short}[/dim]"
            if to_prov:
                line += f"[dim yellow] → tentando {to_prov}...[/dim yellow]"
                status.spinner.text = f" ↪ {to_prov} · aguardando..."
            else:
                line += "[dim red] (sem mais provedores)[/dim red]"
            status.lines.append(line)

    return on_status


def chat(
    session: str = typer.Option("default", "--session", "-s", help="Session name"),
    provider: str = typer.Option(None, "--provider", "-p", help="Force a specific provider"),
    free: bool = typer.Option(False, "--free", help="Use only free providers"),
    new: bool = typer.Option(False, "--new", help="Start a fresh session (clears history)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume the most recent session"),
) -> None:
    """
    Start an interactive chat session with persistent context.

    Your conversation is saved across sessions. Switch providers mid-chat
    with /provider <name>. Type /help for all commands.
    """
    asyncio.run(_chat(session, provider, free, new, resume))


async def _chat(
    session_name: str,
    forced_provider: str | None,
    free: bool,
    new: bool,
    resume: bool,
) -> None:
    from uai.core.executor import RequestExecutor
    from uai.models.request import UAIRequest
    from uai.cli.slash_commands import build_default_registry, ChatContext
    from uai.cli.streaming import stream_to_live
    from uai.cli.input_handler import make_prompt_session, get_user_input
    from uai.cli.input_expander import expand_input

    executor = RequestExecutor.create_default()

    # --resume: find most recent session
    if resume:
        sessions = executor.context.list_sessions()
        if sessions:
            session_name = sessions[0].name
            rprint(f"[dim]Resuming session: [yellow]{session_name}[/yellow][/dim]")

    session = executor.context.get_session(session_name)

    if new:
        executor.context.clear_messages(session)
        rprint(f"[dim]Session '{session_name}' cleared.[/dim]")

    msgs = executor.context.get_messages(session)
    rprint(f"\n[bold cyan]UAI Chat[/bold cyan] — session: [yellow]{session_name}[/yellow]")
    rprint(f"[dim]{len(msgs)} messages in history. Type /help for commands, Ctrl+C or /exit to quit.[/dim]\n")

    current_provider = forced_provider

    # Setup slash command registry
    registry = build_default_registry()
    ctx = ChatContext(
        session_name=session_name,
        executor=executor,
        session=session,
        console=console,
        current_provider=current_provider,
        free=free,
    )

    # Setup prompt_toolkit session
    history_path = executor.config.config_dir / "chat_history"
    pt_session = make_prompt_session(history_path, extra_commands=registry.all_names())

    while True:
        try:
            provider_label = current_provider or "auto"
            user_input = await get_user_input(pt_session, provider_label)
        except (KeyboardInterrupt, EOFError):
            rprint("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # Handle slash commands via registry
        if user_input.startswith("/"):
            ctx.current_provider = current_provider
            result = await registry.dispatch(user_input, ctx)
            if result == "exit":
                break
            if result and result.startswith("provider:"):
                current_provider = result.split(":", 1)[1] or None
                ctx.current_provider = current_provider
            elif result and result.startswith("session:"):
                new_name = result.split(":", 1)[1]
                if new_name:
                    session_name = new_name
                    session = executor.context.get_session(session_name)
                    ctx.session_name = session_name
                    ctx.session = session
                    msgs = executor.context.get_messages(session)
                    rprint(
                        f"[dim]Switched to session: [yellow]{session_name}[/yellow]"
                        f" ({len(msgs)} messages)[/dim]"
                    )
            continue

        # Expand @file and !shell references
        expanded_prompt, warnings = await expand_input(user_input)
        for w in warnings:
            rprint(f"[yellow]Warning: {w}[/yellow]")

        # Execute request with streaming
        request = UAIRequest(
            prompt=expanded_prompt,
            provider=current_provider,
            session_name=session_name,
            free_only=free,
            use_context=True,
        )

        try:
            from uai.cli.streaming import StreamStatus
            status = StreamStatus()
            on_status = _make_on_status(status)

            rprint()  # blank line before response
            t0 = time.monotonic()
            full_text = await stream_to_live(
                executor.execute_stream(request, on_status=on_status),
                console,
                live_status=status,
            )
            elapsed = time.monotonic() - t0
            tokens_est = len(full_text) // 4
            rprint(
                f"[dim]  ⏱ {elapsed:.1f}s · ~{tokens_est} tokens[/dim]"
            )
        except Exception as e:
            from uai.core.errors import UAIError
            if isinstance(e, UAIError):
                rprint(e.rich_format())
            else:
                rprint(f"[red]Error: {e}[/red]")
            continue
