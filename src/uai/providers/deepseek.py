"""DeepSeek provider — OpenAI-compatible API, very low cost."""
from __future__ import annotations
import asyncio
import time
from typing import Any

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import APIProviderMixin, AuthError, ProviderError, ProviderResponse


class DeepSeekProvider(APIProviderMixin):
    name = "deepseek"
    display_name = "DeepSeek"
    is_free = False   # Has free tier but with limits; cost is negligible
    capabilities = [
        TaskCapability.CODE_GENERATION,
        TaskCapability.DEBUGGING,
        TaskCapability.CODE_REVIEW,
        TaskCapability.GENERAL_CHAT,
    ]
    supported_backends = [BackendType.API]
    context_window_tokens = 64_000

    BASE_URL = "https://api.deepseek.com/v1"
    MODELS: dict[str, dict[str, Any]] = {
        "chat":  {"id": "deepseek-chat",  "cost_input": 0.14, "cost_output": 0.28},
        "coder": {"id": "deepseek-coder", "cost_input": 0.14, "cost_output": 0.28},
    }
    DEFAULT_MODEL = "coder"

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
        api_key = self._auth.get_credential("deepseek", "api_key")
        if not api_key:
            raise AuthError("DeepSeek API key not configured. Run: uai connect deepseek")

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
            raise ProviderError(f"DeepSeek API timed out after {timeout}s")

        latency = (time.monotonic() - t0) * 1000
        text = response.choices[0].message.content or ""
        usage = response.usage
        alias = model or self._cfg.default_model or self.DEFAULT_MODEL
        info = self.MODELS.get(alias, self.MODELS[self.DEFAULT_MODEL])
        cost = 0.0
        if usage:
            cost = (
                (usage.prompt_tokens / 1_000_000) * info["cost_input"]
                + (usage.completion_tokens / 1_000_000) * info["cost_output"]
            )

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.API,
            tokens_input=usage.prompt_tokens if usage else None,
            tokens_output=usage.completion_tokens if usage else None,
            cost_usd=cost,
            latency_ms=latency,
        )

    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens from DeepSeek API (OpenAI-compatible streaming)."""
        api_key = self._auth.get_credential("deepseek", "api_key")
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
        if self._auth.get_credential("deepseek", "api_key"):
            return ProviderStatus.AVAILABLE
        return ProviderStatus.NOT_CONFIGURED

    def is_configured(self) -> bool:
        return bool(self._auth.get_credential("deepseek", "api_key"))

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        alias = model or self.DEFAULT_MODEL
        info = self.MODELS.get(alias, self.MODELS[self.DEFAULT_MODEL])
        return (input_tokens / 1_000_000) * info["cost_input"] + (output_tokens / 1_000_000) * info["cost_output"]

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": k, **v} for k, v in self.MODELS.items()]
