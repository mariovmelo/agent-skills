"""Tests for src/uai/core/errors.py"""
from __future__ import annotations
import pytest

from uai.core.errors import (
    AuthError,
    ConfigError,
    ErrorCode,
    NoProviderAvailableError,
    ProviderError,
    RateLimitError,
    UAIError,
)


class TestErrorCode:
    def test_has_ten_members(self):
        assert len(ErrorCode) == 10

    def test_values_start_with_e(self):
        for member in ErrorCode:
            assert member.value.startswith("E"), f"{member.value} does not start with 'E'"

    def test_known_codes(self):
        assert ErrorCode.AUTH_MISSING.value == "E001"
        assert ErrorCode.NO_PROVIDER.value == "E005"
        assert ErrorCode.CONFIG_INVALID.value == "E006"


class TestUAIError:
    def test_rich_format_with_hint(self):
        err = UAIError(ErrorCode.AUTH_MISSING, "test message", hint="do this")
        fmt = err.rich_format()
        assert "[red]" in fmt
        assert "E001" in fmt
        assert "test message" in fmt
        assert "Hint:" in fmt
        assert "do this" in fmt

    def test_rich_format_without_hint(self):
        err = UAIError(ErrorCode.AUTH_MISSING, "test message")
        fmt = err.rich_format()
        assert "test message" in fmt
        assert "Hint:" not in fmt

    def test_is_exception(self):
        err = UAIError(ErrorCode.CONFIG_INVALID, "bad config")
        with pytest.raises(UAIError):
            raise err


class TestAuthError:
    def test_code_is_auth_missing(self):
        err = AuthError("missing credentials")
        assert err.code == ErrorCode.AUTH_MISSING

    def test_message_non_empty(self):
        err = AuthError("something")
        assert str(err) != ""

    def test_with_hint(self):
        err = AuthError("missing", hint="run uai connect")
        assert err.hint == "run uai connect"


class TestProviderError:
    def test_code_is_provider_error(self):
        err = ProviderError("timeout")
        assert err.code == ErrorCode.PROVIDER_ERROR


class TestNoProviderAvailableError:
    def test_has_code(self):
        err = NoProviderAvailableError()
        assert err.code == ErrorCode.NO_PROVIDER

    def test_has_message(self):
        err = NoProviderAvailableError()
        assert str(err) != ""

    def test_has_hint(self):
        err = NoProviderAvailableError()
        assert err.hint != ""

    def test_custom_message(self):
        err = NoProviderAvailableError("nothing available")
        assert "nothing available" in str(err)


class TestRateLimitError:
    def test_message_contains_provider(self):
        err = RateLimitError("gemini")
        assert "gemini" in str(err)

    def test_code_is_rate_limit(self):
        err = RateLimitError("groq")
        assert err.code == ErrorCode.PROVIDER_RATE_LIMIT

    def test_has_hint(self):
        err = RateLimitError("claude")
        assert err.hint != ""


class TestConfigError:
    def test_message_contains_text(self):
        err = ConfigError("bad yaml syntax")
        assert "bad yaml" in str(err)

    def test_code_is_config_invalid(self):
        err = ConfigError("bad")
        assert err.code == ErrorCode.CONFIG_INVALID
