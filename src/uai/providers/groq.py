"""Groq provider — ultra-low latency inference via LPU, generous free tier."""
from __future__ import annotations
import asyncio
import time
from typing import Any

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import APIProviderMixin, AuthError, ProviderError, ProviderResponse


class GroqProvider(APIProviderMixin):
    name = "groq"
    display_name = "Groq"
    is_free = True   # Free tier with rate limits (requests/minute)
    capabilities = [
        TaskCapability.GENERAL_CHAT,
        TaskCapability.CODE_GENERATION,
        TaskCapability.CODE_REVIEW,
        TaskCapability.DEBUGGING,
    ]
    supported_backends = [BackendType.API]
    context_window_tokens = 128_000

    BASE_URL = "https://api.groq.com/openai/v1"
    MODELS: dict[str, dict[str, Any]] = {
        "llama": {"id": "llama-3.3-70b-versatile", "cost_input": 0.0, "cost_output": 0.0},
        "gemma": {"id": "gemma2-9b-it",            "cost_input": 0.0, "cost_output": 0.0},
        "deepseek": {"id": "deepseek-r1-distill-llama-70b", "cost_input": 0.0, "cost_output": 0.0},
    }
    DEFAULT_MODEL = "llama"

    # ------------------------------------------------------------------
    async def send(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
        backend: BackendType | None = None,
        timeout: int = 60,
        output_json: bool = False,
    ) -> ProviderResponse:
        api_key = self._auth.get_credential("groq", "api_key")
        if not api_key:
            raise AuthError("Groq API key not configured. Run: uai connect groq")

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ProviderError("openai not installed. Run: pip install openai")

        model_id = self._resolve_model_alias(model)
        client = AsyncOpenAI(api_key=api_key, base_url=self.BASE_URL)
        messages = self._build_openai_history(history, prompt)

        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(model=model_id, messages=messages),  # type: ignore[arg-type]
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ProviderError(f"Groq API timed out after {timeout}s")

        latency = (time.monotonic() - t0) * 1000
        text = response.choices[0].message.content or ""

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.API,
            tokens_input=response.usage.prompt_tokens if response.usage else None,
            tokens_output=response.usage.completion_tokens if response.usage else None,
            cost_usd=0.0,
            latency_ms=latency,
        )

    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens from Groq API (OpenAI-compatible streaming)."""
        api_key = self._auth.get_credential("groq", "api_key")
        if not api_key:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        try:
            from openai import AsyncOpenAI
        except ImportError:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        model_id = self._resolve_model_alias(model)
        client = AsyncOpenAI(api_key=api_key, base_url=self.BASE_URL)
        messages = self._build_openai_history(history, prompt)

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

    async def health_check(self) -> ProviderStatus:
        if self._auth.get_credential("groq", "api_key"):
            return ProviderStatus.AVAILABLE
        return ProviderStatus.NOT_CONFIGURED

    def is_configured(self) -> bool:
        return bool(self._auth.get_credential("groq", "api_key"))

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        return 0.0

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": k, **v} for k, v in self.MODELS.items()]
