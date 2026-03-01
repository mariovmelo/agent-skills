"""Gemini provider — Google Gemini via API (google-genai SDK) or CLI (gemini)."""
from __future__ import annotations
import asyncio
import time
from typing import Any

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import (
    AuthError, BaseProvider, ProviderError, ProviderResponse, RateLimitError,
)
from uai.utils.installer import get_cli_path


class GeminiProvider(BaseProvider):
    name = "gemini"
    display_name = "Gemini"
    is_free = True
    capabilities = [
        TaskCapability.ARCHITECTURE,
        TaskCapability.LONG_CONTEXT,
        TaskCapability.DATA_ANALYSIS,
        TaskCapability.CODE_REVIEW,
        TaskCapability.GENERAL_CHAT,
    ]
    supported_backends = [BackendType.CLI, BackendType.API]
    context_window_tokens = 1_000_000  # Gemini 1.5+ supports 1M tokens

    MODELS: dict[str, dict[str, Any]] = {
        # GA stable models as of 2026 — 2.0 and 1.x are retired or retiring June 2026.
        "flash":       {"id": "gemini-2.5-flash",      "cost_input": 0.0, "cost_output": 0.0},
        "pro":         {"id": "gemini-2.5-pro",         "cost_input": 0.0, "cost_output": 0.0},
        "flash-lite":  {"id": "gemini-2.5-flash-lite",  "cost_input": 0.0, "cost_output": 0.0},
    }
    DEFAULT_MODEL = "flash"

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
            return await self._send_cli(prompt, history, model, timeout, output_json)
        return await self._send_api(prompt, history, model, timeout, output_json)

    # ------------------------------------------------------------------
    async def _send_cli(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int,
        output_json: bool,
    ) -> ProviderResponse:
        model_id = self._resolve(model)
        full_prompt = self._build_prompt(prompt, history)

        cmd = [get_cli_path("gemini"), "-m", model_id, "-p", full_prompt]
        if output_json:
            cmd += ["--output-format", "json"]

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ProviderError(f"Gemini CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise ProviderError("Gemini CLI not found. Run: npm install -g @google/gemini-cli")

        latency = (time.monotonic() - t0) * 1000

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            err_lower = err.lower()
            # Use specific phrases — "rate" alone matches "generate" in stack traces.
            is_rate_limit = (
                "resource_exhausted" in err_lower
                or "rate limit" in err_lower
                or "quota exceeded" in err_lower
                or "429" in err_lower
            )
            if is_rate_limit:
                raise RateLimitError(f"Gemini rate limit: {err}")
            raise ProviderError(f"Gemini CLI error (exit {proc.returncode}): {err}")

        text = stdout.decode(errors="replace").strip()
        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.CLI,
            latency_ms=latency,
        )

    async def _send_api(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int,
        output_json: bool,
    ) -> ProviderResponse:
        api_key = self._auth.get_credential("gemini", "api_key")
        if not api_key:
            raise AuthError("Gemini API key not configured. Run: uai connect gemini")

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ProviderError("google-genai not installed. Run: pip install google-genai")

        model_id = self._resolve(model)
        client = genai.Client(api_key=api_key)

        # Build contents with history
        contents: list[Any] = []
        if history:
            for msg in history:
                role = "user" if msg.role.value == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))

        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=model_id,
                    contents=contents,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ProviderError(f"Gemini API timed out after {timeout}s")

        latency = (time.monotonic() - t0) * 1000
        text = response.text or ""
        tokens_in = getattr(response.usage_metadata, "prompt_token_count", None)
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", None)

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model_id,
            backend=BackendType.API,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            cost_usd=0.0,
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    async def health_check(self) -> ProviderStatus:
        from uai.utils.installer import is_cli_installed
        if is_cli_installed("gemini"):
            return ProviderStatus.AVAILABLE
        api_key = self._auth.get_credential("gemini", "api_key")
        if api_key:
            return ProviderStatus.AVAILABLE
        return ProviderStatus.NOT_CONFIGURED

    def is_configured(self) -> bool:
        from uai.utils.installer import is_cli_installed
        # Primary path: CLI installed (OAuth handled by the CLI itself on first use).
        # Do NOT require cli_authenticated here — the Gemini CLI manages its own auth state.
        if is_cli_installed("gemini"):
            return True
        # API fallback only: key explicitly set in env / config
        return bool(self._auth.get_credential("gemini", "api_key"))

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        return 0.0  # Gemini is free

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": k, **v} for k, v in self.MODELS.items()]

    # ------------------------------------------------------------------
    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens from Gemini. Uses CLI (preferred) or API based on preferred_backend."""
        # Respect preferred_backend — CLI is the default and needs no API key.
        if self.preferred_backend() == BackendType.CLI:
            # CLI path: blocks until full response arrives, then yields as one chunk.
            # Any ProviderError/TimeoutError raised here propagates to the caller,
            # which handles fallback to alternative providers.
            response = await self._send_cli(prompt, history, model, timeout=120, output_json=False)
            yield response.text
            return
        api_key = self._auth.get_credential("gemini", "api_key")
        if not api_key:
            # No API key configured — fall back to CLI
            response = await self._send_cli(prompt, history, model, timeout=120, output_json=False)
            yield response.text
            return

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        model_id = self._resolve(model)
        client = genai.Client(api_key=api_key)

        contents: list[Any] = []
        if history:
            for msg in history:
                role = "user" if msg.role.value == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))

        try:
            stream_iter = await asyncio.to_thread(
                lambda: list(client.models.generate_content_stream(
                    model=model_id, contents=contents
                ))
            )
            for chunk in stream_iter:
                if chunk.text:
                    yield chunk.text
        except Exception:
            # Fallback to non-streaming on error
            response = await self._send_api(prompt, history, model, timeout=120, output_json=False)
            yield response.text

    # ------------------------------------------------------------------
    def _resolve(self, alias: str | None) -> str:
        alias = alias or self._cfg.default_model or self.DEFAULT_MODEL
        return self.MODELS.get(alias, {}).get("id", alias)

    def _build_prompt(self, prompt: str, history: list[Message] | None) -> str:
        if not history:
            return prompt
        history_text = self.format_history_as_text(history)
        return f"{history_text}\nUser: {prompt}"
