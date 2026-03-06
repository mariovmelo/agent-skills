"""Qwen provider — qwen-code CLI (github.com/QwenLM/qwen-code) + OpenRouter API."""
from __future__ import annotations
import asyncio
import time
from typing import Any

# How long to wait for the first byte from the CLI before giving up.
# If the CLI hasn't produced any output in this window it is almost certainly
# hanging (OAuth expired, network issue, etc.) and we should fail fast so the
# fallback chain can try the next provider without a 120-second wait.
_FIRST_BYTE_TIMEOUT = 15  # seconds

from uai.models.context import Message
from uai.models.provider import BackendType, ProviderStatus, TaskCapability
from uai.providers.base import (
    AuthError, BaseProvider, ProviderError, ProviderResponse, RateLimitError,
)
from uai.utils.installer import get_cli_path


class QwenProvider(BaseProvider):
    name = "qwen"
    display_name = "Qwen Code"
    is_free = True
    capabilities = [
        TaskCapability.CODE_REVIEW,
        TaskCapability.CODE_GENERATION,
        TaskCapability.BATCH_PROCESSING,
        TaskCapability.DEBUGGING,
        TaskCapability.GENERAL_CHAT,
    ]
    supported_backends = [BackendType.CLI, BackendType.API]
    context_window_tokens = 128_000

    # qwen-code uses its own OAuth; for API we go via OpenRouter
    OPENROUTER_BASE = "https://openrouter.ai/api/v1"
    MODELS: dict[str, dict[str, Any]] = {
        "coder":      {"id": "qwen/qwen3-coder:free",   "cost_input": 0.0, "cost_output": 0.0},
        "coder-plus": {"id": "qwen/qwen-plus:free",     "cost_input": 0.0, "cost_output": 0.0},
    }
    DEFAULT_MODEL = "coder"
    # qwen-code OAuth gives 1000 free req/day
    DAILY_LIMIT = 1000

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
            return await self._send_cli(prompt, history, timeout)
        return await self._send_api(prompt, history, model, timeout)

    # ------------------------------------------------------------------
    async def _send_cli(
        self,
        prompt: str,
        history: list[Message] | None,
        timeout: int,
    ) -> ProviderResponse:
        """Use qwen-code headless mode: qwen -p "prompt"."""
        full_prompt = self._build_prompt(prompt, history)
        cmd = [get_cli_path("qwen"), "-p", full_prompt, "-y"]

        from uai.utils.memmon import snapshot, log_delta
        _m0 = snapshot("qwen_cli_before")
        t0 = time.monotonic()
        stderr_chunks: list[bytes] = []

        async def _drain_stderr(stream: asyncio.StreamReader) -> None:
            """Continuously reads stderr into stderr_chunks."""
            try:
                while True:
                    chunk = await stream.read(4096)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
            except Exception:
                pass

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stderr_task = asyncio.create_task(_drain_stderr(proc.stderr))  # type: ignore[arg-type]
            try:
                stdout = await asyncio.wait_for(proc.stdout.read(), timeout=timeout)  # type: ignore[union-attr]
                stderr_task.cancel()
                await proc.wait()
                stderr = b"".join(stderr_chunks)
            except asyncio.TimeoutError:
                stderr_task.cancel()
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except Exception:
                    pass
                partial_stderr = b"".join(stderr_chunks)
                hint = ""
                if partial_stderr:
                    decoded = partial_stderr.decode(errors="replace").strip()
                    if decoded:
                        hint = f" | stderr: {decoded[:300]}"
                raise ProviderError(f"Qwen CLI timed out after {timeout}s{hint}")
        except ProviderError:
            raise
        except FileNotFoundError:
            raise ProviderError(
                "Qwen CLI not found. Install: npm install -g @qwen/qwen-code  "
                "(see https://github.com/QwenLM/qwen-code)"
            )

        latency = (time.monotonic() - t0) * 1000
        log_delta(_m0, snapshot("qwen_cli_after"), "qwen_cli")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            if self.is_rate_limit_error(err):
                raise RateLimitError(f"Qwen rate limit: {err}")
            raise ProviderError(f"Qwen CLI error (exit {proc.returncode}): {err}")

        text = stdout.decode(errors="replace").strip()
        return ProviderResponse(
            text=text,
            provider=self.name,
            model="qwen3-coder",
            backend=BackendType.CLI,
            cost_usd=0.0,
            latency_ms=latency,
        )

    async def _send_api(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int,
    ) -> ProviderResponse:
        """Fallback: OpenRouter API (free tier)."""
        api_key = self._auth.get_credential("qwen", "openrouter_key")
        if not api_key:
            raise AuthError(
                "OpenRouter API key not configured for Qwen. "
                "Run: uai connect qwen  or install qwen-code for OAuth."
            )

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ProviderError("openai not installed. Run: pip install openai")

        model_id = self._resolve(model)
        client = AsyncOpenAI(base_url=self.OPENROUTER_BASE, api_key=api_key)

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
            raise ProviderError(f"Qwen/OpenRouter API timed out after {timeout}s")

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
    async def _stream_cli(
        self,
        prompt: str,
        history: list[Message] | None,
        timeout: int = 120,
    ):
        """Read qwen CLI stdout incrementally, yielding chunks as they arrive."""
        full_prompt = self._build_prompt(prompt, history)
        cmd = [get_cli_path("qwen"), "-p", full_prompt, "-y"]
        stderr_chunks: list[bytes] = []

        async def _drain_stderr(s: asyncio.StreamReader) -> None:
            try:
                while chunk := await s.read(4096):
                    stderr_chunks.append(chunk)
            except Exception:
                pass

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ProviderError("Qwen CLI not found. Install: npm install -g @qwen-code/qwen-code")

        stderr_task = asyncio.create_task(_drain_stderr(proc.stderr))  # type: ignore[arg-type]
        timed_out = False
        first_byte_timeout_hit = False
        try:
            async with asyncio.timeout(timeout):
                first_chunk = True
                while True:
                    if first_chunk:
                        # Fail fast: if no output arrives within _FIRST_BYTE_TIMEOUT
                        # the CLI is hanging (auth expired, network stall, etc.)
                        try:
                            chunk = await asyncio.wait_for(
                                proc.stdout.read(32768),  # type: ignore[union-attr]
                                timeout=_FIRST_BYTE_TIMEOUT,
                            )
                        except (TimeoutError, asyncio.TimeoutError):
                            first_byte_timeout_hit = True
                            break
                        first_chunk = False
                    else:
                        chunk = await proc.stdout.read(32768)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    yield chunk.decode(errors="replace")
        except TimeoutError:
            timed_out = True
        finally:
            stderr_task.cancel()
            if proc.returncode is None:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except Exception:
                    pass
            else:
                await proc.wait()

        if first_byte_timeout_hit:
            partial_stderr = b"".join(stderr_chunks)
            hint = ""
            if partial_stderr:
                decoded = partial_stderr.decode(errors="replace").strip()
                if decoded:
                    hint = f" | stderr: {decoded[:300]}"
            raise ProviderError(
                f"Qwen CLI produced no output within {_FIRST_BYTE_TIMEOUT}s{hint}"
            )

        if timed_out or proc.returncode is None:
            partial_stderr = b"".join(stderr_chunks)
            hint = ""
            if partial_stderr:
                decoded = partial_stderr.decode(errors="replace").strip()
                if decoded:
                    hint = f" | stderr: {decoded[:300]}"
            raise ProviderError(f"Qwen CLI timed out after {timeout}s{hint}")

        if proc.returncode != 0:
            err = b"".join(stderr_chunks).decode(errors="replace").strip()
            if self.is_rate_limit_error(err):
                raise RateLimitError(f"Qwen rate limit: {err}")
            raise ProviderError(f"Qwen CLI error (exit {proc.returncode}): {err}")

    # ------------------------------------------------------------------
    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens via OpenRouter API, or incrementally from CLI subprocess."""
        api_key = self._auth.get_credential("qwen", "openrouter_key")
        if not api_key:
            async for chunk in self._stream_cli(prompt, history):
                yield chunk
            return

        try:
            from openai import AsyncOpenAI
        except ImportError:
            response = await self.send(prompt, history=history, model=model)
            yield response.text
            return

        model_id = self._resolve(model)
        client = AsyncOpenAI(base_url=self.OPENROUTER_BASE, api_key=api_key)

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
        from uai.utils.installer import is_cli_installed
        
        # Test CLI first if installed
        if is_cli_installed("qwen"):
            try:
                # Use a lightweight CLI command to check functionality
                proc = await asyncio.create_subprocess_exec(
                    get_cli_path("qwen"), "-p", "Hi", "-y",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    return ProviderStatus.AVAILABLE
            except Exception:
                pass # Fallback to API check

        # If CLI is not available or failed, try OpenRouter API key with a lightweight call
        api_key = self._auth.get_credential("qwen", "openrouter_key")
        if api_key:
            try:
                from openai import AsyncOpenAI
                # Use a lightweight API call, e.g., a simple chat completion, to verify connectivity and key.
                client = AsyncOpenAI(base_url=self.OPENROUTER_BASE, api_key=api_key)
                await asyncio.wait_for(
                    client.chat.completions.create(
                        model="qwen/qwen3-coder",
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=1
                    ),
                    timeout=5
                )
                return ProviderStatus.AVAILABLE
            except Exception:
                return ProviderStatus.DEGRADED
        
        return ProviderStatus.NOT_CONFIGURED

    def is_configured(self) -> bool:
        from uai.utils.installer import is_cli_installed
        # CLI path: binary must exist AND OAuth must have been completed
        if is_cli_installed("qwen") and getattr(self._cfg, "cli_authenticated", False):
            return True
        # API fallback: OpenRouter key set manually in env / config
        return bool(self._auth.get_credential("qwen", "openrouter_key"))

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str | None = None) -> float:
        return 0.0

    def get_models(self) -> list[dict[str, Any]]:
        return [{"alias": k, **v} for k, v in self.MODELS.items()]

    # ------------------------------------------------------------------
    def _resolve(self, alias: str | None) -> str:
        alias = alias or self._cfg.default_model or self.DEFAULT_MODEL
        return self.MODELS.get(alias, {}).get("id", alias)

    def _build_prompt(self, prompt: str, history: list[Message] | None) -> str:
        if not history:
            return prompt
        history_text = self.format_history_as_text(history)
        return f"{history_text}\nUser: {prompt}"
