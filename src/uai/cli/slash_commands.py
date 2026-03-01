"""Registry-based slash command system for the UAI chat REPL."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from rich.console import Console
from rich.table import Table


# Handler signature: (args: str, ctx: ChatContext) -> str | None
# Return "exit" to quit, "provider:<name>" to switch provider, else "handled"/None
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
        table.add_column("Command", style="cyan", min_width=22)
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
        """Show or switch sessions."""
        if not args.strip():
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
        "session", _session, "Show or switch active session",
        usage="/session [name]"
    ))
    registry.register(SlashCommand(
        "connect", _connect, "Install and authenticate a provider",
        usage="/connect <provider>"
    ))

    return registry
