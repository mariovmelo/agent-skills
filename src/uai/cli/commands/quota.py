"""uai quota — usage and cost report."""
from __future__ import annotations
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def quota() -> None:
    """Show quota usage, costs, and rate limits across all providers."""
    from uai.core.executor import RequestExecutor

    executor = RequestExecutor.create_default()
    cfg = executor.config.load()
    snapshots = executor.quota.get_all_snapshots(cfg.providers)

    table = Table(title="Usage Report", show_header=True, header_style="bold cyan")
    table.add_column("Provider", style="cyan", width=12)
    table.add_column("Today", width=10)
    table.add_column("Month", width=10)
    table.add_column("Tokens Today", width=12)
    table.add_column("Tokens Month", width=12)
    table.add_column("Cost (Month)", width=14)
    table.add_column("Daily Limit", width=12)
    table.add_column("Success 24h", width=12)
    table.add_column("Status", width=12)

    total_cost = 0.0
    total_tokens_today = 0
    total_tokens_month = 0
    for snap in snapshots:
        limit_str = str(snap.daily_limit) if snap.daily_limit else "∞"

        if snap.daily_limit:
            pct = snap.requests_today / snap.daily_limit * 100
            if pct >= 80:
                limit_str = f"[red]{snap.requests_today}/{snap.daily_limit}[/red]"
            elif pct >= 50:
                limit_str = f"[yellow]{snap.requests_today}/{snap.daily_limit}[/yellow]"
            else:
                limit_str = f"[green]{snap.requests_today}/{snap.daily_limit}[/green]"

        cost_str = "[green]free[/green]" if snap.cost_month_usd == 0 else f"${snap.cost_month_usd:.4f}"
        success_str = f"{snap.success_rate_24h * 100:.0f}%"
        status = "[yellow]cooldown[/yellow]" if snap.in_cooldown else ("[green]ok[/green]" if snap.success_rate_24h >= 0.8 else "[red]degraded[/red]")

        table.add_row(
            snap.provider,
            str(snap.requests_today),
            str(snap.requests_month),
            str(snap.tokens_today),
            str(snap.tokens_month),
            cost_str,
            limit_str,
            success_str,
            status,
        )
        total_cost += snap.cost_month_usd
        total_tokens_today += snap.tokens_today
        total_tokens_month += snap.tokens_month

    console.print(table)

    if total_cost > 0:
        rprint(f"\n[bold]Total monthly cost: [yellow]${total_cost:.4f}[/yellow][/bold]")
    else:
        rprint(f"\n[bold]Total monthly cost: [green]$0.00 (all free)[/green][/bold]")

    rprint(f"\n[bold]Total tokens today: [cyan]{total_tokens_today:,}[/cyan][/bold]")
    rprint(f"[bold]Total tokens this month: [cyan]{total_tokens_month:,}[/cyan][/bold]")

    threshold = cfg.quota.alert_threshold_usd
    if total_cost >= threshold:
        rprint(f"[red]⚠ Alert: monthly cost (${total_cost:.2f}) exceeds threshold (${threshold:.2f})[/red]")
