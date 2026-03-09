"""uai providers — list and inspect AI providers."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def providers_list() -> None:
    """List all available AI providers."""
    from uai.providers import list_providers, get_provider_class
    from uai.utils.installer import is_cli_installed

    table = Table(title="Available Providers", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan", width=12)
    table.add_column("Display Name", width=20)
    table.add_column("Cost", width=8)
    table.add_column("CLI", width=8)
    table.add_column("Context Window", width=16)
    table.add_column("Best For", width=40)

    for name in list_providers():
        try:
            cls = get_provider_class(name)
        except Exception:
            continue
        cost = "[green]free[/green]" if cls.is_free else "[yellow]paid[/yellow]"
        cli = "[green]✓[/green]" if is_cli_installed(name) else "[dim]✗[/dim]"
        ctx = f"{cls.context_window_tokens // 1000}K"
        caps = ", ".join(c.value.replace("_", " ") for c in cls.capabilities[:3])
        table.add_row(name, cls.display_name, cost, cli, ctx, caps)

    console.print(table)


def providers_detail(
    name: str = typer.Argument(..., help="Provider name"),
) -> None:
    """Show detailed information about a specific provider."""
    from uai.providers import get_provider_class
    from uai.utils.installer import is_cli_installed

    try:
        cls = get_provider_class(name)
    except ValueError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)

    rprint(f"\n[bold cyan]{cls.display_name}[/bold cyan]")
    rprint(f"  Cost:           [{'green' if cls.is_free else 'yellow'}]{'free' if cls.is_free else 'paid'}[/{'green' if cls.is_free else 'yellow'}]")
    rprint(f"  CLI installed:  {'[green]yes[/green]' if is_cli_installed(name) else '[dim]no[/dim]'}")
    rprint(f"  Context window: {cls.context_window_tokens:,} tokens")
    rprint(f"  Backends:       {', '.join(b.value for b in cls.supported_backends)}")
    rprint(f"\n  [bold]Capabilities (ordered by strength):[/bold]")
    for i, cap in enumerate(cls.capabilities, 1):
        rprint(f"    {i}. {cap.value.replace('_', ' ')}")
