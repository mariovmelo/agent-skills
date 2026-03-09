"""Structured error system for UAI CLI."""
from __future__ import annotations
from enum import Enum


class ErrorCode(str, Enum):
    AUTH_MISSING        = "E001"
    AUTH_INVALID        = "E002"
    PROVIDER_TIMEOUT    = "E003"
    PROVIDER_RATE_LIMIT = "E004"
    NO_PROVIDER         = "E005"
    CONFIG_INVALID      = "E006"
    FILE_NOT_FOUND      = "E007"
    SHELL_EXEC_FAILED   = "E008"
    PROVIDER_ERROR      = "E009"
    CONTEXT_ERROR       = "E010"


class UAIError(Exception):
    """Base error for UAI with structured code and user-facing hint."""

    def __init__(self, code: ErrorCode, message: str, hint: str = "") -> None:
        self.code = code
        self.hint = hint
        super().__init__(message)

    def rich_format(self) -> str:
        base = f"[red][{self.code.value}][/red] {self}"
        if self.hint:
            base += f"\n[dim]Hint: {self.hint}[/dim]"
        return base


class AuthError(UAIError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(ErrorCode.AUTH_MISSING, message, hint)


class ProviderError(UAIError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(ErrorCode.PROVIDER_ERROR, message, hint)


class NoProviderAvailableError(UAIError):
    def __init__(self, message: str = "No provider available") -> None:
        super().__init__(
            ErrorCode.NO_PROVIDER,
            message,
            hint="Run 'uai status' to check provider health, or 'uai connect <provider>' to configure one.",
        )


class RateLimitError(UAIError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            ErrorCode.PROVIDER_RATE_LIMIT,
            f"Rate limit reached for {provider}",
            hint="UAI will automatically try the next provider in the fallback chain.",
        )


class ConfigError(UAIError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(ErrorCode.CONFIG_INVALID, message, hint)
