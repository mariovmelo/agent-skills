"""Auto-installer for AI CLIs."""
from __future__ import annotations
import os
import pathlib
import shutil
import subprocess
import sys

# User-local npm prefix used when the global prefix is not writable (e.g. /usr/lib)
_USER_NPM_PREFIX = pathlib.Path.home() / ".npm-global"

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


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _npm_global_prefix_writable() -> bool:
    """Return True if the current user can write to the npm global prefix dir."""
    npm = shutil.which("npm")
    if not npm:
        return False
    result = subprocess.run(
        [npm, "config", "get", "prefix"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    prefix = pathlib.Path(result.stdout.strip())
    return os.access(prefix, os.W_OK) or (
        not prefix.exists() and os.access(prefix.parent, os.W_OK)
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def is_cli_installed(provider: str) -> bool:
    """True if the provider CLI binary is accessible (PATH or user npm prefix)."""
    cli_name = str(CLI_INSTALL_COMMANDS.get(provider, {}).get("check", provider))
    if shutil.which(cli_name) is not None:
        return True
    # Also check user-local npm prefix (binary installed there but PATH not yet updated)
    return (_USER_NPM_PREFIX / "bin" / cli_name).exists()


def get_cli_path(provider: str) -> str:
    """
    Return the full path to the provider CLI binary.

    Resolution order:
      1. ``shutil.which()`` — binary already in PATH
      2. ``~/.npm-global/bin/<name>`` — installed to user prefix, PATH not yet updated
      3. Bare CLI name — will raise FileNotFoundError at runtime (clear error message)
    """
    cli_name = str(CLI_INSTALL_COMMANDS.get(provider, {}).get("check", provider))
    found = shutil.which(cli_name)
    if found:
        return found
    user_bin = _USER_NPM_PREFIX / "bin" / cli_name
    if user_bin.exists():
        return str(user_bin)
    return cli_name   # fallback — subprocess will raise FileNotFoundError


def install_cli(provider: str) -> bool:
    """
    Attempt to install the CLI for a provider.

    The subprocess inherits the current terminal (stdin/stdout/stderr) so
    interactive prompts, progress bars, and OAuth flows work normally.

    If the npm global prefix is not writable (common on Linux without sudo),
    installs to ``~/.npm-global`` instead and prints PATH setup instructions.

    Returns True on success, False on failure.
    """
    info = CLI_INSTALL_COMMANDS.get(provider)
    if not info:
        return False

    # ── npm package ──────────────────────────────────────────────────────────
    if "npm" in info:
        npm = shutil.which("npm")
        if not npm:
            print(f"  npm not found. Cannot auto-install {info['description']}.")
            return False

        cmd = [npm, "install", "-g", str(info["npm"])]

        # Use user-local prefix when the global one is not writable
        use_user_prefix = not _npm_global_prefix_writable()
        if use_user_prefix:
            _USER_NPM_PREFIX.mkdir(parents=True, exist_ok=True)
            cmd = [npm, "install", "-g", "--prefix", str(_USER_NPM_PREFIX), str(info["npm"])]

        result = subprocess.run(cmd)   # inherits terminal — interactive-friendly

        if result.returncode == 0 and use_user_prefix:
            bin_dir = _USER_NPM_PREFIX / "bin"
            print(
                f"\n  Installed to {bin_dir}\n"
                f"  To use '{info['check']}' from any terminal, add it to your PATH:\n"
                f"\n"
                f"    echo 'export PATH=\"{bin_dir}:$PATH\"' >> ~/.bashrc && source ~/.bashrc\n"
                f"\n"
                f"  (replace .bashrc with .zshrc if you use zsh)\n"
                f"  UAI will use the full path automatically without PATH changes."
            )

        return result.returncode == 0

    # ── shell script ─────────────────────────────────────────────────────────
    if "script" in info:
        result = subprocess.run(str(info["script"]), shell=True)   # inherits terminal
        return result.returncode == 0

    return False


def check_all_clis() -> dict[str, bool]:
    """Return {provider: is_installed} for all known CLIs."""
    return {name: is_cli_installed(name) for name in CLI_INSTALL_COMMANDS}


def npm_available() -> bool:
    return shutil.which("npm") is not None
