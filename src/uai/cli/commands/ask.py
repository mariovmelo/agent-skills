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
    apply: bool = typer.Option(False, "--apply", help="Apply suggested file changes automatically"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Show detailed debug trace of providers, errors and timings"),
) -> None:
    """Ask a question. Routes intelligently across all configured AI providers."""
    asyncio.run(_ask(prompt, provider, model, session, free, no_context, raw, verbose, apply, debug))


async def _ask(
    prompt: str,
    provider: str | None,
    model: str | None,
    session: str,
    free: bool,
    no_context: bool,
    raw: bool,
    verbose: bool,
    apply: bool = False,
    debug: bool = False,
) -> None:
    import time as _time
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
    chosen_file_access: list[str] = ["readwrite"]  # mutable container to capture from callback

    # Debug trace: list of dicts with event details
    _debug_trace: list[dict] = []
    _debug_t0 = _time.monotonic()

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
        elapsed = _time.monotonic() - _debug_t0

        if event == "routing":
            decision, routing_s = args[0], args[1]
            timing["routing_s"] = routing_s
            chosen_file_access[0] = getattr(decision, "file_access", "readwrite")

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
            ro_tag = "  [yellow][ro][/yellow]" if getattr(decision, "file_access", "readwrite") == "readonly" else ""

            # Use Text.from_markup — plain str is wrapped in Text(...) WITHOUT markup parsing
            status.spinner.text = Text.from_markup(
                f" → [cyan]{decision.provider} {backend}[/cyan] · {model_display}"
                f"  [dim][{task_tag}{complexity}{long_ctx}][/dim]{free_tag}{ro_tag}"
            )
            if verbose and decision.alternatives:
                status.lines.append(
                    f"[dim]  alternatives: {', '.join(decision.alternatives)}[/dim]"
                )
            if debug:
                _debug_trace.append({
                    "event": "routing",
                    "elapsed_s": elapsed,
                    "routing_s": routing_s,
                    "provider": decision.provider,
                    "model": model_display,
                    "backend": backend,
                    "task_type": task_tag,
                    "reason": reason,
                    "alternatives": decision.alternatives,
                    "file_access": getattr(decision, "file_access", "readwrite"),
                })

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
            if debug:
                _debug_trace.append({
                    "event": "fallback",
                    "elapsed_s": elapsed,
                    "from_provider": from_prov,
                    "error": str(error),
                    "next_provider": to_prov,
                })

        elif event == "attempt":
            # New event: provider attempt started
            if debug:
                _debug_trace.append({
                    "event": "attempt",
                    "elapsed_s": elapsed,
                    "provider": args[0],
                    "attempt": args[1] if len(args) > 1 else 1,
                    "backend": args[2] if len(args) > 2 else "?",
                })

        elif event == "retry":
            # New event: retry after transient error
            if debug:
                _debug_trace.append({
                    "event": "retry",
                    "elapsed_s": elapsed,
                    "provider": args[0],
                    "attempt": args[1] if len(args) > 1 else "?",
                    "error": args[2] if len(args) > 2 else "?",
                    "wait_s": args[3] if len(args) > 3 else 0,
                })

        elif event == "backend_switch":
            if debug:
                _debug_trace.append({
                    "event": "backend_switch",
                    "elapsed_s": elapsed,
                    "provider": args[0],
                    "from_backend": args[1] if len(args) > 1 else "?",
                    "to_backend": args[2] if len(args) > 2 else "cli",
                })

    # Resolve effective edit mode: --apply flag overrides config
    cfg_edit_mode = executor.config.load().ux.edit_mode
    effective_edit_mode = "apply" if apply else cfg_edit_mode

    try:
        full_response = ""
        if raw:
            # Raw mode: print tokens directly without markdown rendering
            async for token in executor.execute_stream(request, on_status=on_status):
                typer.echo(token, nl=False)
                full_response += token
            typer.echo()
        else:
            full_response = await stream_to_live(
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

        # Handle diffs in the response
        from uai.cli.edit_applier import parse_edit_plan, show_edit_plan, apply_edit_plan
        plan = parse_edit_plan(full_response)
        if not plan.is_empty:
            provider_is_readonly = chosen_file_access[0] == "readonly"
            if effective_edit_mode == "apply" and not provider_is_readonly:
                apply_edit_plan(plan, console, confirm=True)
            else:
                if provider_is_readonly and effective_edit_mode == "apply":
                    rprint("[yellow]  ⚠ Provedor em modo leitura (file_access: readonly) — modificações de arquivo bloqueadas.[/yellow]")
                show_edit_plan(plan, console)

    except Exception as e:
        from uai.core.errors import UAIError
        from uai.core.fallback import AllProvidersFailedError
        if debug:
            _print_debug_panel(_debug_trace, _time.monotonic() - _debug_t0, error=e)
        if isinstance(e, UAIError):
            rprint(e.rich_format())
        elif isinstance(e, AllProvidersFailedError):
            rprint(f"[red]Error: {e}[/red]")
        else:
            rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if debug:
        _print_debug_panel(_debug_trace, _time.monotonic() - _debug_t0)


def _print_debug_panel(trace: list[dict], total_s: float, error: Exception | None = None) -> None:
    """Render a Rich panel with the full debug trace."""
    from rich.panel import Panel
    from rich.table import Table
    from rich import print as rprint

    table = Table.grid(padding=(0, 1))
    table.add_column(style="dim", width=7)   # elapsed
    table.add_column(style="bold", width=14) # event
    table.add_column()                        # details

    for ev in trace:
        t = f"+{ev['elapsed_s']:.2f}s"
        name = ev["event"]

        if name == "routing":
            details = (
                f"[cyan]{ev['provider']}[/cyan] {ev['backend']} · {ev['model']}"
                f"  [{ev['task_type']}]  routing={ev['routing_s']:.2f}s"
                f"  file_access={ev['file_access']}"
            )
            if ev.get("alternatives"):
                details += f"\n  [dim]alternatives: {', '.join(ev['alternatives'])}[/dim]"
            if ev.get("reason"):
                details += f"\n  [dim]reason: {ev['reason']}[/dim]"
            table.add_row(t, "[green]ROUTING[/green]", details)

        elif name == "attempt":
            details = f"[cyan]{ev['provider']}[/cyan] attempt #{ev['attempt']} via {ev['backend']}"
            table.add_row(t, "[blue]ATTEMPT[/blue]", details)

        elif name == "fallback":
            next_p = ev.get("next_provider")
            details = (
                f"[red]{ev['from_provider']}[/red] failed\n"
                f"  [dim]{ev['error']}[/dim]"
            )
            if next_p:
                details += f"\n  → trying [yellow]{next_p}[/yellow]"
            table.add_row(t, "[red]FALLBACK[/red]", details)

        elif name == "retry":
            details = (
                f"[yellow]{ev['provider']}[/yellow] attempt {ev['attempt']}"
                f"  error: {ev['error']}"
                f"  wait={ev['wait_s']}s"
            )
            table.add_row(t, "[yellow]RETRY[/yellow]", details)

        elif name == "backend_switch":
            details = (
                f"[yellow]{ev['provider']}[/yellow]"
                f" {ev['from_backend']} → {ev['to_backend']}"
            )
            table.add_row(t, "[yellow]BKND SW[/yellow]", details)

    status_line = f"[green]OK[/green]  total={total_s:.2f}s" if error is None else f"[red]FAILED[/red]  {error}"
    table.add_row(f"+{total_s:.2f}s", "[bold]DONE[/bold]", status_line)

    from rich.console import Console
    Console().print(Panel(table, title="[bold]uai debug trace[/bold]", border_style="dim"))
