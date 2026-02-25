"""Ollama provider — local model runner, completely free, no internet needed."""
from __future__ import annotations
import asyncio
import time
from typing import Any

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import APIProviderMixin, ProviderError, ProviderResponse


class OllamaProvider(APIProviderMixin):
    name = "ollama"
    display_name = "Ollama (local)"
    is_free = True
    capabilities = [
        TaskCapability.CODE_GENERATION,
        TaskCapability.CODE_REVIEW,
        TaskCapability.GENERAL_CHAT,
        TaskCapability.DEBUGGING,
        TaskCapability.BATCH_PROCESSING,
    ]
    supported_backends = [BackendType.API]   # Ollama exposes an OpenAI-compatible HTTP API
    context_window_tokens = 128_000

    DEFAULT_MODEL = "qwen2.5-coder"

    # ------------------------------------------------------------------
    async def send(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
        backend: BackendType | None = None,
        timeout: int = 120,
        output_json: bool = False,
    ) -> ProviderResponse:
        base_url = getattr(self._cfg, "base_url", "http://localhost:11434")
        model_id = model or self._cfg.default_model or self.DEFAULT_MODEL

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ProviderError("openai not installed. Run: pip install openai")

        client = AsyncOpenAI(base_url=f"{base_url}/v1", api_key="ollama")

        messages: list[dict[str, str]] = []
        if history:
            for msg in history:
                messages.append({"role": msg.role.value, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(model=model_id, messages=messages),  # type: ignore[arg-type]
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ProviderError(f"Ollama timed out after {timeout}s — model may still be loading")
        except Exception as e:
            raise ProviderError(f"Ollama connection error: {e}. Is Ollama running?")

        latency = (time.monotonic() - t0) * 1000
        text = response.choices[0].message.content or ""
        usage = response.usage

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.API,
            tokens_input=usage.prompt_tokens if usage else None,
            tokens_output=usage.completion_tokens if usage else None,
            cost_usd=0.0,
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens from local Ollama server (OpenAI-compatible streaming)."""
        base_url = getattr(self._cfg, "base_url", "http://localhost:11434")
        model_id = model or self._cfg.default_model or self.DEFAULT_MODEL

        try:
            from openai import AsyncOpenAI
        except ImportError:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        client = AsyncOpenAI(base_url=f"{base_url}/v1", api_key="ollama")

        messages: list[dict[str, str]] = []
        if history:
            for msg in history:
                messages.append({"role": msg.role.value, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = await client.chat.completions.create(
                model=model_id, messages=messages, stream=True  # type: ignore[arg-type]
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except Exception:
            response = await self.send(prompt, history=history, model=model)
            yield response.text

    # ------------------------------------------------------------------
    async def health_check(self) -> ProviderStatus:
        base_url = getattr(self._cfg, "base_url", "http://localhost:11434")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{base_url}/api/tags")
                if r.status_code == 200:
                    return ProviderStatus.AVAILABLE
        except Exception:
            pass
        return ProviderStatus.UNAVAILABLE

    def is_configured(self) -> bool:
        return True   # No credentials needed; just needs Ollama running

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        return 0.0

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": "default", "id": self.DEFAULT_MODEL, "cost_input": 0.0, "cost_output": 0.0}]
