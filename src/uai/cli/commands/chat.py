"""uai chat — interactive conversation session with persistent context (REPL)."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich import print as rprint

console = Console()


def _make_on_status(status, timing: dict):
    """
    Build an on_status callback that populates a StreamStatus for stream_to_live()
    and records per-phase timing into `timing`.

    Events from execute_stream():
      "routing"  decision, routing_s        — updates spinner; records routing_s
      "fallback" from_prov, error, to_prov  — queues a warning line; updates spinner
    """
    from rich.text import Text

    def _resolve_model(decision) -> str:
        """Return the most readable model label for display."""
        alias = decision.model  # may be None → provider default
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
            ro_tag = "  [yellow][ro][/yellow]" if getattr(decision, "access", "readwrite") == "readonly" else ""

            # Use Text.from_markup — plain str is wrapped in Text(...) WITHOUT markup parsing
            status.spinner.text = Text.from_markup(
                f" → [cyan]{decision.provider} {backend}[/cyan] · {model_display}"
                f"  [dim][{task_tag}{complexity}{long_ctx}][/dim]{free_tag}{ro_tag}"
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

    return on_status


def chat(
    session: str = typer.Option("default", "--session", "-s", help="Session name"),
    provider: str = typer.Option(None, "--provider", "-p", help="Force a specific provider"),
    free: bool = typer.Option(False, "--free", help="Use only free providers"),
    new: bool = typer.Option(False, "--new", help="Start a fresh session (clears history)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume the most recent session"),
) -> None:
    """
    Start an interactive chat session with persistent context.

    Your conversation is saved across sessions. Switch providers mid-chat
    with /provider <name>. Type /help for all commands.
    """
    asyncio.run(_chat(session, provider, free, new, resume))


async def _chat(
    session_name: str,
    forced_provider: str | None,
    free: bool,
    new: bool,
    resume: bool,
) -> None:
    from uai.core.executor import RequestExecutor
    from uai.models.request import UAIRequest
    from uai.cli.slash_commands import build_default_registry, ChatContext
    from uai.cli.streaming import stream_to_live
    from uai.cli.input_handler import make_prompt_session, get_user_input
    from uai.cli.input_expander import expand_input

    executor = RequestExecutor.create_default()

    # --resume: find most recent session
    if resume:
        sessions = executor.context.list_sessions()
        if sessions:
            session_name = sessions[0].name
            rprint(f"[dim]Resuming session: [yellow]{session_name}[/yellow][/dim]")

    session = executor.context.get_session(session_name)

    if new:
        executor.context.clear_messages(session)
        rprint(f"[dim]Session '{session_name}' cleared.[/dim]")

    msgs = executor.context.get_messages(session)
    rprint(f"\n[bold cyan]UAI Chat[/bold cyan] — session: [yellow]{session_name}[/yellow]")
    rprint(f"[dim]{len(msgs)} messages in history. Type /help for commands, Ctrl+C or /exit to quit.[/dim]\n")

    current_provider = forced_provider

    # Setup slash command registry
    registry = build_default_registry()
    ctx = ChatContext(
        session_name=session_name,
        executor=executor,
        session=session,
        console=console,
        current_provider=current_provider,
        free=free,
    )

    # Setup prompt_toolkit session
    history_path = executor.config.config_dir / "chat_history"
    pt_session = make_prompt_session(history_path, extra_commands=registry.all_names())

    while True:
        try:
            provider_label = current_provider or "auto"
            user_input = await get_user_input(pt_session, provider_label)
        except (KeyboardInterrupt, EOFError):
            rprint("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # Handle slash commands via registry
        if user_input.startswith("/"):
            ctx.current_provider = current_provider
            result = await registry.dispatch(user_input, ctx)
            if result == "exit":
                break
            if result and result.startswith("provider:"):
                current_provider = result.split(":", 1)[1] or None
                ctx.current_provider = current_provider
            elif result and result.startswith("session:"):
                new_name = result.split(":", 1)[1]
                if new_name:
                    session_name = new_name
                    session = executor.context.get_session(session_name)
                    ctx.session_name = session_name
                    ctx.session = session
                    msgs = executor.context.get_messages(session)
                    rprint(
                        f"[dim]Switched to session: [yellow]{session_name}[/yellow]"
                        f" ({len(msgs)} messages)[/dim]"
                    )
            continue

        # Expand @file and !shell references
        expanded_prompt, warnings = await expand_input(user_input)
        for w in warnings:
            rprint(f"[yellow]Warning: {w}[/yellow]")

        # Execute request with streaming
        request = UAIRequest(
            prompt=expanded_prompt,
            provider=current_provider,
            session_name=session_name,
            free_only=free,
            use_context=True,
        )

        try:
            from uai.cli.streaming import StreamStatus
            timing: dict = {}
            status = StreamStatus()
            rprint()  # blank line before spinner
            full_text = await stream_to_live(
                executor.execute_stream(request, on_status=_make_on_status(status, timing)),
                console,
                live_status=status,
                timing=timing,
            )
            routing_s = timing.get("routing_s", 0.0)
            ttft_s = timing.get("ttft_s", 0.0)
            stream_s = timing.get("stream_s", 0.0)
            total_s = timing.get("total_s", 0.0)
            tokens_est = len(full_text) // 4
            rprint(
                f"[dim]  ⏱ routing {routing_s:.1f}s"
                f" · 1º token {ttft_s:.1f}s"
                f" · streaming {stream_s:.1f}s"
                f" · total {total_s:.1f}s"
                f" · ~{tokens_est} tokens[/dim]"
            )

            # Handle diffs embedded in response
            from uai.cli.edit_applier import parse_edit_plan, show_edit_plan, apply_edit_plan
            plan = parse_edit_plan(full_text)
            if not plan.is_empty:
                edit_mode = executor.config.load().ux.edit_mode
                if edit_mode == "apply":
                    apply_edit_plan(plan, console, confirm=True)
                else:
                    show_edit_plan(plan, console)

        except Exception as e:
            from uai.core.errors import UAIError
            if isinstance(e, UAIError):
                rprint(e.rich_format())
            else:
                rprint(f"[red]Error: {e}[/red]")
            continue
