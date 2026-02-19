"""uai ask "prompt" — single query with context and intelligent routing."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich import print as rprint

console = Console()


def ask(
    prompt: str = typer.Argument(..., help="Your question or task"),
    provider: str = typer.Option(None, "--provider", "-p", help="Force a specific provider"),
    model: str = typer.Option(None, "--model", "-m", help="Force a specific model"),
    session: str = typer.Option("default", "--session", "-s", help="Session name for context"),
    free: bool = typer.Option(False, "--free", help="Use only free providers"),
    no_context: bool = typer.Option(False, "--no-context", help="Ignore session history"),
    raw: bool = typer.Option(False, "--raw", help="Print raw text without markdown rendering"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show routing details"),
) -> None:
    """Ask a question. Routes intelligently across all configured AI providers."""
    asyncio.run(_ask(prompt, provider, model, session, free, no_context, raw, verbose))


async def _ask(
    prompt: str,
    provider: str | None,
    model: str | None,
    session: str,
    free: bool,
    no_context: bool,
    raw: bool,
    verbose: bool,
) -> None:
    from uai.core.executor import RequestExecutor
    from uai.models.request import UAIRequest

    executor = RequestExecutor()

    request = UAIRequest(
        prompt=prompt,
        provider=provider,
        model=model,
        session_name=session,
        free_only=free,
        use_context=not no_context,
    )

    if verbose:
        rprint(f"[dim]Session: {session} | Free-only: {free} | Context: {not no_context}[/dim]")

    try:
        response = await executor.execute(request)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if verbose:
        provider_tag = f"[cyan]{response.provider}[/cyan]/[dim]{response.model}[/dim]"
        cost_tag = f"[green]free[/green]" if not response.cost_usd else f"${response.cost_usd:.4f}"
        latency_tag = f"[dim]{response.latency_ms:.0f}ms[/dim]"
        fallback_tag = f" [yellow](fallback: {', '.join(response.providers_tried)})[/yellow]" if response.fallback_used else ""
        rprint(f"\n{provider_tag} {cost_tag} {latency_tag}{fallback_tag}\n")

    if raw:
        typer.echo(response.text)
    else:
        console.print(Markdown(response.text))
