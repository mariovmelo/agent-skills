"""uai config — view and edit configuration."""
from __future__ import annotations
import typer
import yaml
from rich.console import Console
from rich import print as rprint
from rich.syntax import Syntax

console = Console()


def config_show() -> None:
    """Show current configuration."""
    from uai.core.config import ConfigManager

    cfg_mgr = ConfigManager()
    rprint(f"[dim]Config file: {cfg_mgr.config_path}[/dim]\n")

    if not cfg_mgr.config_path.exists():
        rprint("[yellow]Config not found. Run: uai setup[/yellow]")
        return

    with cfg_mgr.config_path.open() as f:
        content = f.read()

    console.print(Syntax(content, "yaml", theme="monokai", line_numbers=True))


def config_set(
    key: str = typer.Argument(..., help="Config key in dot notation (e.g. defaults.cost_mode)"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a configuration value using dot notation."""
    from uai.core.config import ConfigManager

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()

    try:
        cfg_mgr.set(key, value)
        rprint(f"[green]✓ Set {key} = {value}[/green]")
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
