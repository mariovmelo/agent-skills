"""uai orchestrate "task" — multi-AI team orchestration."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich import print as rprint

console = Console()


def orchestrate(
    task: str = typer.Argument(..., help="Task to orchestrate across multiple AI providers"),
    pattern: str = typer.Option(None, "--pattern", "-p", help="Team pattern to use"),
    autonomous: bool = typer.Option(False, "--autonomous", "-a", help="Skip confirmations"),
    list_patterns: bool = typer.Option(False, "--list", "-l", help="List available patterns"),
) -> None:
    """Orchestrate a task across multiple AI providers using team patterns."""
    if list_patterns:
        _show_patterns()
        return
    asyncio.run(_orchestrate(task, pattern, autonomous))


def _show_patterns() -> None:
    from uai.orchestration.patterns import PATTERNS

    table = Table(title="Team Patterns", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan", width=22)
    table.add_column("Cost", width=12)
    table.add_column("Execution", width=12)
    table.add_column("Description", width=50)

    for name, p in PATTERNS.items():
        cost_colors = {
            "free": "[green]free[/green]",
            "mostly_free": "[green]mostly free[/green]",
            "mixed": "[yellow]mixed[/yellow]",
            "paid": "[red]paid[/red]",
        }
        table.add_row(name, cost_colors.get(p.cost_estimate, p.cost_estimate), p.execution, p.description)
    console.print(table)
    rprint("\n[dim]Use: uai orchestrate \"task\" --pattern <name>[/dim]")


async def _orchestrate(task: str, pattern_name: str | None, autonomous: bool) -> None:
    from uai.core.config import ConfigManager
    from uai.core.auth import AuthManager
    from uai.core.quota import QuotaTracker
    from uai.orchestration.patterns import PATTERNS, list_patterns as lp
    from uai.orchestration.team import TeamBuilder
    from uai.orchestration.cost_guard import CostGuard, CostMode

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()
    auth = AuthManager(cfg_mgr.config_dir)
    quota = QuotaTracker(cfg_mgr.config_dir / "quota.db")
    builder = TeamBuilder(cfg_mgr, auth, quota)
    guard = CostGuard()

    # Auto-select pattern if not specified
    if not pattern_name:
        pattern_name = _auto_select_pattern(task)
        rprint(f"[dim]Auto-selected pattern: [cyan]{pattern_name}[/cyan][/dim]")

    p = PATTERNS.get(pattern_name)
    if not p:
        available = ", ".join(lp())
        rprint(f"[red]Unknown pattern: {pattern_name}[/red]")
        rprint(f"Available: {available}")
        raise typer.Exit(1)

    # Cost guard
    mode = guard.classify(p.roles, user_said_autonomous=autonomous)

    if mode != CostMode.FREE and mode != CostMode.AUTONOMOUS:
        ok = guard.request_approval(p, task, mode)
        if not ok:
            rprint("[dim]Cancelled.[/dim]")
            return

    # Execute
    result = await builder.execute(p, task)

    # Report
    rprint(f"\n[bold cyan]{'='*60}[/bold cyan]")
    rprint(f"[bold]Orchestration Complete[/bold]: {p.name}")
    rprint(f"[dim]Total time: {result.execution_ms:.0f}ms | Cost: ${result.total_cost_usd:.4f}[/dim]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Role", style="cyan")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("Latency")

    for r in result.role_results:
        status = "[green]✓[/green]" if r.status == "ok" else "[red]✗[/red]"
        table.add_row(r.role, r.provider, status, f"{r.latency_ms:.0f}ms")
    console.print(table)

    rprint(f"\n[bold]Consolidated Report:[/bold]")
    console.print(Markdown(result.consolidated))


def _auto_select_pattern(task: str) -> str:
    lower = task.lower()
    if any(k in lower for k in ["bug", "debug", "error", "crash"]):
        return "critical_debug"
    if any(k in lower for k in ["privacy", "lgpd", "gdpr", "pii"]):
        return "lgpd_audit"
    if any(k in lower for k in ["review", "full", "complete", "all"]):
        return "full_analysis"
    if any(k in lower for k in ["brainstorm", "idea", "perspective", "approach"]):
        return "brainstorm"
    if any(k in lower for k in ["batch", "bulk", "list", "items"]):
        return "batch_processing"
    return "daily_dev"
