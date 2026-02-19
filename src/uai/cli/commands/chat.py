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
) -> None:
    """
    Start an interactive chat session with persistent context.

    Your conversation is saved across sessions. Switch providers mid-chat
    with /provider <name>. Type /help for all commands.
    """
    asyncio.run(_chat(session, provider, free, new))


async def _chat(
    session_name: str,
    forced_provider: str | None,
    free: bool,
    new: bool,
) -> None:
    from uai.core.executor import RequestExecutor
    from uai.models.request import UAIRequest

    executor = RequestExecutor()
    session = executor.context.get_session(session_name)

    if new:
        executor.context.clear_messages(session)
        rprint(f"[dim]Session '{session_name}' cleared.[/dim]")

    msgs = executor.context.get_messages(session)
    rprint(f"\n[bold cyan]UAI Chat[/bold cyan] — session: [yellow]{session_name}[/yellow]")
    rprint(f"[dim]{len(msgs)} messages in history. Type /help for commands, Ctrl+C or /exit to quit.[/dim]\n")

    current_provider = forced_provider

    while True:
        try:
            user_input = typer.prompt("You", prompt_suffix="> ")
        except (KeyboardInterrupt, EOFError):
            rprint("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            handled = _handle_slash(user_input, session_name, executor, session)
            if handled == "exit":
                break
            if handled and handled.startswith("provider:"):
                current_provider = handled.split(":", 1)[1] or None
            continue

        # Execute request
        request = UAIRequest(
            prompt=user_input,
            provider=current_provider,
            session_name=session_name,
            free_only=free,
            use_context=True,
        )

        try:
            response = await executor.execute(request)
        except Exception as e:
            rprint(f"[red]Error: {e}[/red]")
            continue

        # Show provider info
        tag = f"[cyan]{response.provider}[/cyan]/[dim]{response.model}[/dim]"
        fallback = f" [yellow]→ fallback from {response.providers_tried[0]}[/yellow]" if response.fallback_used else ""
        rprint(f"\n{tag}{fallback}")
        console.print(Markdown(response.text))
        rprint()


def _handle_slash(cmd: str, session_name: str, executor, session) -> str | None:
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/exit", "/quit", "/q"):
        rprint("[dim]Goodbye![/dim]")
        return "exit"

    if command == "/help":
        rprint("""
[bold]Available commands:[/bold]
  /provider <name>   Switch provider (gemini, claude, qwen, codex, ollama...)
  /provider          Reset to auto-routing
  /clear             Clear session history
  /history           Show message count
  /export            Export session as markdown
  /status            Show provider status
  /exit              Exit chat
""")
        return "handled"

    if command == "/provider":
        if arg:
            rprint(f"[dim]Switched to provider: [cyan]{arg}[/cyan][/dim]")
            return f"provider:{arg}"
        else:
            rprint("[dim]Reset to auto-routing.[/dim]")
            return "provider:"

    if command == "/clear":
        executor.context.clear_messages(session)
        rprint("[dim]Session history cleared.[/dim]")
        return "handled"

    if command == "/history":
        msgs = executor.context.get_messages(session)
        rprint(f"[dim]{len(msgs)} messages in session '{session_name}'.[/dim]")
        return "handled"

    if command == "/export":
        content = executor.context.export_session(session, fmt="markdown")
        filename = f"{session_name}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        rprint(f"[green]✓ Exported to {filename}[/green]")
        return "handled"

    if command == "/status":
        from uai.models.provider import ProviderStatus
        import asyncio as _asyncio
        rprint("[bold]Provider status:[/bold]")
        for name, prov in executor.providers.items():
            try:
                st = _asyncio.run(prov.health_check())
            except Exception:
                st = ProviderStatus.UNAVAILABLE
            color = "green" if st == ProviderStatus.AVAILABLE else "red"
            rprint(f"  [{color}]{name}[/{color}]: {st.value}")
        return "handled"

    rprint(f"[yellow]Unknown command: {cmd}. Type /help for available commands.[/yellow]")
    return "handled"
