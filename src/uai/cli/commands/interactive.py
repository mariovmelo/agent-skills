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
# Provider catalog
# Providers with a CLI are installed automatically; API-only ones need a key
# configured manually in ~/.uai/config.yaml.
# ──────────────────────────────────────────────────────────────────────────────

_PROVIDERS_WITH_CLI: list[dict] = [
    {
        "name": "gemini",
        "display": "Google Gemini",
        "cost": "free",
        "desc": "Fast, generous free tier — recommended",
        "npm": "@google/gemini-cli",
    },
    {
        "name": "qwen",
        "display": "Qwen Code",
        "cost": "free",
        "desc": "Alibaba Qwen Code, 1 000 req/day",
        "npm": "@qwen/qwen-code",
    },
    {
        "name": "claude",
        "display": "Anthropic Claude",
        "cost": "paid",
        "desc": "State-of-the-art reasoning & code",
        "npm": "@anthropic-ai/claude-code",
    },
    {
        "name": "codex",
        "display": "OpenAI Codex",
        "cost": "paid",
        "desc": "GPT-4o optimised for coding tasks",
        "npm": "@openai/codex",
    },
    {
        "name": "ollama",
        "display": "Ollama (local)",
        "cost": "free",
        "desc": "Fully offline, no account needed",
        "script": "curl -fsSL https://ollama.ai/install.sh | sh",
    },
]

