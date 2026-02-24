"""uai status — provider health dashboard."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed info"),
) -> None:
    """Show health status of all configured AI providers."""
    asyncio.run(_status(verbose))


async def _status(verbose: bool) -> None:
    from uai.core.executor import RequestExecutor
    from uai.models.provider import ProviderStatus
    from uai.utils.installer import check_all_clis

    executor = RequestExecutor()
    cfg = executor.config.load()
    cli_status = check_all_clis()

    table = Table(title="Provider Status", show_header=True, header_style="bold cyan")
    table.add_column("Provider", style="cyan", width=12)
    table.add_column("Status", width=16)
    table.add_column("Backend", width=10)
    table.add_column("CLI", width=10)
    table.add_column("Model", width=22)
    table.add_column("Cost", width=8)

    results = await asyncio.gather(*[
        _check_one(name, executor, cfg)
        for name, pcfg in cfg.providers.items()
        if pcfg.enabled
    ], return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            continue
        name, status_str, backend, model, is_free = result
        cli_installed = "✓" if cli_status.get(name) else "✗"
        cli_color = "green" if cli_status.get(name) else "dim"
        cost = "[green]free[/green]" if is_free else "[yellow]paid[/yellow]"
        table.add_row(name, status_str, backend, f"[{cli_color}]{cli_installed}[/{cli_color}]", model or "-", cost)

    console.print(table)

    # Show project-level config and UAI.md status
    try:
        from uai.core.project_context import find_project_instructions, find_project_config
        instructions = find_project_instructions()
        project_cfg = find_project_config()
        if instructions:
            rprint(f"[dim]Project instructions: [cyan]UAI.md[/cyan] loaded ({len(instructions)} chars)[/dim]")
        if project_cfg:
            rprint(f"[dim]Project config: [cyan]{project_cfg}[/cyan][/dim]")
    except Exception:
        pass

    total_cost = executor.quota.total_cost_month()
    if total_cost > 0:
        rprint(f"\n[dim]Total cost this month: [yellow]${total_cost:.4f}[/yellow][/dim]")

    rprint(f"\n[dim]Run [cyan]uai quota[/cyan] for detailed usage. [cyan]uai connect <provider>[/cyan] to add a provider.[/dim]")


async def _check_one(name: str, executor, cfg) -> tuple:
    from uai.models.provider import ProviderStatus
    from uai.providers import get_provider_class

    prov = executor.providers.get(name)
    prov_cfg = cfg.providers.get(name)

    try:
        cls = get_provider_class(name)
        is_free = cls.is_free
    except Exception:
        is_free = False

    if prov is None:
        return (name, "[dim]disabled[/dim]", "-", "-", is_free)

    try:
        health = await asyncio.wait_for(prov.health_check(), timeout=8)
        status_map = {
            ProviderStatus.AVAILABLE:      "[green]● available[/green]",
            ProviderStatus.NOT_CONFIGURED: "[yellow]○ not configured[/yellow]",
            ProviderStatus.RATE_LIMITED:   "[red]● rate limited[/red]",
            ProviderStatus.AUTH_ERROR:     "[red]● auth error[/red]",
            ProviderStatus.UNAVAILABLE:    "[red]○ unavailable[/red]",
            ProviderStatus.COOLDOWN:       "[yellow]⏸ cooldown[/yellow]",
        }
        status_str = status_map.get(health, str(health))
    except Exception:
        status_str = "[red]○ timeout[/red]"

    backend = getattr(prov_cfg, "preferred_backend", "api")
    model = getattr(prov_cfg, "default_model", None)
    return (name, status_str, backend, model, is_free)
