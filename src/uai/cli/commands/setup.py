"""uai setup — first-run wizard."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def setup(
    install: bool = typer.Option(False, "--install", help="Auto-install missing CLIs via npm"),
) -> None:
    """First-run setup: detect CLIs, create config, initialize session store."""
    from uai.core.config import ConfigManager
    from uai.utils.installer import check_all_clis, install_cli, npm_available

    rprint("[bold cyan]UAI — Unified AI CLI Setup[/bold cyan]\n")

    # 1. Initialize config directory
    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()
    rprint(f"[green]✓[/green] Config directory: {cfg_mgr.config_dir}")
    rprint(f"[green]✓[/green] Config file:      {cfg_mgr.config_path}")

    # 2. Check CLI installations
    cli_status = check_all_clis()
    table = Table(title="\nCLI Detection", show_header=True)
    table.add_column("Provider", style="cyan")
    table.add_column("CLI", style="white")
    table.add_column("Status", style="white")

    missing: list[str] = []
    for provider, installed in cli_status.items():
        status = "[green]✓ Installed[/green]" if installed else "[yellow]✗ Not found[/yellow]"
        table.add_row(provider, f"{provider} CLI", status)
        if not installed:
            missing.append(provider)

    console.print(table)

    # 3. Install missing CLIs if requested
    if missing and install:
        if not npm_available():
            rprint("\n[yellow]Warning:[/yellow] npm not found. Cannot auto-install CLIs.")
            rprint("Install Node.js from https://nodejs.org/ and re-run with --install")
        else:
            rprint(f"\nInstalling {len(missing)} missing CLI(s)...")
            for provider in missing:
                rprint(f"  Installing {provider}...", end=" ")
                ok = install_cli(provider)
                rprint("[green]done[/green]" if ok else "[red]failed[/red]")
    elif missing:
        rprint(f"\n[dim]Tip: run [cyan]uai setup --install[/cyan] to auto-install missing CLIs[/dim]")

    # 4. Summary
    rprint("\n[bold]Next steps:[/bold]")
    rprint("  [cyan]uai connect gemini[/cyan]   — connect Gemini account (free)")
    rprint("  [cyan]uai connect qwen[/cyan]     — connect Qwen Code (free, 1000 req/day)")
    rprint("  [cyan]uai connect claude[/cyan]   — connect Claude (paid)")
    rprint("  [cyan]uai connect codex[/cyan]    — connect Codex (paid)")
    rprint("  [cyan]uai ask \"hello\"[/cyan]      — make your first request")
    rprint("  [cyan]uai status[/cyan]           — check provider status")
    rprint("\n[green]Setup complete![/green]")
