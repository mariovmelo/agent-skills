"""Abstract base class for all AI providers."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Any

from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.models.context import Message


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    backend: BackendType
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float | None = None
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: dict[str, Any] | None = None


class ProviderError(Exception):
    """Generic provider error."""


class RateLimitError(ProviderError):
    """Provider is rate-limited or quota exhausted."""


class AuthError(ProviderError):
    """Authentication / credential error."""


class ContextTooLargeError(ProviderError):
    """Prompt + history exceeds provider's context window."""


class BaseProvider(ABC):
    """
    Abstract base for all AI providers.

    Each provider MUST set class-level attributes:
        name, display_name, is_free, capabilities,
        supported_backends, context_window_tokens
    """

    name: str
    display_name: str
    is_free: bool                          # Default tier is free (no credit card needed)
    capabilities: list[TaskCapability]     # Ordered: first = strongest
    supported_backends: list[BackendType]
    context_window_tokens: int             # Max tokens the provider accepts

    def __init__(self, auth: Any, provider_cfg: Any) -> None:
        self._auth = auth
        self._cfg = provider_cfg

    # ------------------------------------------------------------------
    # Core methods — must be implemented
    # ------------------------------------------------------------------

    @abstractmethod
    async def send(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
        backend: BackendType | None = None,
        timeout: int = 120,
        output_json: bool = False,
    ) -> ProviderResponse:
        """Send a prompt (with optional conversation history) and return a response."""
        ...

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        """Quick liveness check. Should complete in <10 s."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """True if provider has the credentials/config it needs."""
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        """Estimate cost in USD. Return 0.0 for free providers."""
        ...

    # ------------------------------------------------------------------
    # Optional — providers may override
    # ------------------------------------------------------------------

    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens. Default: call send() and yield the full text."""
        response = await self.send(prompt, history=history, model=model)
        yield response.text

    def get_models(self) -> list[dict[str, Any]]:
        """Return metadata for all available models."""
        return []

    def format_history_as_text(self, history: list[Message]) -> str:
        """Format conversation history as plain text for CLI providers."""
        lines: list[str] = []
        for msg in history:
            role = msg.role.value.capitalize()
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def preferred_backend(self) -> BackendType:
        """Select backend based on config preference and what's available.

        Priority:
          - "api"        → always use API (if supported)
          - "cli"/"auto" → use CLI if installed; fall back to API when CLI absent
        """
        pref = getattr(self._cfg, "preferred_backend", "cli")

        # Explicit API preference — skip CLI detection
        if pref == "api":
            if BackendType.API in self.supported_backends:
                return BackendType.API
            return self.supported_backends[0] if self.supported_backends else BackendType.API

        # "cli" or "auto": prefer CLI when installed, fall back to API
        if BackendType.CLI in self.supported_backends:
            from uai.utils.installer import is_cli_installed
            if is_cli_installed(self.name):
                return BackendType.CLI
            # CLI not installed — use API if available (key may be in env/config)
            if BackendType.API in self.supported_backends:
                return BackendType.API

        return self.supported_backends[0] if self.supported_backends else BackendType.API

    def resolve_model(self, model_alias: str | None) -> str:
        """Map a short alias ('flash', 'pro') to a full model ID."""
        return model_alias or ""

    @staticmethod
    def is_rate_limit_error(error_message: str, status_code: int | None = None) -> bool:
        """Standardized check for rate limit errors across providers."""
        lower_msg = error_message.lower()
        if (
            "rate limit" in lower_msg
            or "resource exhausted" in lower_msg
            or "quota exceeded" in lower_msg
            or "429" in lower_msg  # HTTP 429 Too Many Requests
        ):
            return True
        if status_code == 429:
            return True
        return False


class APIProviderMixin(BaseProvider):
    """
    Mixin for API-based providers with an OpenAI-compatible message format.

    Provides helpers for history formatting and model resolution that are
    duplicated across claude, groq, deepseek, ollama, and qwen providers.
    """

    # Subclasses must define these at class level
    MODELS: dict[str, dict] = {}
    DEFAULT_MODEL: str = ""

    def _build_openai_history(
        self,
        history: list[Message] | None,
        prompt: str,
    ) -> list[dict[str, str]]:
        """Build an OpenAI-compatible messages list from conversation history."""
        messages: list[dict[str, str]] = []
        if history:
            for msg in history:
                if msg.role.value in ("user", "assistant"):
                    messages.append({"role": msg.role.value, "content": msg.content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _resolve_model_alias(self, alias: str | None) -> str:
        """Map a short model alias to the full model ID via MODELS dict."""
        resolved = alias or getattr(self._cfg, "default_model", None) or self.DEFAULT_MODEL
        return self.MODELS.get(resolved, {}).get("id", resolved)  # type: ignore[attr-defined]
