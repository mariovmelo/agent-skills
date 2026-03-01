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
        # IMPORTANT: Gemini CLI authenticates via Google OAuth — NO API key is needed.
        # The CLI triggers a browser login on first use. preferred_backend MUST stay "cli".
        # Do NOT add "auth_type": "api_key" here; that breaks the free OAuth flow.
        "auth_args": ["-p", "hi"],
    },
    "qwen": {
        "display": "Qwen Code",
        "npm": "@qwen/qwen-code",
        "auth_args": ["-p", "hi"],
    },
    "claude": {
        "display": "Anthropic Claude",
        "npm": "@anthropic-ai/claude-code",
        "auth_args": ["-p", "hi", "--model", "haiku"],
    },
    "codex": {
        "display": "OpenAI Codex",
        "npm": "@openai/codex",
        "auth_args": ["exec", "--skip-git-repo-check", "hi"],
    },
    "ollama": {
        "display": "Ollama (local)",
        "script": "curl -fsSL https://ollama.ai/install.sh | sh",
        # No auth_args — ollama uses no OAuth; user pulls a model separately
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


def _set_cli_authenticated(cfg_mgr, provider: str, value: bool) -> None:
    """Persist cli_authenticated flag for a provider in config.yaml."""
    cfg = cfg_mgr.load()
    if provider in cfg.providers:
        cfg.providers[provider].cli_authenticated = value
        cfg_mgr.save(cfg)


def connect(
    provider: str = typer.Argument(
        ...,
        help="Provider name (gemini, qwen, claude, codex, ollama, groq, deepseek)",
    ),
) -> None:
    """
    Install the CLI for an AI provider (or show how to configure API-only providers).

    CLI-based providers (gemini, qwen, claude, codex, ollama) are installed via npm
    or a shell script and use OAuth — no API key needed.

    API-only providers (groq, deepseek) have no CLI. Set their key as an environment
    variable or add it to [cyan]~/.uai/config.yaml[/cyan].
    """
    asyncio.run(_connect(provider))


async def _connect(provider: str) -> None:
    from uai.core.config import ConfigManager
    from uai.core.auth import AuthManager
    from uai.utils.installer import is_cli_installed, install_cli, npm_available, get_cli_path

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
        # Install — process inherits terminal so output, prompts and OAuth flows work
        if "npm" in info:
            if not npm_available():
                rprint(
                    "[yellow]⚠[/yellow] npm not found. Install Node.js from "
                    "[cyan]https://nodejs.org/[/cyan] and re-run."
                )
                raise typer.Exit(1)
            rprint(f"\nRunning: [dim]npm install -g {info['npm']}[/dim]\n")
        elif "script" in info:
            rprint(f"\nRunning: [dim]{info['script']}[/dim]\n")

        ok = install_cli(provider)

        if ok:
            rprint(f"\n[green]✓[/green] {info['display']} CLI installed.")
        else:
            rprint(f"\n[red]✗[/red] Installation failed.")
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

    # ── Ollama: no OAuth; just show post-install steps ─────────────────
    if "post_install" in info:
        rprint(f"\n[yellow]Next steps:[/yellow]")
        rprint(f"  {info['post_install']}")
        return

    # ── Auth step ──────────────────────────────────────────────────────
    # API keys are NEVER prompted interactively. They must be set via
    # environment variable or ~/.uai/config.yaml. CLI providers authenticate
    # via their own OAuth flow (auth_args) or manage auth internally (self_auth).
    if auth_args := info.get("auth_args"):
        # Provider uses browser OAuth via its CLI
        rprint(
            f"\n[bold]Step 2 — Authenticate {info['display']}[/bold]\n"
            f"[dim]A browser window will open. Log in, then return to this terminal.[/dim]\n"
        )
        import subprocess
        cmd = [get_cli_path(provider)] + auth_args
        result = subprocess.run(cmd)   # inherits terminal — OAuth flows work naturally

        if result.returncode == 0:
            _set_cli_authenticated(cfg_mgr, provider, True)
            rprint(f"\n[green]✓[/green] {info['display']} authenticated and ready!")
            rprint(f"\nUse [cyan]uai ask \"hello\"[/cyan] to try it.")
        else:
            rprint(
                f"\n[yellow]⚠[/yellow] Authentication may not have completed "
                f"(exit code {result.returncode})."
            )
            rprint(
                f"  Run [cyan]{provider} {' '.join(auth_args)}[/cyan] to retry, "
                f"or just type [cyan]uai ask \"hello\"[/cyan] — UAI will prompt for auth."
            )
