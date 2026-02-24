"""uai ask "prompt" — single query with context and intelligent routing."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
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
    from uai.cli.input_expander import expand_input
    from uai.cli.streaming import stream_to_live

    executor = RequestExecutor()

    # Expand @file and !shell references in the prompt
    expanded_prompt, warnings = await expand_input(prompt)
    for w in warnings:
        rprint(f"[yellow]Warning: {w}[/yellow]")

    request = UAIRequest(
        prompt=expanded_prompt,
        provider=provider,
        model=model,
        session_name=session,
        free_only=free,
        use_context=not no_context,
    )

    if verbose:
        rprint(f"[dim]Session: {session} | Free-only: {free} | Context: {not no_context}[/dim]")

    try:
        if raw:
            # Raw mode: print tokens directly without markdown rendering
            async for token in executor.execute_stream(request):
                typer.echo(token, nl=False)
            typer.echo()
        else:
            await stream_to_live(executor.execute_stream(request), console)
    except Exception as e:
        from uai.core.errors import UAIError
        if isinstance(e, UAIError):
            rprint(e.rich_format())
        else:
            rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
