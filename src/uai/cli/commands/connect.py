"""uai connect <provider> — connect an AI account."""
from __future__ import annotations
import asyncio
import typer
from rich import print as rprint
from rich.console import Console

console = Console()

_CONNECT_INSTRUCTIONS: dict[str, str] = {
    "claude":   "Get your API key at https://console.anthropic.com/",
    "gemini":   "Get your API key at https://aistudio.google.com/app/apikey",
    "codex":    "Get your API key at https://platform.openai.com/api-keys",
    "qwen":     "Get your OpenRouter key at https://openrouter.ai/keys (free tier available)\n"
                "  Or install qwen-code CLI for OAuth: npm install -g @qwen/qwen-code",
    "deepseek": "Get your API key at https://platform.deepseek.com/",
    "groq":     "Get your API key at https://console.groq.com/keys (free tier)",
    "ollama":   "No API key needed. Ollama runs locally.\n"
                "  Install: curl -fsSL https://ollama.ai/install.sh | sh\n"
                "  Pull a model: ollama pull qwen2.5-coder",
}

_CREDENTIAL_KEYS: dict[str, str] = {
    "claude":   "api_key",
    "gemini":   "api_key",
    "codex":    "api_key",
    "qwen":     "openrouter_key",
    "deepseek": "api_key",
    "groq":     "api_key",
}


def connect(
    provider: str = typer.Argument(..., help="Provider name (claude, gemini, codex, qwen, ollama, deepseek, groq)"),
    key: str = typer.Option(None, "--key", "-k", help="Pass API key directly (instead of interactive prompt)"),
    test: bool = typer.Option(True, "--test/--no-test", help="Test connection after saving"),
) -> None:
    """Connect an AI provider account."""
    from uai.core.config import ConfigManager
    from uai.core.auth import AuthManager

    cfg_mgr = ConfigManager()
    cfg_mgr.initialize()
    auth = AuthManager(cfg_mgr.config_dir)

    rprint(f"\n[bold cyan]Connecting {provider}...[/bold cyan]")

    # Ollama: no credentials needed
    if provider == "ollama":
        rprint(_CONNECT_INSTRUCTIONS["ollama"])
        rprint("\n[green]✓ Ollama requires no credentials — just ensure it's running.[/green]")
        rprint("  Test with: [cyan]uai status[/cyan]")
        return

    if provider not in _CONNECT_INSTRUCTIONS:
        rprint(f"[red]Unknown provider: {provider}[/red]")
        rprint(f"Available: {', '.join(_CONNECT_INSTRUCTIONS.keys())}")
        raise typer.Exit(1)

    rprint(f"[dim]{_CONNECT_INSTRUCTIONS[provider]}[/dim]\n")

    cred_key = _CREDENTIAL_KEYS.get(provider, "api_key")

    # Get the API key
    if key:
        api_key = key
    else:
        api_key = typer.prompt(
            f"Enter your {provider} API key",
            hide_input=True,
            confirmation_prompt=False,
        )

    if not api_key.strip():
        rprint("[red]No key provided. Aborted.[/red]")
        raise typer.Exit(1)

    auth.set_credential(provider, cred_key, api_key.strip())
    rprint(f"[green]✓ Credentials saved securely.[/green]")

    # Enable provider in config
    cfg = cfg_mgr.load()
    if provider in cfg.providers:
        cfg.providers[provider].enabled = True
        cfg_mgr.save(cfg)

    # Test the connection
    if test:
        rprint("Testing connection...", end=" ")
        ok, message = asyncio.run(_test_connection(provider, auth, cfg_mgr))
        if ok:
            rprint(f"[green]✓ {message}[/green]")
        else:
            rprint(f"[yellow]⚠ {message}[/yellow]")

    rprint(f"\n[green]{provider} connected![/green] Use [cyan]uai ask \"hello\"[/cyan] to try it.")


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
