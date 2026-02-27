"""uai connect <provider> — install the provider CLI (or show manual API config tip)."""
from __future__ import annotations
import asyncio
import typer
from rich import print as rprint
from rich.console import Console

console = Console()

# Providers that ship a CLI installable via npm or a shell script
_CLI_PROVIDERS: dict[str, dict] = {
    "gemini": {
        "display": "Google Gemini",
        "npm": "@google/gemini-cli",
        "post_install": "Run [cyan]gemini[/cyan] once to complete OAuth login.",
    },
    "qwen": {
        "display": "Qwen Code",
        "npm": "@qwen/qwen-code",
        "post_install": "Run [cyan]qwen[/cyan] once to complete OAuth login.",
    },
    "claude": {
        "display": "Anthropic Claude",
        "npm": "@anthropic-ai/claude-code",
        "post_install": "Run [cyan]claude[/cyan] once to complete browser login.",
    },
    "codex": {
        "display": "OpenAI Codex",
        "npm": "@openai/codex",
        "post_install": "Run [cyan]codex[/cyan] once to complete browser login.",
    },
    "ollama": {
        "display": "Ollama (local)",
        "script": "curl -fsSL https://ollama.ai/install.sh | sh",
        "post_install": (
            "Pull a model: [cyan]ollama pull qwen2.5-coder[/cyan]\n"
            "  Then start the server: [cyan]ollama serve[/cyan]"
        ),
    },
}

# Providers that have no CLI — API key must be set manually in config/env
_API_ONLY_PROVIDERS: dict[str, dict] = {
    "groq": {
        "display": "Groq",
        "key_name": "api_key",
        "env": "GROQ_API_KEY",
        "url": "https://console.groq.com/keys",
    },
    "deepseek": {
        "display": "DeepSeek",
        "key_name": "api_key",
        "env": "DEEPSEEK_API_KEY",
        "url": "https://platform.deepseek.com/",
    },
}

# Kept for internal use by interactive.py onboarding
_CONNECT_INSTRUCTIONS: dict[str, str] = {
    p: f"Install via npm: npm install -g {info['npm']}"
    for p, info in _CLI_PROVIDERS.items()
    if "npm" in info
}
_CONNECT_INSTRUCTIONS["ollama"] = _CLI_PROVIDERS["ollama"]["script"]

_CREDENTIAL_KEYS: dict[str, str] = {
    p: info["key_name"] for p, info in _API_ONLY_PROVIDERS.items()
}


async def _test_connection(provider: str, auth, cfg_mgr) -> tuple[bool, str]:
    try:
        from uai.providers import get_provider_class
        cls = get_provider_class(provider)
        prov_cfg = cfg_mgr.get_provider_config(provider)
        instance = cls(auth, prov_cfg)
        status = await instance.health_check()
        from uai.models.provider import ProviderStatus
        if status == ProviderStatus.AVAILABLE:
            return True, f"{provider} is available"
        return False, f"Status: {status.value}"
    except Exception as e:
        return False, str(e)


def connect(
    provider: str = typer.Argument(
        ...,
        help="Provider name (gemini, qwen, claude, codex, ollama, groq, deepseek)",
    ),
    test: bool = typer.Option(True, "--test/--no-test", help="Test connection after install"),
) -> None:
    """
    Install the CLI for an AI provider (or show how to configure API-only providers).

    CLI-based providers (gemini, qwen, claude, codex, ollama) are installed via npm
    or a shell script and use OAuth — no API key needed.

    API-only providers (groq, deepseek) have no CLI. Set their key as an environment
    variable or add it to [cyan]~/.uai/config.yaml[/cyan].
    """
    asyncio.run(_connect(provider, test))


async def _connect(provider: str, test: bool) -> None:
    from uai.core.config import ConfigManager
    from uai.core.auth import AuthManager
    from uai.utils.installer import is_cli_installed, install_cli, npm_available

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()
    auth = AuthManager(cfg_mgr.config_dir)

    # ── API-only provider ──────────────────────────────────────────────────
    if provider in _API_ONLY_PROVIDERS:
        info = _API_ONLY_PROVIDERS[provider]
        rprint(f"\n[bold cyan]{info['display']}[/bold cyan] is an API-only provider.\n")
        rprint(f"  Get your key at: [cyan]{info['url']}[/cyan]\n")
        rprint("  Add it to your environment:")
        rprint(f"    [dim]export {info['env']}=<your-key>[/dim]\n")
        rprint("  Or add it to [cyan]~/.uai/config.yaml[/cyan]:")
        rprint(f"    [dim]providers:\n      {provider}:\n        enabled: true\n        extra:\n          api_key: <your-key>[/dim]\n")
        rprint("[dim]UAI will pick up the key automatically on the next run.[/dim]")
        return

    # ── CLI-based provider ─────────────────────────────────────────────────
    if provider not in _CLI_PROVIDERS:
        rprint(f"[red]Unknown provider: {provider}[/red]")
        rprint(
            f"CLI providers: {', '.join(_CLI_PROVIDERS)}\n"
            f"API-only providers: {', '.join(_API_ONLY_PROVIDERS)}"
        )
        raise typer.Exit(1)

    info = _CLI_PROVIDERS[provider]
    rprint(f"\n[bold cyan]Connecting {info['display']}...[/bold cyan]")

    if is_cli_installed(provider):
        rprint(f"[green]✓[/green] {info['display']} CLI is already installed.")
    else:
        # Install
        if "npm" in info:
            if not npm_available():
                rprint(
                    "[yellow]⚠[/yellow] npm not found. Install Node.js from "
                    "[cyan]https://nodejs.org/[/cyan] and re-run."
                )
                raise typer.Exit(1)
            rprint(f"Installing via npm: [dim]npm install -g {info['npm']}[/dim]")
        elif "script" in info:
            rprint(f"Running: [dim]{info['script']}[/dim]")

        ok = install_cli(provider)
        if ok:
            rprint(f"[green]✓[/green] {info['display']} CLI installed.")
        else:
            rprint(f"[red]✗[/red] Installation failed.")
            if "npm" in info:
                rprint(f"  Try manually: [dim]npm install -g {info['npm']}[/dim]")
            elif "script" in info:
                rprint(f"  Try manually: [dim]{info['script']}[/dim]")
            raise typer.Exit(1)

    # Enable provider in config
    cfg = cfg_mgr.load()
    if provider in cfg.providers:
        cfg.providers[provider].enabled = True
        cfg_mgr.save(cfg)

    rprint(f"\n[dim]{info['post_install']}[/dim]")

    if test:
        rprint("\nTesting connection...", end=" ")
        ok, message = await _test_connection(provider, auth, cfg_mgr)
        if ok:
            rprint(f"[green]✓ {message}[/green]")
        else:
            rprint(f"[yellow]⚠ {message}[/yellow]")

    rprint(f"\n[green]{info['display']} connected![/green] "
           f"Use [cyan]uai ask \"hello\"[/cyan] to try it.")
