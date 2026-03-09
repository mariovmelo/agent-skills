"""Authentication manager — secure credential storage."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Provider credential definitions
# ──────────────────────────────────────────────────────────────────────────────

PROVIDER_CREDENTIALS: dict[str, list[dict[str, str]]] = {
    "claude": [
        {"key": "api_key", "label": "Anthropic API Key", "env": "ANTHROPIC_API_KEY"},
    ],
    "gemini": [
        {"key": "api_key", "label": "Gemini API Key", "env": "GEMINI_API_KEY"},
    ],
    "codex": [
        {"key": "api_key", "label": "OpenAI API Key", "env": "OPENAI_API_KEY"},
    ],
    "qwen": [
        # qwen-code uses OAuth stored locally; we store the OpenRouter key as fallback
        {"key": "openrouter_key", "label": "OpenRouter API Key (optional)", "env": "OPENROUTER_API_KEY"},
    ],
    "deepseek": [
        {"key": "api_key", "label": "DeepSeek API Key", "env": "DEEPSEEK_API_KEY"},
    ],
    "groq": [
        {"key": "api_key", "label": "Groq API Key", "env": "GROQ_API_KEY"},
    ],
}


class AuthManager:
    """
    Credential storage with two backends:
    1. System keyring (macOS Keychain, GNOME Keyring, Windows Credential Locker)
    2. Encrypted JSON file fallback for headless/CI environments
    """

    SERVICE_PREFIX = "uai"

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._fallback_path = config_dir / "credentials.enc"
        self._use_keyring = self._check_keyring()

    # ------------------------------------------------------------------
    def set_credential(self, provider: str, key_name: str, value: str) -> None:
        """Persist a credential for a provider."""
        service = f"{self.SERVICE_PREFIX}.{provider}"
        if self._use_keyring:
            import keyring
            keyring.set_password(service, key_name, value)
        else:
            self._fb_set(provider, key_name, value)

    def get_credential(self, provider: str, key_name: str) -> str | None:
        """Retrieve a credential. Checks env vars first, then storage."""
        # 1. Environment variable override (useful for CI/CD)
        creds = PROVIDER_CREDENTIALS.get(provider, [])
        for cred in creds:
            if cred["key"] == key_name:
                env_val = os.environ.get(cred.get("env", ""))
                if env_val:
                    return env_val

        # 2. Storage
        service = f"{self.SERVICE_PREFIX}.{provider}"
        if self._use_keyring:
            import keyring
            return keyring.get_password(service, key_name)
        return self._fb_get(provider, key_name)

    def delete_credential(self, provider: str, key_name: str) -> None:
        service = f"{self.SERVICE_PREFIX}.{provider}"
        if self._use_keyring:
            import keyring
            try:
                keyring.delete_password(service, key_name)
            except Exception:
                pass
        else:
            self._fb_delete(provider, key_name)

    def is_provider_configured(self, provider: str) -> bool:
        """Returns True if the provider has at least one credential set (or needs none)."""
        creds = PROVIDER_CREDENTIALS.get(provider, [])
        if not creds:
            return True  # Ollama and similar require no credentials
        # Check if any required credential is available
        for cred in creds:
            if self.get_credential(provider, cred["key"]):
                return True
        return False

    def list_configured_providers(self) -> list[str]:
        return [p for p in PROVIDER_CREDENTIALS if self.is_provider_configured(p)]

    # ------------------------------------------------------------------
    # Fallback: encrypted JSON file (Fernet symmetric encryption)
    # ------------------------------------------------------------------

    def _check_keyring(self) -> bool:
        try:
            import keyring
            # Probe with a dummy read; FailKeyring / NoKeyringError raises here
            keyring.get_password("__uai_probe__", "__probe__")
            return True
        except Exception:
            return False

    def _fb_load(self) -> dict[str, dict[str, str]]:
        if not self._fallback_path.exists():
            return {}
        try:
            key = self._derive_key()
            from cryptography.fernet import Fernet
            f = Fernet(key)
            data = f.decrypt(self._fallback_path.read_bytes())
            return json.loads(data)
        except Exception:
            return {}

    def _fb_save(self, data: dict[str, dict[str, str]]) -> None:
        key = self._derive_key()
        from cryptography.fernet import Fernet
        f = Fernet(key)
        encrypted = f.encrypt(json.dumps(data).encode())
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path.write_bytes(encrypted)

    def _fb_set(self, provider: str, key_name: str, value: str) -> None:
        data = self._fb_load()
        data.setdefault(provider, {})[key_name] = value
        self._fb_save(data)

    def _fb_get(self, provider: str, key_name: str) -> str | None:
        data = self._fb_load()
        return data.get(provider, {}).get(key_name)

    def _fb_delete(self, provider: str, key_name: str) -> None:
        data = self._fb_load()
        if provider in data and key_name in data[provider]:
            del data[provider][key_name]
            self._fb_save(data)

    def _derive_key(self) -> bytes:
        """Derive a stable Fernet key from machine-specific data."""
        import hashlib
        # os.getlogin() fails in headless/CI/Docker environments; use env fallback chain
        username = (
            os.environ.get("USER")
            or os.environ.get("LOGNAME")
            or os.environ.get("USERNAME")
            or "uai-default"
        )
        seed = f"uai-{username}-{Path.home()}".encode()
        digest = hashlib.sha256(seed).digest()
        return base64.urlsafe_b64encode(digest)
