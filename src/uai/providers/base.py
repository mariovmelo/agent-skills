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
        """Select backend based on config preference and what's available."""
        pref = getattr(self._cfg, "preferred_backend", "auto")
        if pref == "api" and BackendType.API in self.supported_backends:
            return BackendType.API
        if pref == "cli" and BackendType.CLI in self.supported_backends:
            return BackendType.CLI
        # Fallback: first in supported list
        return self.supported_backends[0] if self.supported_backends else BackendType.API

    def resolve_model(self, model_alias: str | None) -> str:
        """Map a short alias ('flash', 'pro') to a full model ID."""
        return model_alias or ""
