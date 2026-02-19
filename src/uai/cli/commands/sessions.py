"""uai sessions — manage conversation sessions."""
from __future__ import annotations
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def sessions_list() -> None:
    """List all saved conversation sessions."""
    from uai.core.executor import RequestExecutor

    executor = RequestExecutor()
    sessions = executor.context.list_sessions()

    if not sessions:
        rprint("[dim]No sessions found. Start chatting with [cyan]uai chat[/cyan].[/dim]")
        return

    table = Table(title="Sessions", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan", width=20)
    table.add_column("Messages", width=10)
    table.add_column("Tokens", width=10)
    table.add_column("Last Active", width=22)
    table.add_column("Size", width=10)

    for s in sessions:
        size_kb = s.size_bytes / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        table.add_row(
            s.name,
            str(s.total_messages),
            str(s.total_tokens),
            s.last_active.strftime("%Y-%m-%d %H:%M"),
            size_str,
        )

    console.print(table)


def sessions_show(
    name: str = typer.Argument("default", help="Session name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of messages to show"),
) -> None:
    """Show conversation history of a session."""
    from uai.core.executor import RequestExecutor
    from uai.models.context import MessageRole
    from rich.markdown import Markdown

    executor = RequestExecutor()
    session = executor.context.get_session(name)
    messages = executor.context.get_messages(session, limit=limit)

    if not messages:
        rprint(f"[dim]No messages in session '{name}'.[/dim]")
        return

    rprint(f"\n[bold cyan]Session: {name}[/bold cyan] ({len(messages)} messages shown)\n")
    for msg in messages:
        if msg.role == MessageRole.USER:
            rprint(f"[bold]You:[/bold] {msg.content}")
        elif msg.role == MessageRole.ASSISTANT:
            provider_tag = f"[dim]({msg.provider}/{msg.model})[/dim]" if msg.provider else ""
            rprint(f"[bold cyan]Assistant[/bold cyan] {provider_tag}:")
            console.print(Markdown(msg.content))
        elif msg.role == MessageRole.SUMMARY:
            rprint(f"[dim italic][Summary]: {msg.content[:200]}...[/dim italic]")
        rprint()


def sessions_delete(
    name: str = typer.Argument(..., help="Session name to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a conversation session."""
    from uai.core.executor import RequestExecutor

    if not yes:
        confirm = typer.confirm(f"Delete session '{name}'? This cannot be undone.")
        if not confirm:
            rprint("[dim]Aborted.[/dim]")
            return

    executor = RequestExecutor()
    executor.context.delete_session(name)
    rprint(f"[green]✓ Session '{name}' deleted.[/green]")


def sessions_export(
    name: str = typer.Argument("default", help="Session name"),
    format: str = typer.Option("markdown", "--format", "-f", help="Export format: markdown | json"),
    output: str = typer.Option(None, "--output", "-o", help="Output file (default: <name>.<ext>)"),
) -> None:
    """Export a session as markdown or JSON."""
    from uai.core.executor import RequestExecutor

    executor = RequestExecutor()
    session = executor.context.get_session(name)

    fmt = format.lower()
    if fmt not in ("markdown", "json"):
        rprint("[red]Format must be 'markdown' or 'json'.[/red]")
        raise typer.Exit(1)

    content = executor.context.export_session(session, fmt=fmt)  # type: ignore[arg-type]

    ext = "md" if fmt == "markdown" else "json"
    filename = output or f"{name}.{ext}"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    rprint(f"[green]✓ Session '{name}' exported to {filename}[/green]")
