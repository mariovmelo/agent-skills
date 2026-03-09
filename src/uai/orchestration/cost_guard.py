"""
CostGuard — implements the 5 operational modes from SKILL.md.

Modes:
  free       → Execute, inform after
  paid       → Show plan + estimated cost, wait for OK
  sensitive  → Always ask, suggest anonymization
  batch      → Run 2-3 as test, show result, ask to continue
  autonomous → Execute everything, report at end
"""
from __future__ import annotations
from enum import Enum
from typing import Callable

import typer
from rich import print as rprint

from uai.orchestration.patterns import TeamPattern, TeamRole


class CostMode(str, Enum):
    FREE       = "free"
    PAID       = "paid"
    SENSITIVE  = "sensitive"
    BATCH      = "batch"
    AUTONOMOUS = "autonomous"


class CostGuard:
    def classify(
        self,
        roles: list[TeamRole],
        has_sensitive_data: bool = False,
        batch_size: int = 0,
        user_said_autonomous: bool = False,
    ) -> CostMode:
        if user_said_autonomous:
            return CostMode.AUTONOMOUS
        if has_sensitive_data:
            return CostMode.SENSITIVE
        if batch_size > 10:
            return CostMode.BATCH
        all_free = all(r.is_free for r in roles)
        if all_free:
            return CostMode.FREE
        return CostMode.PAID

    def request_approval(
        self,
        pattern: TeamPattern,
        task: str,
        mode: CostMode,
    ) -> bool:
        """
        Request user approval if needed.
        Returns True if execution should proceed, False if user cancelled.
        """
        if mode in (CostMode.FREE, CostMode.AUTONOMOUS):
            return True  # No approval needed

        free_providers = [r.provider for r in pattern.roles if r.is_free]
        paid_providers = [r.provider for r in pattern.roles if not r.is_free]

        rprint(f"\n[bold]Orchestration Plan:[/bold] {pattern.name}")
        rprint(f"[dim]Task:[/dim] {task[:100]}{'...' if len(task) > 100 else ''}")
        rprint(f"\n[bold]Team:[/bold]")
        for role in pattern.roles:
            cost_tag = "[green]free[/green]" if role.is_free else "[yellow]paid[/yellow]"
            rprint(f"  • {role.role:<20} → [cyan]{role.provider}[/cyan] {cost_tag}")
        rprint(f"\n[bold]Execution:[/bold] {pattern.execution}")
        rprint(f"[bold]Costs:[/bold]")
        rprint(f"  Free:  {free_providers or ['none']}")
        rprint(f"  Paid:  {paid_providers or ['none']}")

        if mode == CostMode.SENSITIVE:
            rprint(f"\n[red]⚠ Sensitive data detected.[/red] Ensure data is anonymized before proceeding.")

        return typer.confirm("\nProceed?", default=True)
