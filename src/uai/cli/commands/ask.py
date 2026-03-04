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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show extra routing details"),
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
    from uai.cli.streaming import stream_to_live, StreamStatus
    from rich.text import Text

    executor = RequestExecutor.create_default()

    # Expand @file and !shell references in the prompt
    expanded_prompt, warnings = await expand_input(prompt)
    for w in warnings:
        rprint(f"[yellow]Warning: {w}[/yellow]")

    if verbose:
        rprint(f"[dim]Session: {session} | Free-only: {free} | Context: {not no_context}[/dim]")

    request = UAIRequest(
        prompt=expanded_prompt,
        provider=provider,
        model=model,
        session_name=session,
        free_only=free,
        use_context=not no_context,
    )

    timing: dict = {}
    status = StreamStatus()

    def _resolve_model(decision) -> str:
        alias = decision.model
        try:
            from uai.providers import get_provider_class
            prov_cls = get_provider_class(decision.provider)
            if alias is None:
                alias = getattr(prov_cls, "DEFAULT_MODEL", None)
            models = getattr(prov_cls, "MODELS", {})
            if alias and alias in models:
                return models[alias].get("id", alias)
        except Exception:
            pass
        return alias or "default"

    def on_status(event: str, *args) -> None:
        if event == "routing":
            decision, routing_s = args[0], args[1]
            timing["routing_s"] = routing_s

            backend = decision.backend.value.upper()   # "CLI" or "API"
            model_display = _resolve_model(decision)
            task_tag = decision.task_type.value.replace("_", " ")
            reason = decision.reason or ""
            complexity = ""
            for tag in ("[simple]", "[medium]", "[complex]"):
                if tag in reason:
                    complexity = f" · {tag[1:-1]}"
                    break
            long_ctx = " · long-ctx" if "[long-ctx]" in reason else ""
            free_tag = "  [green][free][/green]" if "[free]" in reason else ""

            # Use Text.from_markup — plain str is wrapped in Text(...) WITHOUT markup parsing
            status.spinner.text = Text.from_markup(
                f" → [cyan]{decision.provider} {backend}[/cyan] · {model_display}"
                f"  [dim][{task_tag}{complexity}{long_ctx}][/dim]{free_tag}"
            )
            if verbose and decision.alternatives:
                status.lines.append(
                    f"[dim]  alternatives: {', '.join(decision.alternatives)}[/dim]"
                )

        elif event == "fallback":
            from_prov, error, to_prov = args[0], args[1], args[2]
            err_short = str(error)[:80]
            line = f"[dim red]  ✗ {from_prov}:[/dim red] [dim]{err_short}[/dim]"
            if to_prov:
                line += f"[yellow] → tentando {to_prov}...[/yellow]"
                status.spinner.text = Text.from_markup(
                    f" ↪ [yellow]{to_prov}[/yellow] · aguardando..."
                )
            else:
                line += "[dim red] (sem mais provedores)[/dim red]"
            status.lines.append(line)

    try:
        if raw:
            # Raw mode: print tokens directly without markdown rendering
            async for token in executor.execute_stream(request, on_status=on_status):
                typer.echo(token, nl=False)
            typer.echo()
        else:
            await stream_to_live(
                executor.execute_stream(request, on_status=on_status),
                console,
                live_status=status,
                timing=timing,
            )

        routing_s = timing.get("routing_s", 0.0)
        ttft_s = timing.get("ttft_s", 0.0)
        stream_s = timing.get("stream_s", 0.0)
        total_s = timing.get("total_s", 0.0)
        rprint(
            f"[dim]  ⏱ routing {routing_s:.1f}s"
            f" · 1º token {ttft_s:.1f}s"
            f" · streaming {stream_s:.1f}s"
            f" · total {total_s:.1f}s[/dim]"
        )

    except Exception as e:
        from uai.core.errors import UAIError
        if isinstance(e, UAIError):
            rprint(e.rich_format())
        else:
            rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
