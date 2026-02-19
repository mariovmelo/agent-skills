"""Codex provider — OpenAI Codex CLI + API.

CRITICAL: When calling codex CLI, OPENAI_BASE_URL and OPENAI_API_KEY must be
cleared from the environment to avoid conflicts with OpenRouter config.
"""
from __future__ import annotations
import asyncio
import os
import time
from typing import Any

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import (
    AuthError, BaseProvider, ProviderError, ProviderResponse, RateLimitError,
)


class CodexProvider(BaseProvider):
    name = "codex"
    display_name = "Codex CLI"
    is_free = False
    capabilities = [
        TaskCapability.DEBUGGING,
        TaskCapability.CODE_GENERATION,
        TaskCapability.CODE_REVIEW,
    ]
    supported_backends = [BackendType.CLI, BackendType.API]
    context_window_tokens = 128_000

    MODELS: dict[str, dict[str, Any]] = {
        "codex": {"id": "gpt-5.3-codex", "cost_input": 2.0, "cost_output": 8.0},
    }
    DEFAULT_MODEL = "codex"

    # ------------------------------------------------------------------
    async def send(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
        backend: BackendType | None = None,
        timeout: int = 300,
        output_json: bool = False,
    ) -> ProviderResponse:
        backend = backend or self.preferred_backend()
        if backend == BackendType.CLI:
            return await self._send_cli(prompt, history, timeout)
        return await self._send_api(prompt, history, model, timeout)

    # ------------------------------------------------------------------
    async def _send_cli(
        self,
        prompt: str,
        history: list[Message] | None,
        timeout: int,
    ) -> ProviderResponse:
        """
        IMPORTANT: sanitize env vars before calling codex CLI.
        If OPENAI_BASE_URL points to OpenRouter, codex will fail.
        """
        full_prompt = self._build_prompt(prompt, history)
        cmd = ["codex", "exec", "--skip-git-repo-check", full_prompt]

        # Build clean environment
        env = os.environ.copy()
        env.pop("OPENAI_BASE_URL", None)
        env.pop("OPENAI_API_KEY", None)

        # Re-inject codex's own key if stored
        codex_key = self._auth.get_credential("codex", "api_key")
        if codex_key:
            env["OPENAI_API_KEY"] = codex_key

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ProviderError(f"Codex CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise ProviderError("Codex CLI not found. Install: npm install -g @openai/codex")

        latency = (time.monotonic() - t0) * 1000
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            if "rate" in err.lower() or "quota" in err.lower():
                raise RateLimitError(f"Codex rate limit: {err}")
            if "auth" in err.lower() or "api key" in err.lower():
                raise AuthError(f"Codex auth error: {err}")
            raise ProviderError(f"Codex CLI error (exit {proc.returncode}): {err}")

        text = stdout.decode(errors="replace").strip()
        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self.MODELS[self.DEFAULT_MODEL]["id"],
            backend=BackendType.CLI,
            latency_ms=latency,
        )

    async def _send_api(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int,
    ) -> ProviderResponse:
        api_key = self._auth.get_credential("codex", "api_key")
        if not api_key:
            raise AuthError("OpenAI API key not configured for Codex. Run: uai connect codex")

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ProviderError("openai not installed. Run: pip install openai")

        # Use direct OpenAI endpoint (NOT OpenRouter)
        client = AsyncOpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
        model_id = self.MODELS.get(model or self.DEFAULT_MODEL, self.MODELS[self.DEFAULT_MODEL])["id"]

        messages: list[dict[str, str]] = []
        if history:
            for msg in history:
                if msg.role.value in ("user", "assistant"):
                    messages.append({"role": msg.role.value, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(model=model_id, messages=messages),  # type: ignore[arg-type]
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ProviderError(f"Codex API timed out after {timeout}s")

        latency = (time.monotonic() - t0) * 1000
        text = response.choices[0].message.content or ""
        usage = response.usage
        alias = model or self.DEFAULT_MODEL
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

    # ------------------------------------------------------------------
    async def health_check(self) -> ProviderStatus:
        from uai.utils.installer import is_cli_installed
        if is_cli_installed("codex"):
            return ProviderStatus.AVAILABLE
        if self._auth.get_credential("codex", "api_key"):
            return ProviderStatus.AVAILABLE
        return ProviderStatus.NOT_CONFIGURED

    def is_configured(self) -> bool:
        from uai.utils.installer import is_cli_installed
        return is_cli_installed("codex") or bool(self._auth.get_credential("codex", "api_key"))

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        alias = model or self.DEFAULT_MODEL
        info = self.MODELS.get(alias, self.MODELS[self.DEFAULT_MODEL])
        return (input_tokens / 1_000_000) * info["cost_input"] + (output_tokens / 1_000_000) * info["cost_output"]

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": k, **v} for k, v in self.MODELS.items()]

    # ------------------------------------------------------------------
    def _build_prompt(self, prompt: str, history: list[Message] | None) -> str:
        if not history:
            return prompt
        history_text = self.format_history_as_text(history)
        return f"Context:\n{history_text}\n\nTask: {prompt}"
