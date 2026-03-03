"""Registry-based slash command system for the UAI chat REPL."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from rich.console import Console
from rich.table import Table


# Handler signature: (args: str, ctx: ChatContext) -> str | None
# Return "exit" to quit, "provider:<name>" to switch provider,
# "session:<name>" to switch session, else "handled"/None
HandlerFn = Callable[[str, "ChatContext"], Awaitable[str | None]]


@dataclass
class SlashCommand:
    name: str           # registered name (without leading /)
    handler: HandlerFn
    description: str
    aliases: list[str] = field(default_factory=list)
    usage: str = ""


@dataclass
class ChatContext:
    """Mutable state passed to every slash command handler."""
    session_name: str
    executor: object        # RequestExecutor
    session: object         # Session
    console: Console
    current_provider: str | None = None
    free: bool = False


class SlashCommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, cmd: SlashCommand) -> None:
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._commands[alias] = cmd

    def get(self, name: str) -> SlashCommand | None:
        return self._commands.get(name.lstrip("/"))

    def all_names(self) -> list[str]:
        """Return sorted list of all unique command names with leading /."""
        seen_ids: set[int] = set()
        names: list[str] = []
        for name, cmd in self._commands.items():
            if id(cmd) not in seen_ids:
                seen_ids.add(id(cmd))
                names.append(f"/{cmd.name}")
        return sorted(names)

    async def dispatch(self, raw_input: str, ctx: ChatContext) -> str | None:
        parts = raw_input.strip().split(maxsplit=1)
        name = parts[0].lower().lstrip("/")
        args = parts[1] if len(parts) > 1 else ""
        cmd = self._commands.get(name)
        if cmd is None:
            ctx.console.print(
                f"[yellow]Unknown command: {raw_input}. Type /help for help.[/yellow]"
            )
            return "handled"
        return await cmd.handler(args, ctx)

    def print_help(self, console: Console) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Command", style="cyan", min_width=26)
        table.add_column("Description")

        seen_ids: set[int] = set()
        for _, cmd in sorted(self._commands.items()):
            if id(cmd) in seen_ids:
                continue
            seen_ids.add(id(cmd))
            alias_str = (
                f"  [dim]({', '.join('/' + a for a in cmd.aliases)})[/dim]"
                if cmd.aliases else ""
            )
            usage_str = f"  [dim]{cmd.usage}[/dim]" if cmd.usage else ""
            table.add_row(
                f"/{cmd.name}{alias_str}",
                f"{cmd.description}{usage_str}",
            )

        console.print("\n[bold]Slash commands:[/bold]")
        console.print(table)
        console.print()


# ── Default command implementations ──────────────────────────────────────────

def build_default_registry() -> SlashCommandRegistry:
    registry = SlashCommandRegistry()

    # ── Core navigation ────────────────────────────────────────────────

    async def _help(args: str, ctx: ChatContext) -> str | None:
        registry.print_help(ctx.console)
        return "handled"

    async def _exit(args: str, ctx: ChatContext) -> str | None:
        ctx.console.print("[dim]Goodbye![/dim]")
        return "exit"

    async def _clear(args: str, ctx: ChatContext) -> str | None:
        ctx.executor.context.clear_messages(ctx.session)  # type: ignore[attr-defined]
        ctx.console.print("[dim]Session history cleared.[/dim]")
        return "handled"

    async def _history(args: str, ctx: ChatContext) -> str | None:
        msgs = ctx.executor.context.get_messages(ctx.session)  # type: ignore[attr-defined]
        ctx.console.print(
            f"[dim]{len(msgs)} messages in session '[yellow]{ctx.session_name}[/yellow]'.[/dim]"
        )
        return "handled"

    async def _provider(args: str, ctx: ChatContext) -> str | None:
        if args.strip():
            name = args.strip()
            ctx.console.print(f"[dim]Switched to: [cyan]{name}[/cyan][/dim]")
            return f"provider:{name}"
        ctx.console.print(
            "[dim]Reset to auto-routing. "
            f"Was: [cyan]{ctx.current_provider or 'auto'}[/cyan][/dim]"
        )
        return "provider:"

    async def _export(args: str, ctx: ChatContext) -> str | None:
        filename = args.strip() or f"{ctx.session_name}.md"
        content = ctx.executor.context.export_session(ctx.session, fmt="markdown")  # type: ignore[attr-defined]
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        ctx.console.print(f"[green]Exported to {filename}[/green]")
        return "handled"

    async def _status(args: str, ctx: ChatContext) -> str | None:
        from uai.models.provider import ProviderStatus
        ctx.console.print("[bold]Provider status:[/bold]")
        for name, prov in ctx.executor.providers.items():  # type: ignore[attr-defined]
            try:
                st = await prov.health_check()
            except Exception:
                st = ProviderStatus.UNAVAILABLE
            color = "green" if st == ProviderStatus.AVAILABLE else (
                "yellow" if st == ProviderStatus.NOT_CONFIGURED else "red"
            )
            ctx.console.print(f"  [{color}]{name}[/{color}]: {st.value}")
        return "handled"

    async def _session(args: str, ctx: ChatContext) -> str | None:
        """Show session info or switch to a named session."""
        name = args.strip()
        if name:
            # Signal chat loop to switch session
            return f"session:{name}"
        # No arg: show current session and list available ones
        ctx.console.print(f"[dim]Current session: [yellow]{ctx.session_name}[/yellow][/dim]")
        sessions = ctx.executor.context.list_sessions()  # type: ignore[attr-defined]
        if sessions:
            ctx.console.print("[dim]Available sessions:[/dim]")
            for s in sessions[:10]:
                marker = "→" if s.name == ctx.session_name else " "
                ctx.console.print(f"  [dim]{marker} {s.name}[/dim]")
        return "handled"

    async def _connect(args: str, ctx: ChatContext) -> str | None:
        """Install and authenticate a provider without leaving the chat."""
        from uai.cli.commands.connect import connect_provider, _CLI_PROVIDERS, _API_ONLY_PROVIDERS

        provider = args.strip().lower()
        if not provider:
            all_providers = list(_CLI_PROVIDERS) + list(_API_ONLY_PROVIDERS)
            ctx.console.print(
                f"[bold]Available providers:[/bold] {', '.join(all_providers)}\n"
                f"[dim]Usage: /connect <provider>[/dim]"
            )
            return "handled"

        await connect_provider(provider)
        return "handled"

    # ── In-chat query shortcuts ────────────────────────────────────────

    async def _ask(args: str, ctx: ChatContext) -> str | None:
        """Send a single query with optional flags."""
        from uai.models.request import UAIRequest
        from uai.cli.streaming import stream_to_live
        from uai.cli.input_expander import expand_input

        # Parse simple flags
        parts = args.split()
        free = ctx.free
        verbose = False
        no_context = False
        provider_override: str | None = ctx.current_provider
        prompt_parts: list[str] = []
        i = 0
        while i < len(parts):
            tok = parts[i]
            if tok == "--free":
                free = True
            elif tok in ("--verbose", "-v"):
                verbose = True
            elif tok == "--no-context":
                no_context = True
            elif tok in ("--provider", "-p") and i + 1 < len(parts):
                i += 1
                provider_override = parts[i]
            else:
                prompt_parts.append(tok)
            i += 1

        prompt = " ".join(prompt_parts).strip()
        if not prompt:
            ctx.console.print(
                "[dim]Usage: /ask [--free] [--verbose] [--no-context] [--provider P] <prompt>[/dim]"
            )
            return "handled"

        expanded, warnings = await expand_input(prompt)
        for w in warnings:
            ctx.console.print(f"[yellow]Warning: {w}[/yellow]")

        if verbose:
            try:
                decision = await ctx.executor.router.route(  # type: ignore[attr-defined]
                    prompt=expanded,
                    prefer_provider=provider_override,
                    free_only=True if free else None,
                )
                ctx.console.print(
                    f"[dim]→ [cyan]{decision.provider}[/cyan]"
                    f"/{decision.model or 'default'}"
                    f" | {decision.task_type.value}"
                    f" | {decision.reason}[/dim]"
                )
            except Exception as e:
                ctx.console.print(f"[dim]Routing info unavailable: {e}[/dim]")

        request = UAIRequest(
            prompt=expanded,
            provider=provider_override,
            session_name=ctx.session_name,
            free_only=free,
            use_context=not no_context,
        )
        try:
            from uai.cli.streaming import StreamStatus
            from uai.cli.commands.chat import _make_on_status
            status = StreamStatus()
            ctx.console.print()
            await stream_to_live(
                ctx.executor.execute_stream(request, on_status=_make_on_status(status)),  # type: ignore[attr-defined]
                ctx.console,
                live_status=status,
            )
            ctx.console.print()
        except Exception as e:
            ctx.console.print(f"[red]Error: {e}[/red]")
        return "handled"

    async def _code(args: str, ctx: ChatContext) -> str | None:
        """Route a code-specific task to the best coding provider."""
        from uai.models.request import UAIRequest
        from uai.models.provider import TaskCapability
        from uai.cli.streaming import stream_to_live
        from uai.cli.input_expander import expand_input

        parts = args.split()
        verbose = False
        task_parts: list[str] = []
        i = 0
        while i < len(parts):
            tok = parts[i]
            if tok in ("--verbose", "-v"):
                verbose = True
            else:
                task_parts.append(tok)
            i += 1

        task = " ".join(task_parts).strip()
        if not task:
            ctx.console.print("[dim]Usage: /code [--verbose] <task>[/dim]")
            return "handled"

        # Classify the task type for smarter routing
        lower = task.lower()
        if any(kw in lower for kw in ["bug", "error", "fix", "debug", "exception", "crash", "fail"]):
            task_type = TaskCapability.DEBUGGING
        elif any(kw in lower for kw in ["review", "audit", "check", "improve", "quality"]):
            task_type = TaskCapability.CODE_REVIEW
        elif any(kw in lower for kw in ["architect", "design", "structure", "refactor", "pattern"]):
            task_type = TaskCapability.ARCHITECTURE
        else:
            task_type = TaskCapability.CODE_GENERATION

        if verbose:
            ctx.console.print(f"[dim]Task type: [cyan]{task_type.value}[/cyan][/dim]")

        expanded, warnings = await expand_input(task)
        for w in warnings:
            ctx.console.print(f"[yellow]Warning: {w}[/yellow]")

        request = UAIRequest(
            prompt=expanded,
            provider=ctx.current_provider,
            session_name=ctx.session_name,
            task_type=task_type,
            free_only=ctx.free,
            use_context=True,
        )
        try:
            from uai.cli.streaming import StreamStatus
            from uai.cli.commands.chat import _make_on_status
            status = StreamStatus()
            ctx.console.print()
            await stream_to_live(
                ctx.executor.execute_stream(request, on_status=_make_on_status(status)),  # type: ignore[attr-defined]
                ctx.console,
                live_status=status,
            )
            ctx.console.print()
        except Exception as e:
            ctx.console.print(f"[red]Error: {e}[/red]")
        return "handled"

    async def _orchestrate(args: str, ctx: ChatContext) -> str | None:
        """Orchestrate a task across multiple AI providers."""
        from rich.markdown import Markdown
        from uai.orchestration.patterns import PATTERNS, list_patterns as lp
        from uai.orchestration.team import TeamBuilder
        from uai.orchestration.cost_guard import CostGuard, CostMode

        parts = args.split()
        pattern_name: str | None = None
        autonomous = False
        task_parts: list[str] = []
        i = 0
        while i < len(parts):
            tok = parts[i]
            if tok in ("--pattern", "-p") and i + 1 < len(parts):
                i += 1
                pattern_name = parts[i]
            elif tok in ("--autonomous", "-a"):
                autonomous = True
            elif tok == "--list":
                table = Table(title="Team Patterns", show_header=True, header_style="bold cyan")
                table.add_column("Pattern", style="cyan", width=22)
                table.add_column("Cost", width=12)
                table.add_column("Description")
                cost_colors = {
                    "free": "[green]free[/green]",
                    "mostly_free": "[green]mostly free[/green]",
                    "mixed": "[yellow]mixed[/yellow]",
                    "paid": "[red]paid[/red]",
                }
                for name, p in PATTERNS.items():
                    table.add_row(name, cost_colors.get(p.cost_estimate, p.cost_estimate), p.description)
                ctx.console.print(table)
                return "handled"
            else:
                task_parts.append(tok)
            i += 1

        task = " ".join(task_parts).strip()
        if not task:
            ctx.console.print(
                "[dim]Usage: /orchestrate [--pattern P] [--autonomous] <task>[/dim]\n"
                "[dim]       /orchestrate --list  (show available patterns)[/dim]"
            )
            return "handled"

        # Auto-select pattern if not specified
        if not pattern_name:
            lower = task.lower()
            if any(k in lower for k in ["bug", "debug", "error", "crash"]):
                pattern_name = "critical_debug"
            elif any(k in lower for k in ["privacy", "lgpd", "gdpr", "pii"]):
                pattern_name = "lgpd_audit"
            elif any(k in lower for k in ["review", "full", "complete", "all"]):
                pattern_name = "full_analysis"
            elif any(k in lower for k in ["brainstorm", "idea", "perspective", "approach"]):
                pattern_name = "brainstorm"
            elif any(k in lower for k in ["batch", "bulk", "list", "items"]):
                pattern_name = "batch_processing"
            else:
                pattern_name = "daily_dev"
            ctx.console.print(f"[dim]Auto-selected pattern: [cyan]{pattern_name}[/cyan][/dim]")

        p = PATTERNS.get(pattern_name)
        if not p:
            ctx.console.print(f"[red]Unknown pattern: {pattern_name}[/red]")
            ctx.console.print(f"[dim]Available: {', '.join(lp())}[/dim]")
            return "handled"

        guard = CostGuard()
        mode = guard.classify(p.roles, user_said_autonomous=autonomous)
        if mode != CostMode.FREE and mode != CostMode.AUTONOMOUS:
            ok = guard.request_approval(p, task, mode)
            if not ok:
                ctx.console.print("[dim]Cancelled.[/dim]")
                return "handled"

        builder = TeamBuilder(
            ctx.executor.config,  # type: ignore[attr-defined]
            ctx.executor.auth,    # type: ignore[attr-defined]
            ctx.executor.quota,   # type: ignore[attr-defined]
        )
        result = await builder.execute(p, task)

        ctx.console.print(f"\n[bold cyan]{'='*50}[/bold cyan]")
        ctx.console.print(
            f"[bold]Orchestration:[/bold] {p.name} | "
            f"[dim]{result.execution_ms:.0f}ms | ${result.total_cost_usd:.4f}[/dim]"
        )

        role_table = Table(show_header=True, header_style="bold")
        role_table.add_column("Role", style="cyan")
        role_table.add_column("Provider")
        role_table.add_column("Status")
        for r in result.role_results:
            status = "[green]✓[/green]" if r.status == "ok" else "[red]✗[/red]"
            role_table.add_row(r.role, r.provider, status)
        ctx.console.print(role_table)

        ctx.console.print("\n[bold]Result:[/bold]")
        ctx.console.print(Markdown(result.consolidated))
        return "handled"

    # ── Management / info commands ─────────────────────────────────────

    async def _quota(args: str, ctx: ChatContext) -> str | None:
        """Show usage and cost report."""
        cfg = ctx.executor.config.load()  # type: ignore[attr-defined]
        snapshots = ctx.executor.quota.get_all_snapshots(cfg.providers)  # type: ignore[attr-defined]

        table = Table(title="Usage Report", show_header=True, header_style="bold cyan")
        table.add_column("Provider", style="cyan", width=10)
        table.add_column("Today", width=7)
        table.add_column("Month", width=7)
        table.add_column("Cost (Mo.)", width=11)
        table.add_column("Limit", width=8)
        table.add_column("OK 24h", width=8)

        total_cost = 0.0
        for snap in snapshots:
            limit_str = str(snap.daily_limit) if snap.daily_limit else "∞"
            cost_str = (
                "[green]free[/green]" if snap.cost_month_usd == 0
                else f"${snap.cost_month_usd:.4f}"
            )
            table.add_row(
                snap.provider,
                str(snap.requests_today),
                str(snap.requests_month),
                cost_str,
                limit_str,
                f"{snap.success_rate_24h * 100:.0f}%",
            )
            total_cost += snap.cost_month_usd

        ctx.console.print(table)
        cost_label = (
            "[green]$0.00 (all free)[/green]" if total_cost == 0
            else f"[yellow]${total_cost:.4f}[/yellow]"
        )
        ctx.console.print(f"[bold]Monthly cost:[/bold] {cost_label}")
        return "handled"

    async def _sessions(args: str, ctx: ChatContext) -> str | None:
        """Manage sessions: list, show <name>, delete <name>."""
        parts = args.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts and parts[0] else "list"
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if not args.strip() or sub == "list":
            sessions = ctx.executor.context.list_sessions()  # type: ignore[attr-defined]
            if not sessions:
                ctx.console.print("[dim]No sessions.[/dim]")
                return "handled"
            table = Table(show_header=True, header_style="bold")
            table.add_column("Name", style="cyan")
            table.add_column("Msgs", width=6)
            table.add_column("Tokens", width=8)
            table.add_column("Last Active")
            for s in sessions:
                marker = " ←" if s.name == ctx.session_name else ""
                table.add_row(
                    f"{s.name}{marker}",
                    str(s.total_messages),
                    str(s.total_tokens),
                    str(s.last_active)[:16],
                )
            ctx.console.print(table)

        elif sub == "show":
            name = sub_arg or ctx.session_name
            target = ctx.executor.context.get_session(name)  # type: ignore[attr-defined]
            msgs = ctx.executor.context.get_messages(target, limit=20)  # type: ignore[attr-defined]
            if not msgs:
                ctx.console.print(f"[dim]No messages in '{name}'.[/dim]")
                return "handled"
            for m in msgs:
                role_color = "cyan" if m.role.value == "user" else "green"
                preview = m.content[:200] + ("…" if len(m.content) > 200 else "")
                ctx.console.print(f"[{role_color}]{m.role.value}:[/{role_color}] {preview}")

        elif sub == "delete":
            if not sub_arg:
                ctx.console.print("[dim]Usage: /sessions delete <name>[/dim]")
                return "handled"
            if sub_arg == ctx.session_name:
                ctx.console.print(f"[red]Cannot delete the active session '{sub_arg}'.[/red]")
                return "handled"
            ctx.executor.context.delete_session(sub_arg)  # type: ignore[attr-defined]
            ctx.console.print(f"[green]Deleted session '{sub_arg}'.[/green]")

        else:
            ctx.console.print("[dim]Usage: /sessions [list|show <name>|delete <name>][/dim]")

        return "handled"

    async def _config(args: str, ctx: ChatContext) -> str | None:
        """View or edit config: show | set <key.path> <value>."""
        from rich.syntax import Syntax

        parts = args.strip().split(maxsplit=2)
        sub = parts[0].lower() if parts else "show"

        if not args.strip() or sub == "show":
            cfg_path = ctx.executor.config.config_path  # type: ignore[attr-defined]
            try:
                text = cfg_path.read_text()
                ctx.console.print(Syntax(text, "yaml", theme="monokai", line_numbers=False))
            except Exception as e:
                ctx.console.print(f"[red]Error reading config: {e}[/red]")

        elif sub == "set":
            if len(parts) < 3:
                ctx.console.print("[dim]Usage: /config set <key.path> <value>[/dim]")
                return "handled"
            key, value = parts[1], parts[2]
            try:
                ctx.executor.config.set(key, value)  # type: ignore[attr-defined]
                ctx.console.print(f"[green]Set {key} = {value}[/green]")
            except Exception as e:
                ctx.console.print(f"[red]Error: {e}[/red]")

        else:
            ctx.console.print("[dim]Usage: /config [show|set <key.path> <value>][/dim]")

        return "handled"

    async def _providers(args: str, ctx: ChatContext) -> str | None:
        """List providers or show detail: /providers [list|detail <name>|<name>]."""
        from uai.providers import list_providers, get_provider_class

        parts = args.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        cfg = ctx.executor.config.load()  # type: ignore[attr-defined]

        def _show_detail(name: str) -> None:
            try:
                cls = get_provider_class(name)
                prov_cfg = cfg.providers.get(name)
                ctx.console.print(f"\n[bold cyan]{cls.display_name}[/bold cyan]")
                ctx.console.print(f"  Free:         {cls.is_free}")
                ctx.console.print(f"  Context:      {cls.context_window_tokens:,} tokens")
                ctx.console.print(f"  Backends:     {', '.join(b.value for b in cls.supported_backends)}")
                ctx.console.print(f"  Capabilities: {', '.join(c.value for c in cls.capabilities)}")
                if prov_cfg:
                    ctx.console.print(f"  Priority:     {prov_cfg.priority}")
                    ctx.console.print(f"  Backend:      {prov_cfg.preferred_backend}")
                    if prov_cfg.daily_limit:
                        ctx.console.print(f"  Daily limit:  {prov_cfg.daily_limit}")
            except (ValueError, Exception) as e:
                ctx.console.print(f"[red]Provider '{name}' not found: {e}[/red]")

        if not args.strip() or sub == "list":
            table = Table(show_header=True, header_style="bold")
            table.add_column("Provider", style="cyan")
            table.add_column("Free")
            table.add_column("Context")
            table.add_column("Status")
            for name in list_providers():
                try:
                    cls = get_provider_class(name)
                    prov_cfg = cfg.providers.get(name)
                    enabled = prov_cfg and prov_cfg.enabled
                    free_tag = "[green]yes[/green]" if cls.is_free else "[yellow]paid[/yellow]"
                    ctx_k = f"{cls.context_window_tokens // 1000}K"
                    status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
                    table.add_row(name, free_tag, ctx_k, status)
                except Exception:
                    pass
            ctx.console.print(table)

        elif sub == "detail":
            name = sub_arg or ""
            if not name:
                ctx.console.print("[dim]Usage: /providers detail <name>[/dim]")
            else:
                _show_detail(name)

        else:
            # Treat bare arg as provider name shorthand: /providers claude
            _show_detail(sub)

        return "handled"

    # ── Register all commands ──────────────────────────────────────────

    registry.register(SlashCommand(
        "help", _help, "Show this help message", aliases=["h", "?"]
    ))
    registry.register(SlashCommand(
        "exit", _exit, "Exit the chat session", aliases=["quit", "q"]
    ))
    registry.register(SlashCommand(
        "clear", _clear, "Clear session conversation history"
    ))
    registry.register(SlashCommand(
        "history", _history, "Show message count in current session"
    ))
    registry.register(SlashCommand(
        "provider", _provider, "Switch provider or reset to auto-routing",
        usage="/provider <name> | /provider (reset)"
    ))
    registry.register(SlashCommand(
        "export", _export, "Export session to a markdown file",
        usage="/export [filename.md]"
    ))
    registry.register(SlashCommand(
        "status", _status, "Show real-time provider health status"
    ))
    registry.register(SlashCommand(
        "session", _session, "Show session info or switch to a named session",
        usage="/session [name]"
    ))
    registry.register(SlashCommand(
        "connect", _connect, "Install and authenticate a provider",
        usage="/connect <provider>"
    ))
    # ── Extended commands ──────────────────────────────────────────────
    registry.register(SlashCommand(
        "ask", _ask, "Send a single query with optional flags",
        usage="/ask [--free] [--verbose] [--no-context] [--provider P] <prompt>"
    ))
    registry.register(SlashCommand(
        "code", _code, "Route a coding task to the best coding provider",
        usage="/code [--verbose] <task>"
    ))
    registry.register(SlashCommand(
        "orchestrate", _orchestrate, "Run multi-AI team orchestration",
        aliases=["orch"],
        usage="/orchestrate [--pattern P] [--autonomous] <task> | --list"
    ))
    registry.register(SlashCommand(
        "quota", _quota, "Show usage and cost report"
    ))
    registry.register(SlashCommand(
        "sessions", _sessions, "Manage sessions",
        usage="/sessions [list|show <name>|delete <name>]"
    ))
    registry.register(SlashCommand(
        "config", _config, "View or edit configuration",
        usage="/config [show|set <key.path> <value>]"
    ))
    registry.register(SlashCommand(
        "providers", _providers, "List providers or show detail",
        usage="/providers [list|detail <name>|<name>]"
    ))

    return registry
