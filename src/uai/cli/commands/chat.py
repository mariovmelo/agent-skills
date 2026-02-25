"""uai chat — interactive conversation session with persistent context (REPL)."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich import print as rprint

console = Console()


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
            # Show provider label before streaming starts
            provider_label_str = f"[cyan]{current_provider or 'auto'}[/cyan]"
            rprint(f"\n{provider_label_str}")
            full_text = await stream_to_live(
                executor.execute_stream(request),
                console,
            )
            rprint()
        except Exception as e:
            from uai.core.errors import UAIError
            if isinstance(e, UAIError):
                rprint(e.rich_format())
            else:
                rprint(f"[red]Error: {e}[/red]")
            continue
