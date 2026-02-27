"""UAI CLI — main Typer application."""
from __future__ import annotations
import asyncio
import typer
from rich.console import Console

from uai.cli.commands import (
    ask, chat, code, config_cmd, connect, orchestrate,
    providers_cmd, quota, sessions, setup, status,
)

console = Console()
app = typer.Typer(
    name="uai",
    help="[bold cyan]UAI[/] — Unified AI CLI: one tool for all AI providers",
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)


@app.callback(invoke_without_command=True)
def default_callback(ctx: typer.Context) -> None:
    """Launch interactive mode when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        from uai.cli.commands.interactive import interactive_mode
        asyncio.run(interactive_mode())

app.command("ask")(ask.ask)
app.command("chat")(chat.chat)
app.command("code")(code.code)
app.command("orchestrate")(orchestrate.orchestrate)
app.command("setup")(setup.setup)
app.command("connect")(connect.connect)
app.command("status")(status.status)
app.command("quota")(quota.quota)

# Sub-app for session management
sessions_app = typer.Typer(help="Manage conversation sessions", no_args_is_help=True)
sessions_app.command("list")(sessions.sessions_list)
sessions_app.command("show")(sessions.sessions_show)
sessions_app.command("delete")(sessions.sessions_delete)
sessions_app.command("export")(sessions.sessions_export)
app.add_typer(sessions_app, name="sessions")

# Sub-app for config management
config_app = typer.Typer(help="View and edit configuration", no_args_is_help=True)
config_app.command("show")(config_cmd.config_show)
config_app.command("set")(config_cmd.config_set)
app.add_typer(config_app, name="config")

# Sub-app for providers
providers_app = typer.Typer(help="List and inspect AI providers", no_args_is_help=True)
providers_app.command("list")(providers_cmd.providers_list)
providers_app.command("detail")(providers_cmd.providers_detail)
app.add_typer(providers_app, name="providers")


def main() -> None:
    import os
    from uai.utils.logging import configure_logging
    configure_logging(os.environ.get("UAI_LOG_LEVEL", "WARNING"))
    app()
