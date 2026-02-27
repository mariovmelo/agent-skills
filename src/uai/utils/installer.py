"""Auto-installer for AI CLIs."""
from __future__ import annotations
import shutil
import subprocess
import sys


CLI_INSTALL_COMMANDS: dict[str, dict[str, str | list[str]]] = {
    "claude": {
        "check": "claude",
        "npm": "@anthropic-ai/claude-code",
        "description": "Claude Code CLI",
    },
    "gemini": {
        "check": "gemini",
        "npm": "@google/gemini-cli",
        "description": "Gemini CLI",
    },
    "codex": {
        "check": "codex",
        "npm": "@openai/codex",
        "description": "OpenAI Codex CLI",
    },
    "qwen": {
        "check": "qwen",
        "npm": "@qwen/qwen-code",
        "description": "Qwen Code CLI",
    },
    "ollama": {
        "check": "ollama",
        "script": "curl -fsSL https://ollama.ai/install.sh | sh",
        "description": "Ollama (local AI runner)",
    },
}


def is_cli_installed(provider: str) -> bool:
    cli_name = CLI_INSTALL_COMMANDS.get(provider, {}).get("check", provider)
    return shutil.which(str(cli_name)) is not None


def install_cli(provider: str) -> bool:
    """
    Attempt to install the CLI for a provider.

    The subprocess inherits the current terminal (stdin/stdout/stderr) so
    interactive prompts, progress bars, and OAuth flows work normally.
    Returns True on success, False on failure.
    """
    info = CLI_INSTALL_COMMANDS.get(provider)
    if not info:
        return False

    # npm package install
    if "npm" in info:
        npm = shutil.which("npm")
        if not npm:
            print(f"  npm not found. Cannot auto-install {info['description']}.")
            return False
        cmd = [npm, "install", "-g", str(info["npm"])]
        result = subprocess.run(cmd)          # inherits terminal — interactive-friendly
        return result.returncode == 0

    # Shell script install
    if "script" in info:
        result = subprocess.run(str(info["script"]), shell=True)   # inherits terminal
        return result.returncode == 0

    return False


def check_all_clis() -> dict[str, bool]:
    """Return {provider: is_installed} for all known CLIs."""
    return {name: is_cli_installed(name) for name in CLI_INSTALL_COMMANDS}


def npm_available() -> bool:
    return shutil.which("npm") is not None
