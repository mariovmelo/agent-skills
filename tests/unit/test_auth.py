"""Tests for src/uai/core/auth.py"""
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from uai.core.auth import AuthManager, PROVIDER_CREDENTIALS


class TestDeriveKey:
    def test_returns_bytes(self, tmp_dir):
        auth = AuthManager(tmp_dir)
        key = auth._derive_key()
        assert isinstance(key, bytes)

    def test_deterministic_with_same_user(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("USER", "testuser")
        monkeypatch.delenv("LOGNAME", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        auth = AuthManager(tmp_dir)
        key1 = auth._derive_key()
        key2 = auth._derive_key()
        assert key1 == key2

    def test_uses_logname_fallback(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.setenv("LOGNAME", "loguser")
        monkeypatch.delenv("USERNAME", raising=False)
        auth = AuthManager(tmp_dir)
        key = auth._derive_key()
        assert isinstance(key, bytes)

    def test_uses_username_fallback(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("LOGNAME", raising=False)
        monkeypatch.setenv("USERNAME", "winuser")
        auth = AuthManager(tmp_dir)
        key = auth._derive_key()
        assert isinstance(key, bytes)

    def test_fallback_to_uai_default(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("LOGNAME", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        auth = AuthManager(tmp_dir)
        key = auth._derive_key()
        # Should not raise and should return bytes
        assert isinstance(key, bytes)


class TestGetCredentialEnvVar:
    def test_env_var_returned_first(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-value")
        auth = AuthManager(tmp_dir)
        result = auth.get_credential("claude", "api_key")
        assert result == "env-key-value"

    def test_gemini_env_var(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-env-key")
        auth = AuthManager(tmp_dir)
        result = auth.get_credential("gemini", "api_key")
        assert result == "gemini-env-key"

    def test_returns_none_when_no_env_and_no_stored(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Force fallback file path (no keyring in test environment)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False
        result = auth.get_credential("claude", "api_key")
        assert result is None


class TestCredentialRoundTrip:
    def test_set_then_get(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False  # Force fallback file
        auth.set_credential("claude", "api_key", "my-secret-key")
        result = auth.get_credential("claude", "api_key")
        assert result == "my-secret-key"

    def test_delete_then_get_returns_none(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False
        auth.set_credential("claude", "api_key", "to-delete")
        auth.delete_credential("claude", "api_key")
        result = auth.get_credential("claude", "api_key")
        assert result is None

    def test_overwrite_credential(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False
        auth.set_credential("gemini", "api_key", "first-key")
        auth.set_credential("gemini", "api_key", "second-key")
        result = auth.get_credential("gemini", "api_key")
        assert result == "second-key"


class TestIsProviderConfigured:
    def test_ollama_always_configured(self, tmp_dir):
        auth = AuthManager(tmp_dir)
        # Ollama has no credentials in PROVIDER_CREDENTIALS
        assert auth.is_provider_configured("ollama") is True

    def test_unconfigured_provider(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False
        assert auth.is_provider_configured("claude") is False

    def test_configured_via_env(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
        auth = AuthManager(tmp_dir)
        assert auth.is_provider_configured("groq") is True


_ALL_API_ENV_VARS = [
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
    "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
]


class TestListConfiguredProviders:
    def test_gemini_after_set(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False
        auth.set_credential("gemini", "api_key", "test-key")
        providers = auth.list_configured_providers()
        assert "gemini" in providers

    def test_returns_list(self, tmp_dir, monkeypatch):
        for env in _ALL_API_ENV_VARS:
            monkeypatch.delenv(env, raising=False)
        auth = AuthManager(tmp_dir)
        auth._use_keyring = False
        providers = auth.list_configured_providers()
        assert isinstance(providers, list)


class TestProviderCredentialsRegistry:
    def test_claude_has_api_key(self):
        assert any(c["key"] == "api_key" for c in PROVIDER_CREDENTIALS["claude"])

    def test_all_creds_have_env_key(self):
        for provider, creds in PROVIDER_CREDENTIALS.items():
            for cred in creds:
                assert "env" in cred, f"{provider} credential missing 'env' field"
