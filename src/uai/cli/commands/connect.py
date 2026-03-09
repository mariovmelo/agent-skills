"""uai connect <provider> — install the provider CLI (or show manual API config tip)."""
from __future__ import annotations
import asyncio
import subprocess
import typer
from rich import print as rprint
from rich.console import Console

console = Console()

# Providers that ship a CLI installable via npm or a shell script
_CLI_PROVIDERS: dict[str, dict] = {
    "gemini": {
        "display": "Google Gemini",
        "npm": "@google/gemini-cli",
        # IMPORTANT: Use interactive_auth=True — NOT auth_args=["-p","hi"].
        # Running `gemini -p <prompt>` non-interactively requires pre-configured auth
        # and exits 41 if none is set. Running `gemini` (no args) triggers the
        # first-run wizard where the user picks Google OAuth or API key themselves.
        # UAI never prompts for credentials; the Gemini CLI wizard handles it.
        # preferred_backend MUST remain "cli".
        "interactive_auth": True,
        # Auth success is confirmed by the presence of ~/.gemini/settings.json
    },
    "qwen": {
        "display": "Qwen Code",
        "npm": "@qwen-code/qwen-code",
        # Qwen uses browser-based OAuth on first run (identical to Gemini's flow).
        # Running `qwen -p hi` without prior auth exits non-zero — so we open the
        # REPL and let the user complete sign-in interactively via the wizard.
        # Auth success is confirmed by the presence of ~/.qwen/settings.json.
        "interactive_auth": True,
        "auth_hint": (
            "The Qwen Code setup wizard will open.\n"
            "  Choose your auth method (Qwen OAuth or API key), then\n"
            "  type [cyan]/quit[/cyan] or press [cyan]Ctrl+C[/cyan] to return here."
        ),
        "auth_settings_file": ".qwen/settings.json",
    },
    "claude": {
        "display": "Anthropic Claude",
        "npm": "@anthropic-ai/claude-code",
        # IMPORTANT: Do NOT use `claude auth login` — it opens a browser and then
        # polls the server waiting for the OAuth callback. In container/headless
        # environments this poll hangs indefinitely with no way to unblock it.
        # Instead, open the full interactive REPL (`claude` with no args) so the
        # user can type `/login` themselves; the REPL handles the TTY correctly.
        # Auth success is confirmed afterwards via `claude auth status` (exit 0).
        "interactive_auth": True,
        "auth_hint": (
            "The Claude Code editor will open.\n"
            "  1. Type [cyan]/login[/cyan] and follow the prompts to sign in\n"
            "  2. When done, type [cyan]/exit[/cyan] or press [cyan]Ctrl+C[/cyan] to return here"
        ),
        # Run `claude auth status` after REPL exits; exit 0 means logged in
        "auth_check_args": ["auth", "status"],
    },
    "codex": {
        "display": "OpenAI Codex",
        "npm": "@openai/codex",
        "auth_args": ["exec", "--skip-git-repo-check", "hi"],
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
_CREDENTIAL_KEYS: dict[str, str] = {
    p: info["key_name"] for p, info in _API_ONLY_PROVIDERS.items()
}


def _set_cli_authenticated(cfg_mgr, provider: str, value: bool) -> None:
    """Persist cli_authenticated flag for a provider in config.yaml."""
    cfg = cfg_mgr.load()
    if provider in cfg.providers:
        cfg.providers[provider].cli_authenticated = value
        cfg_mgr.save(cfg)


def _run_interactive(cmd: list[str]) -> int:
    """Run a CLI command with full terminal access (stdin/stdout/stderr inherited).

    Uses subprocess.run so the child process gets a proper TTY — safe for OAuth
    flows that need to display prompts and read pasted codes from the user.
    Returns the process exit code.
    """
    result = subprocess.run(cmd)
    return result.returncode


async def connect_provider(provider: str) -> bool:
    """
    Install and authenticate a provider CLI.

    Returns True on success, False on failure.
    Safe to call from both the CLI (via asyncio.run) and the chat /connect command
    (already inside an event loop). Runs auth subprocesses via asyncio.to_thread so
    blocking TTY interaction (OAuth prompts, code paste) works without freezing the loop.
    """
    from uai.core.config import ConfigManager
    from uai.utils.installer import is_cli_installed, install_cli, npm_available, get_cli_path

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()

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
        return True

    # ── CLI-based provider ─────────────────────────────────────────────────
    if provider not in _CLI_PROVIDERS:
        rprint(f"[red]Unknown provider:[/red] {provider}")
        all_providers = list(_CLI_PROVIDERS) + list(_API_ONLY_PROVIDERS)
        rprint(f"Available: {', '.join(all_providers)}")
        return False

    info = _CLI_PROVIDERS[provider]
    rprint(f"\n[bold cyan]Connecting {info['display']}...[/bold cyan]")

    if is_cli_installed(provider):
        rprint(f"[green]✓[/green] {info['display']} CLI is already installed.")
    else:
        if "npm" in info:
            if not npm_available():
                rprint(
                    "[yellow]⚠[/yellow] npm not found. Install Node.js from "
                    "[cyan]https://nodejs.org/[/cyan] and re-run."
                )
                return False
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
            return False

    # Enable provider in config
    cfg = cfg_mgr.load()
    if provider in cfg.providers:
        cfg.providers[provider].enabled = True
        cfg_mgr.save(cfg)

    # ── Ollama: no OAuth; just show post-install steps ─────────────────
    if "post_install" in info:
        rprint(f"\n[yellow]Next steps:[/yellow]")
        rprint(f"  {info['post_install']}")
        return True

    # ── Interactive auth: run the CLI itself (REPL or first-run wizard) ───
    # Used when the CLI manages auth internally via its own interactive flow.
    # Each provider optionally supplies:
    #   auth_hint         — instructions shown before opening the CLI
    #   auth_check_args   — sub-command to run afterwards; exit 0 = auth OK
    #   auth_settings_file — relative path under $HOME to check for auth success
    #                        (default: .gemini/settings.json)
    if info.get("interactive_auth"):
        from pathlib import Path

        default_hint = (
            "Choose your auth method (Google account or API key), then\n"
            "  type [cyan]/quit[/cyan] or press [cyan]Ctrl+C[/cyan] to return here."
        )
        hint = info.get("auth_hint", default_hint)
        rprint(
            f"\n[bold]Step 2 — Authenticate {info['display']}[/bold]\n"
            f"[dim]{hint}[/dim]\n"
        )
        await asyncio.to_thread(_run_interactive, [get_cli_path(provider)])

        # ── Determine auth success ────────────────────────────────────────
        if auth_check_args := info.get("auth_check_args"):
            # Provider supplies a status command (e.g. `claude auth status`)
            check = subprocess.run(
                [get_cli_path(provider)] + auth_check_args,
                capture_output=True,
            )
            success = check.returncode == 0
        else:
            # Settings-file check: provider wrote ~/.{dir}/settings.json
            settings_rel = info.get("auth_settings_file", ".gemini/settings.json")
            success = (Path.home() / settings_rel).exists()

        if success:
            _set_cli_authenticated(cfg_mgr, provider, True)
            rprint(f"\n[green]✓[/green] {info['display']} authenticated and ready!")
            return True
        rprint(
            f"\n[yellow]⚠[/yellow] Auth not completed.\n"
            f"  Run [cyan]/connect {provider}[/cyan] again to retry."
        )
        return False

    # ── Auth step — browser OAuth via provider CLI ──────────────────────
    # API keys are NEVER prompted interactively. They must be set via
    # environment variable or ~/.uai/config.yaml. CLI providers authenticate
    # via their own OAuth flow (auth_args).
    if auth_args := info.get("auth_args"):
        # Show provider-specific instructions if available (e.g., code-paste step)
        auth_note = info.get("auth_note", "")
        rprint(
            f"\n[bold]Step 2 — Authenticate {info['display']}[/bold]\n"
            f"[dim]A browser window will open. Sign in, then return to this terminal.[/dim]"
            + (f"\n[dim]{auth_note}[/dim]" if auth_note else "")
            + "\n"
        )
        cmd = [get_cli_path(provider)] + auth_args
        # Use asyncio.to_thread so subprocess.run() runs in a thread pool with
        # full TTY access — the user can type/paste the authorization code normally.
        returncode = await asyncio.to_thread(_run_interactive, cmd)

        if returncode == 0:
            _set_cli_authenticated(cfg_mgr, provider, True)
            rprint(f"\n[green]✓[/green] {info['display']} authenticated and ready!")
            return True
        rprint(
            f"\n[yellow]⚠[/yellow] Authentication may not have completed "
            f"(exit code {returncode}).\n"
            f"  Run [cyan]/connect {provider}[/cyan] to retry."
        )
        return False

    return True


def connect(
    provider: str = typer.Argument(
        ...,
        help="Provider name (gemini, qwen, claude, codex, ollama, groq, deepseek)",
    ),
) -> None:
    """
    Install the CLI for an AI provider (or show how to configure API-only providers).

    CLI-based providers (gemini, qwen, claude, codex) are installed via npm
    and use OAuth — no API key needed.

    API-only providers (groq, deepseek) have no CLI. Set their key as an environment
    variable or add it to [cyan]~/.uai/config.yaml[/cyan].
    """
    ok = asyncio.run(connect_provider(provider))
    if not ok:
        raise typer.Exit(1)
