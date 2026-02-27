"""UAI interactive mode — launched when `uai` is run without arguments."""
from __future__ import annotations

import asyncio
from importlib.metadata import version, PackageNotFoundError

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Provider catalog — ordered: free first, then paid
# ──────────────────────────────────────────────────────────────────────────────

_PROVIDER_CATALOG: list[dict] = [
    {
        "name": "gemini",
        "display": "Google Gemini",
        "cost": "free",
        "desc": "Fast, generous free tier — recommended",
    },
    {
        "name": "groq",
        "display": "Groq",
        "cost": "free",
        "desc": "Ultra-fast inference, free tier",
    },
    {
        "name": "ollama",
        "display": "Ollama (local)",
        "cost": "free",
        "desc": "Fully offline, no API key needed",
    },
    {
        "name": "qwen",
        "display": "Qwen Code",
        "cost": "free",
        "desc": "Alibaba Qwen Code, 1 000 req/day",
    },
    {
        "name": "claude",
        "display": "Anthropic Claude",
        "cost": "paid",
        "desc": "State-of-the-art reasoning & code",
    },
    {
        "name": "codex",
        "display": "OpenAI Codex",
        "cost": "paid",
        "desc": "GPT-4o optimised for coding tasks",
    },
    {
        "name": "deepseek",
        "display": "DeepSeek",
        "cost": "paid",
        "desc": "Cost-effective, strong at code",
    },
]


def _get_version() -> str:
    try:
        return version("uai")
    except PackageNotFoundError:
        return "dev"


# ──────────────────────────────────────────────────────────────────────────────
# Banner
# ──────────────────────────────────────────────────────────────────────────────


def _print_banner(configured_providers: list[str]) -> None:
    ver = _get_version()

    if configured_providers:
        connected = "  ".join(f"[green]{p}[/green]" for p in configured_providers)
        status_line = f"Connected: {connected}"
    else:
        status_line = "[yellow]No providers connected yet[/yellow]"

    content = (
        f"[bold cyan]UAI[/bold cyan] [dim]v{ver}[/dim]\n"
        f"[dim]Unified AI CLI — one tool for all AI providers[/dim]\n\n"
        f"{status_line}\n"
        f"[dim]Type /help for commands, Ctrl+C or /exit to quit[/dim]"
    )

    console.print()
    console.print(Panel(content, border_style="cyan", padding=(1, 4)))
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Onboarding
# ──────────────────────────────────────────────────────────────────────────────


def _print_provider_table() -> None:
    table = Table(
        show_header=True,
        header_style="bold dim",
        box=None,
        padding=(0, 2),
        show_edge=False,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Provider", style="cyan", min_width=20)
    table.add_column("Cost", min_width=6)
    table.add_column("Description", style="dim")

    for i, p in enumerate(_PROVIDER_CATALOG, 1):
        cost = "[green]free[/green]" if p["cost"] == "free" else "[yellow]paid[/yellow]"
        table.add_row(str(i), p["display"], cost, p["desc"])

    console.print(table)
    console.print()


def _parse_selection(raw: str) -> list[str]:
    """Parse user input into a list of provider names."""
    raw = raw.strip().lower()

    if raw == "free":
        return [p["name"] for p in _PROVIDER_CATALOG if p["cost"] == "free"]

    if raw == "all":
        return [p["name"] for p in _PROVIDER_CATALOG]

    name_set = {p["name"] for p in _PROVIDER_CATALOG}
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(_PROVIDER_CATALOG):
                selected.append(_PROVIDER_CATALOG[idx]["name"])
        elif part in name_set:
            selected.append(part)

    return selected


async def _connect_provider_interactive(provider: str, auth, cfg_mgr) -> None:
    """Connect a single provider, prompting for credentials inline."""
    from uai.cli.commands.connect import (
        _CONNECT_INSTRUCTIONS,
        _CREDENTIAL_KEYS,
        _test_connection,
    )

    rprint(f"[bold cyan]── {provider} ──[/bold cyan]")

    if provider == "ollama":
        rprint(f"[dim]{_CONNECT_INSTRUCTIONS['ollama']}[/dim]")
        rprint("[green]✓[/green] No credentials needed — just ensure Ollama is running.\n")
        return

    instructions = _CONNECT_INSTRUCTIONS.get(provider, "")
    if instructions:
        rprint(f"[dim]{instructions}[/dim]\n")

    cred_key = _CREDENTIAL_KEYS.get(provider, "api_key")

    try:
        import typer as _typer
        api_key = _typer.prompt(
            f"  {provider} API key",
            hide_input=True,
            confirmation_prompt=False,
            default="",
            show_default=False,
        )
    except (KeyboardInterrupt, EOFError):
        rprint("\n[dim]Skipped.[/dim]\n")
        return

    if not api_key.strip():
        rprint(f"[dim]Skipped {provider}.[/dim]\n")
        return

    auth.set_credential(provider, cred_key, api_key.strip())
    rprint("[green]✓[/green] Credentials saved.")

    # Enable provider in config
    cfg = cfg_mgr.load()
    if provider in cfg.providers:
        cfg.providers[provider].enabled = True
        cfg_mgr.save(cfg)

    # Test the connection
    rprint("  Testing connection...", end=" ")
    ok, message = await _test_connection(provider, auth, cfg_mgr)
    if ok:
        rprint(f"[green]✓ {message}[/green]\n")
    else:
        rprint(f"[yellow]⚠ {message}[/yellow]\n")


async def _onboarding_flow(auth, cfg_mgr) -> None:
    """Guide the user through connecting at least one provider."""
    rprint("[bold]No AI providers configured yet.[/bold] Let's connect one!\n")
    _print_provider_table()

    rprint("[dim]Which providers would you like to connect?[/dim]")
    rprint(
        "[dim]Enter numbers separated by commas (e.g. [cyan]1,2[/cyan]), "
        "[cyan]free[/cyan] for all free providers, "
        "or press Enter to skip.[/dim]"
    )

    try:
        raw = input("\n> ").strip()
    except (KeyboardInterrupt, EOFError):
        rprint("\n[dim]Skipped.[/dim]")
        return

    if not raw:
        rprint("[dim]Skipped. Connect later with [cyan]uai connect <provider>[/cyan][/dim]\n")
        return

    selected = _parse_selection(raw)
    if not selected:
        rprint(
            "[yellow]No valid selection.[/yellow] "
            "Connect later with [cyan]uai connect <provider>[/cyan]\n"
        )
        return

    rprint()
    for name in selected:
        await _connect_provider_interactive(name, auth, cfg_mgr)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


async def interactive_mode() -> None:
    """
    Default mode when `uai` is called without arguments.

    • Shows a welcome banner with connected providers.
    • If nothing is configured, runs the onboarding flow (provider selection).
    • Drops into the interactive chat REPL.
    """
    from uai.core.config import ConfigManager
    from uai.core.auth import AuthManager

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()
    auth = AuthManager(cfg_mgr.config_dir)

    configured = auth.list_configured_providers()

    _print_banner(configured)

    if not configured:
        await _onboarding_flow(auth, cfg_mgr)
        configured = auth.list_configured_providers()
        if not configured:
            rprint(
                "[dim]Tip: run [cyan]uai connect <provider>[/cyan] anytime to add a provider.[/dim]\n"
            )

    # Start the chat REPL
    from uai.cli.commands.chat import _chat

    await _chat(
        session_name="default",
        forced_provider=None,
        free=False,
        new=False,
        resume=False,
    )
