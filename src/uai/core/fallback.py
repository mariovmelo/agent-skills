"""Fallback chain — 3-layer resilience ensuring users always get a response."""
from __future__ import annotations
import asyncio

from uai.core.context import ContextManager
from uai.core.quota import QuotaTracker
from uai.core.router import RoutingDecision
from uai.models.context import Message
from uai.models.provider import BackendType
from uai.models.quota import UsageRecord
from uai.models.request import UAIResponse
from uai.providers.base import (
    BaseProvider, ProviderError, ProviderResponse, RateLimitError, AuthError,
)


class AllProvidersFailedError(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        details = "\n".join(f"  {k}: {v}" for k, v in errors.items())
        super().__init__(f"All providers failed:\n{details}")


class FallbackChain:
    """
    Execute a request with automatic failover.

    Layer 1: retry within the same provider (transient errors)
    Layer 2: failover to alternative providers (hard failures)
    Layer 3: if API backend fails, try CLI backend of the same provider
    """

    def __init__(
        self,
        providers: dict[str, BaseProvider],
        quota: QuotaTracker,
    ) -> None:
        self._providers = providers
        self._quota = quota

    async def execute(
        self,
        prompt: str,
        decision: RoutingDecision,
        history: list[Message] | None = None,
        max_retries_per_provider: int = 2,
        backoff: tuple[float, ...] = (5.0, 15.0, 45.0),
    ) -> tuple[ProviderResponse, list[str]]:
        """
        Returns (ProviderResponse, providers_tried).
        Raises AllProvidersFailedError if everything fails.
        """
        chain = [decision.provider] + decision.alternatives
        errors: dict[str, str] = {}
        providers_tried: list[str] = []

        for provider_name in chain:
            provider = self._providers.get(provider_name)
            if provider is None:
                errors[provider_name] = "Provider not instantiated"
                continue

            # Use decision model/backend only for the primary provider
            is_primary = provider_name == decision.provider
            model = decision.model if is_primary else None
            preferred_backend = decision.backend if is_primary else None

            providers_tried.append(provider_name)

            # Layer 1: retry loop
            for attempt in range(1, max_retries_per_provider + 1):
                try:
                    response = await provider.send(
                        prompt=prompt,
                        history=history,
                        model=model,
                        backend=preferred_backend,
                        timeout=120,
                    )
                    # Success — record usage
                    self._record(provider_name, response, success=True)
                    return response, providers_tried

                except RateLimitError as e:
                    errors[provider_name] = f"RATE_LIMITED: {e}"
                    self._quota.set_cooldown(provider_name, 300)
                    self._record(provider_name, None, success=False, error=str(e))
                    break  # No retry on rate limit — move to next provider immediately

                except AuthError as e:
                    errors[provider_name] = f"AUTH_ERROR: {e}"
                    self._record(provider_name, None, success=False, error=str(e))
                    break  # No retry on auth error

                except ProviderError as e:
                    errors[provider_name] = f"ERROR: {e}"
                    self._record(provider_name, None, success=False, error=str(e))

                    # Layer 3: if API failed, try CLI on last attempt
                    if (
                        attempt == max_retries_per_provider
                        and preferred_backend == BackendType.API
                        and BackendType.CLI in provider.supported_backends
                    ):
                        try:
                            response = await provider.send(
                                prompt=prompt, history=history, model=model,
                                backend=BackendType.CLI, timeout=120,
                            )
                            self._record(provider_name, response, success=True)
                            return response, providers_tried
                        except Exception:
                            pass

                    if attempt < max_retries_per_provider:
                        wait = backoff[min(attempt - 1, len(backoff) - 1)]
                        await asyncio.sleep(wait)

        raise AllProvidersFailedError(errors)

    def _record(
        self,
        provider: str,
        response: ProviderResponse | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        self._quota.record(UsageRecord(
            provider=provider,
            model=response.model if response else "",
            backend=response.backend.value if response else "unknown",
            tokens_input=response.tokens_input or 0,
            tokens_output=response.tokens_output or 0,
            cost_usd=response.cost_usd or 0.0,
            latency_ms=response.latency_ms if response else 0.0,
            success=success,
            error=error,
        ))