_PROVIDERS_API_ONLY: list[dict] = [
    {
        "name": "groq",
        "display": "Groq",
        "cost": "free",
        "desc": "Ultra-fast inference, free tier",
        "key_env": "GROQ_API_KEY",
    },
    {
        "name": "deepseek",
        "display": "DeepSeek",
        "cost": "paid",
        "desc": "Cost-effective, strong at code",
        "key_env": "DEEPSEEK_API_KEY",
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


def _print_banner(ready: list[str], needs_auth: list[str]) -> None:
    ver = _get_version()

    lines: list[str] = []
    if ready:
        lines.append("Ready:      " + "  ".join(f"[green]{p}[/green]" for p in ready))
    if needs_auth:
        lines.append(
            "Need auth:  "
            + "  ".join(f"[yellow]{p}[/yellow]" for p in needs_auth)
            + "  [dim](run uai connect <provider>)[/dim]"
        )
    if not ready and not needs_auth:
        lines.append("[dim]No providers installed yet[/dim]")

    status_line = "\n".join(lines)

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


def _detect_installed() -> list[str]:
    """Return names of providers whose CLI binary is present (regardless of auth)."""
    from uai.utils.installer import is_cli_installed
    return [p["name"] for p in _PROVIDERS_WITH_CLI if is_cli_installed(p["name"])]


def _detect_ready(cfg, auth) -> list[str]:
    """Return names of providers that are installed AND authenticated (ready to use)."""
    from uai.utils.installer import is_cli_installed
    ready = []
    for p in _PROVIDERS_WITH_CLI:
        name = p["name"]
        if not is_cli_installed(name):
            continue
        prov_cfg = cfg.providers.get(name)
        cli_ok = bool(prov_cfg and getattr(prov_cfg, "cli_authenticated", False))
        api_ok = bool(auth.get_credential(name, "api_key"))
        if cli_ok or api_ok:
            ready.append(name)
    return ready


def _detect_needs_auth(cfg, auth) -> list[str]:
    """Return names of providers installed but not yet authenticated."""
    from uai.utils.installer import is_cli_installed
    needs = []
    for p in _PROVIDERS_WITH_CLI:
        name = p["name"]
        if not is_cli_installed(name):
            continue
        prov_cfg = cfg.providers.get(name)
        cli_ok = bool(prov_cfg and getattr(prov_cfg, "cli_authenticated", False))
        api_ok = bool(auth.get_credential(name, "api_key"))
        if not cli_ok and not api_ok:
            needs.append(name)
    return needs


def _print_onboarding_table() -> None:
    from uai.utils.installer import is_cli_installed, npm_available

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
    table.add_column("Status", min_width=16)
    table.add_column("Description", style="dim")

    for i, p in enumerate(_PROVIDERS_WITH_CLI, 1):
        cost = "[green]free[/green]" if p["cost"] == "free" else "[yellow]paid[/yellow]"
        installed = is_cli_installed(p["name"]) or (
            # Ollama: check binary
            p["name"] == "ollama" and is_cli_installed("ollama")
        )
        status = "[green]✓ installed[/green]" if installed else "[dim]not installed[/dim]"
        table.add_row(str(i), p["display"], cost, status, p["desc"])

    console.print(table)

    # API-only section
    if _PROVIDERS_API_ONLY:
        console.print()
        console.print(
            "[dim]API-only providers (no CLI available — configure via config file):[/dim]"
        )
        for p in _PROVIDERS_API_ONLY:
            cost = "[green]free[/green]" if p["cost"] == "free" else "[yellow]paid[/yellow]"
            console.print(
                f"  [dim cyan]{p['display']}[/dim cyan]  {cost}  "
                f"[dim]{p['desc']} — set [cyan]{p['key_env']}[/cyan] in "
                f"~/.uai/config.yaml[/dim]"
            )

    console.print()

    if not npm_available():
        console.print(
            "[yellow]⚠[/yellow] [dim]npm not found — Node.js CLIs cannot be auto-installed. "
            "Install Node.js from https://nodejs.org/ first.[/dim]\n"
        )


def _parse_selection(raw: str, total: int) -> list[int]:
    """Return 0-based indices of selected providers."""
    raw = raw.strip().lower()

    if raw == "all":
        return list(range(total))

    if raw == "free":
        return [i for i, p in enumerate(_PROVIDERS_WITH_CLI) if p["cost"] == "free"]

    indices: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < total:
                indices.append(idx)
    return indices


async def _install_provider(p: dict) -> bool:
    """Install the CLI for a provider. Returns True on success."""
    from uai.utils.installer import install_cli, is_cli_installed, npm_available

    name = p["name"]

    if is_cli_installed(name):
        rprint(f"  [green]✓[/green] {p['display']} already installed.")
        return True

    # npm package
    if "npm" in p:
        if not npm_available():
            rprint(f"  [yellow]⚠[/yellow] npm not found — cannot install {p['display']}.")
            rprint(f"    Install Node.js from [cyan]https://nodejs.org/[/cyan] then run:")
            rprint(f"    [dim]npm install -g {p['npm']}[/dim]")
            return False
        rprint(f"\n  Installing [bold cyan]{p['display']}[/bold cyan] "
               f"[dim](npm install -g {p['npm']})[/dim]")
        ok = install_cli(name)
    elif "script" in p:
        rprint(f"\n  Installing [bold cyan]{p['display']}[/bold cyan]...")
        ok = install_cli(name)
    else:
        ok = False

    if ok:
        rprint(f"\n  [green]✓[/green] {p['display']} installed.")
    else:
        rprint(f"\n  [red]✗[/red] {p['display']} installation failed.")
        if "npm" in p:
            rprint(f"    Try manually: [dim]npm install -g {p['npm']}[/dim]")
        elif "script" in p:
            rprint(f"    Manual: [dim]{p['script']}[/dim]")

    return ok


async def _onboarding_flow() -> None:
    """Show provider table, let user pick which CLIs to install."""
    rprint("[bold]No AI providers installed yet.[/bold] Let's set one up!\n")
    _print_onboarding_table()

    rprint("[dim]Which providers would you like to install?[/dim]")
    rprint(
        "[dim]Enter numbers separated by commas (e.g. [cyan]1,2[/cyan]), "
        "[cyan]free[/cyan] for all free, [cyan]all[/cyan] for everything, "
        "or press Enter to skip.[/dim]"
    )

    try:
        raw = input("\n> ").strip()
    except (KeyboardInterrupt, EOFError):
        rprint("\n[dim]Skipped.[/dim]")
        return

    if not raw:
        rprint(
            "[dim]Skipped. Install later with [cyan]uai connect <provider>[/cyan][/dim]\n"
        )
        return

    indices = _parse_selection(raw, len(_PROVIDERS_WITH_CLI))
    if not indices:
        rprint(
            "[yellow]No valid selection.[/yellow] "
            "Install later with [cyan]uai connect <provider>[/cyan]\n"
        )
        return

    rprint()
    for i in indices:
        await _install_provider(_PROVIDERS_WITH_CLI[i])
    rprint()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


async def interactive_mode() -> None:
    """
    Default mode when `uai` is called without arguments.

    • Shows a welcome banner with ready (installed + authenticated) providers.
    • If nothing is installed, runs the onboarding flow (CLI installation).
    • If CLIs are installed but not authenticated, offers to authenticate now.
    • Drops into the interactive chat REPL.
    """
    from uai.core.config import ConfigManager
    from uai.core.auth import AuthManager

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()
    auth = AuthManager(cfg_mgr.config_dir)
    cfg = cfg_mgr.load()

    installed = _detect_installed()
    ready = _detect_ready(cfg, auth)
    needs_auth = _detect_needs_auth(cfg, auth)

    _print_banner(ready, needs_auth)

    # ── Nothing installed at all → full onboarding ─────────────────────
    if not installed:
        await _onboarding_flow()
        cfg = cfg_mgr.load()
        installed = _detect_installed()
        needs_auth = _detect_needs_auth(cfg, auth)
        ready = _detect_ready(cfg, auth)
        if not installed:
            rprint(
                "[dim]Tip: run [cyan]uai connect <provider>[/cyan] anytime to install a CLI.[/dim]\n"
            )

    # ── Offer to authenticate if no provider is ready yet ──────────────
    if not ready and needs_auth:
        try:
            ans = input("  Authenticate now? (y/N) ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            ans = ""
        if ans in ("y", "yes"):
            from uai.cli.commands.connect import _connect
            for name in needs_auth:
                rprint()
                await _connect(name)
            cfg = cfg_mgr.load()
            ready = _detect_ready(cfg, auth)

    # Start the chat REPL
    from uai.cli.commands.chat import _chat

    await _chat(
        session_name="default",
        forced_provider=None,
        free=False,
        new=False,
        resume=False,
    )
