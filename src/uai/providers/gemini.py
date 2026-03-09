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

        cmd = [get_cli_path("gemini"), "-m", model_id, "-p", full_prompt, "--approval-mode=yolo"]
        if output_json:
            cmd += ["--output-format", "json"]

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise ProviderError(f"Gemini CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise ProviderError("Gemini CLI not found. Run: npm install -g @google/gemini-cli")

        latency = (time.monotonic() - t0) * 1000

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            if self.is_rate_limit_error(err):
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
        
        # Test CLI first
        if is_cli_installed("gemini"):
            try:
                # Use a lightweight CLI command, e.g., asking for a short, simple prompt.
                # Adding --approval-mode=yolo to avoid interactive prompts.
                proc = await asyncio.create_subprocess_exec(
                    get_cli_path("gemini"), "-m", "gemini-2.5-flash", "-p", "Hi", "--approval-mode=yolo",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    return ProviderStatus.AVAILABLE
                # If CLI command fails, it might still be partially configured, so try API
            except Exception:
                pass  # Fallback to API check

        # If CLI is not available or failed, try API key with a lightweight call
        api_key = self._auth.get_credential("gemini", "api_key")
        if api_key:
            try:
                from google import genai
                # Use a lightweight API call, e.g., listing models, to verify connectivity and key.
                # No actual generation is performed, just metadata access.
                client = genai.Client(api_key=api_key)
                await asyncio.to_thread(client.models.list)
                return ProviderStatus.AVAILABLE
            except Exception:
                # API key might be invalid or network issue, so it's degraded
                return ProviderStatus.DEGRADED
        
        # Neither CLI nor API key is properly configured or working
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
    async def _stream_cli(
        self,
        prompt: str,
        history: list[Message] | None,
        model: str | None,
        timeout: int = 120,
    ):
        """Read gemini CLI stdout incrementally, yielding chunks as they arrive."""
        model_id = self._resolve(model)
        full_prompt = self._build_prompt(prompt, history)
        cmd = [get_cli_path("gemini"), "-m", model_id, "-p", full_prompt, "--approval-mode=yolo"]
        t0 = time.monotonic()
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
            raise ProviderError("Gemini CLI not found. Run: npm install -g @google/gemini-cli")

        stderr_task = asyncio.create_task(_drain_stderr(proc.stderr))  # type: ignore[arg-type]
        try:
            while True:
                remaining = timeout - (time.monotonic() - t0)
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    chunk = await asyncio.wait_for(
                        proc.stdout.read(512), timeout=remaining  # type: ignore[union-attr]
                    )
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                yield chunk.decode(errors="replace")
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

        elapsed = time.monotonic() - t0
        if proc.returncode is None or (elapsed >= timeout and proc.returncode != 0):
            raise ProviderError(f"Gemini CLI timed out after {timeout}s")

        if proc.returncode != 0:
            err = b"".join(stderr_chunks).decode(errors="replace").strip()
            if self.is_rate_limit_error(err):
                raise RateLimitError(f"Gemini rate limit: {err}")
            raise ProviderError(f"Gemini CLI error (exit {proc.returncode}): {err}")

    async def stream(
        self,
        prompt: str,
        history: list[Message] | None = None,
        model: str | None = None,
    ):
        """Stream tokens from Gemini. Uses CLI (preferred) or API based on preferred_backend."""
        if self.preferred_backend() == BackendType.CLI:
            async for chunk in self._stream_cli(prompt, history, model):
                yield chunk
            return
        api_key = self._auth.get_credential("gemini", "api_key")
        if not api_key:
            async for chunk in self._stream_cli(prompt, history, model):
                yield chunk
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
            # Use async streaming properly — iterate in thread but yield chunks incrementally
            import queue
            chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
            
            def _consume_stream() -> None:
                """Consume sync stream in background thread, push chunks to async queue."""
                try:
                    stream = client.models.generate_content_stream(
                        model=model_id, contents=contents
                    )
                    for chunk in stream:
                        if chunk.text:
                            # Schedule put on event loop
                            fut = asyncio.run_coroutine_threadsafe(
                                chunk_queue.put(chunk.text),
                                asyncio.get_running_loop()
                            )
                            # Wait for put to complete (with timeout to avoid deadlock)
                            try:
                                fut.result(timeout=5.0)
                            except Exception:
                                pass
                except Exception:
                    pass
                finally:
                    # Signal end of stream
                    try:
                        asyncio.run_coroutine_threadsafe(
                            chunk_queue.put(None),
                            asyncio.get_running_loop()
                        ).result(timeout=2.0)
                    except Exception:
                        pass
            
            # Start consuming in background thread
            stream_task = asyncio.create_task(asyncio.to_thread(_consume_stream))
            
            # Yield chunks as they arrive
            while True:
                chunk = await chunk_queue.get()
                if chunk is None:
                    break
                yield chunk
            
            # Wait for stream task to complete
            await stream_task
            
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
