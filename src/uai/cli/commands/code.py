"""uai code "task" — code-specific task with bias toward code providers."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich import print as rprint

console = Console()


def code(
    task: str = typer.Argument(..., help="Code task description"),
    provider: str = typer.Option(None, "--provider", "-p", help="Force a specific provider"),
    session: str = typer.Option("default", "--session", "-s", help="Session name"),
    free: bool = typer.Option(False, "--free", help="Use only free providers"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Execute a code-specific task. Routes to the best coding provider."""
    asyncio.run(_code(task, provider, session, free, verbose))


async def _code(
    task: str,
    provider: str | None,
    session: str,
    free: bool,
    verbose: bool,
) -> None:
    from uai.core.executor import RequestExecutor
    from uai.models.request import UAIRequest
    from uai.models.provider import TaskCapability

    # Classify the coding task for better routing
    lower = task.lower()
    if any(kw in lower for kw in ["bug", "error", "fix", "debug", "exception"]):
        task_type = TaskCapability.DEBUGGING
    elif any(kw in lower for kw in ["review", "audit", "check", "improve"]):
        task_type = TaskCapability.CODE_REVIEW
    elif any(kw in lower for kw in ["architect", "design", "structure", "refactor"]):
        task_type = TaskCapability.ARCHITECTURE
    else:
        task_type = TaskCapability.CODE_GENERATION

    executor = RequestExecutor.create_default()
    request = UAIRequest(
        prompt=task,
        provider=provider,
        session_name=session,
        task_type=task_type,
        free_only=free,
        use_context=True,
    )

    if verbose:
        rprint(f"[dim]Task type: {task_type.value}[/dim]")

    try:
        response = await executor.execute(request)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if verbose:
        rprint(f"[dim]{response.provider}/{response.model} | {response.latency_ms:.0f}ms[/dim]\n")

    console.print(Markdown(response.text))
