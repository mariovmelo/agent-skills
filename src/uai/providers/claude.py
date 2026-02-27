"""Claude provider — Anthropic API (anthropic SDK) + Claude Code CLI."""
from __future__ import annotations
import asyncio
import time
from typing import Any

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import (
    APIProviderMixin, AuthError, ProviderError, ProviderResponse, RateLimitError,
)
from uai.utils.installer import get_cli_path


class ClaudeProvider(APIProviderMixin):
    name = "claude"
    display_name = "Claude"
    is_free = False
    capabilities = [
        TaskCapability.ARCHITECTURE,
        TaskCapability.CODE_REVIEW,
        TaskCapability.DEBUGGING,
        TaskCapability.CODE_GENERATION,
        TaskCapability.GENERAL_CHAT,
        TaskCapability.PRIVACY_AUDIT,
    ]
    supported_backends = [BackendType.CLI, BackendType.API]
    context_window_tokens = 200_000

    MODELS: dict[str, dict[str, Any]] = {
        "opus":   {"id": "claude-opus-4-6",              "cost_input": 15.0,  "cost_output": 75.0},
        "sonnet": {"id": "claude-sonnet-4-5-20250929",   "cost_input": 3.0,   "cost_output": 15.0},
        "haiku":  {"id": "claude-haiku-4-5-20251001",    "cost_input": 0.80,  "cost_output": 4.0},
    }
    DEFAULT_MODEL = "sonnet"

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
        backend = backend or self.preferred_backend()
        if backend == BackendType.CLI:
            return await self._send_cli(prompt, history, model, timeout)
        return await self._send_api(prompt, history, model, timeout)

    # ------------------------------------------------------------------
    async def _send_api(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int,
    ) -> ProviderResponse:
        api_key = self._auth.get_credential("claude", "api_key")
        if not api_key:
            raise AuthError("Anthropic API key not configured. Run: uai connect claude")

        try:
            import anthropic
        except ImportError:
            raise ProviderError("anthropic not installed. Run: pip install anthropic")

        model_id = self._resolve_model_alias(model)
        client = anthropic.AsyncAnthropic(api_key=api_key)
        messages = self._build_openai_history(history, prompt)

        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model_id,
                    max_tokens=4096,
                    messages=messages,  # type: ignore[arg-type]
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ProviderError(f"Claude API timed out after {timeout}s")
        except anthropic.RateLimitError as e:
            raise RateLimitError(str(e))
        except anthropic.AuthenticationError as e:
            raise AuthError(str(e))

        latency = (time.monotonic() - t0) * 1000
        text = response.content[0].text if response.content else ""
        usage = response.usage
        model_info = self.MODELS.get(model or self.DEFAULT_MODEL, {})
        cost = (
            (usage.input_tokens / 1_000_000) * model_info.get("cost_input", 0)
            + (usage.output_tokens / 1_000_000) * model_info.get("cost_output", 0)
        )

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.API,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
            cost_usd=cost,
            latency_ms=latency,
        )

    async def _send_cli(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int,
    ) -> ProviderResponse:
        """Use claude -p in headless mode."""
        full_prompt = self._build_prompt(prompt, history)
        model_id = self._resolve_model_alias(model)
        cmd = [get_cli_path("claude"), "-p", full_prompt, "--model", model_id]

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ProviderError(f"Claude CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise ProviderError(
                "Claude CLI not found. Install: npm install -g @anthropic-ai/claude-code"
            )

        latency = (time.monotonic() - t0) * 1000
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise ProviderError(f"Claude CLI error (exit {proc.returncode}): {err}")

        text = stdout.decode(errors="replace").strip()
        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.CLI,
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    async def health_check(self) -> ProviderStatus:
        from uai.utils.installer import is_cli_installed
        if is_cli_installed("claude"):
            return ProviderStatus.AVAILABLE
        if self._auth.get_credential("claude", "api_key"):
            return ProviderStatus.AVAILABLE
        return ProviderStatus.NOT_CONFIGURED

    def is_configured(self) -> bool:
        from uai.utils.installer import is_cli_installed
        # CLI path: binary must exist AND OAuth must have been completed
        if is_cli_installed("claude") and getattr(self._cfg, "cli_authenticated", False):
            return True
        # API fallback: key set manually in env / config
        return bool(self._auth.get_credential("claude", "api_key"))

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        alias = model or self.DEFAULT_MODEL
        info = self.MODELS.get(alias, self.MODELS[self.DEFAULT_MODEL])
        return (input_tokens / 1_000_000) * info["cost_input"] + (output_tokens / 1_000_000) * info["cost_output"]

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": k, **v} for k, v in self.MODELS.items()]

    # ------------------------------------------------------------------
    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens. Uses CLI when installed (preferred), falls back to API streaming."""
        backend = self.preferred_backend()

        # CLI backend: single yield (CLIs don't support streaming)
        if backend == BackendType.CLI:
            response = await self._send_cli(prompt, history, model, timeout=120)
            yield response.text
            return

        # API backend: true streaming via Anthropic SDK
        api_key = self._auth.get_credential("claude", "api_key")
        if not api_key:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        try:
            import anthropic as _anthropic
        except ImportError:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        model_id = self._resolve_model_alias(model)
        client = _anthropic.AsyncAnthropic(api_key=api_key)
        messages = self._build_openai_history(history, prompt)

        try:
            async with client.messages.stream(
                model=model_id,
                max_tokens=4096,
                messages=messages,  # type: ignore[arg-type]
            ) as stream:
                async for text_chunk in stream.text_stream:
                    yield text_chunk
        except Exception:
            response = await self._send_api(prompt, history, model, timeout=120)
            yield response.text

    def _build_prompt(self, prompt: str, history: list[Message] | None) -> str:
        if not history:
            return prompt
        history_text = self.format_history_as_text(history)
        return f"Previous conversation:\n{history_text}\n\nContinue: {prompt}"
