"""Tests for QwenProvider — CLI streaming, timeouts, and fallback behavior.

Scenarios covered
-----------------
_stream_cli
  1. CLI hangs and never produces output → fast ProviderError (first-byte timeout)
  2. CLI not installed (FileNotFoundError) → ProviderError
  3. CLI exits with non-zero code → ProviderError
  4. CLI stderr matches rate-limit pattern → RateLimitError
  5. CLI succeeds and yields chunks in order
  6. CLI produces first chunk but hangs after → full-timeout ProviderError

stream()
  7. No OpenRouter key → delegates to _stream_cli
  8. OpenRouter key present → uses OpenRouter API (does not call CLI)
  9. openai not installed with API key → falls back to send()

_send_cli
  10. CLI times out → ProviderError
  11. CLI exits non-zero → ProviderError
  12. CLI succeeds → ProviderResponse with correct fields

Executor integration
  13. Timeout error triggers 60-second cooldown on provider
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import uai.providers.qwen as _qwen_mod
from uai.models.config import ProviderConfig
from uai.models.provider import BackendType
from uai.providers.base import ProviderError, ProviderResponse, RateLimitError
from uai.providers.qwen import QwenProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth(openrouter_key=None):
    auth = MagicMock()
    auth.get_credential = MagicMock(return_value=openrouter_key)
    return auth


def _make_provider(openrouter_key=None, preferred_backend="cli"):
    auth = _make_auth(openrouter_key)
    cfg = ProviderConfig(enabled=True, preferred_backend=preferred_backend)
    return QwenProvider(auth, cfg)


class _MockProc:
    """Simulates an asyncio subprocess with controllable stdout/stderr."""

    def __init__(
        self,
        stdout_chunks: list[bytes] | None = None,
        stderr_data: bytes = b"",
        returncode: int = 0,
        first_chunk_delay: float = 0.0,   # seconds before first chunk
        subsequent_delay: float = 0.0,    # seconds before subsequent chunks
    ):
        self._returncode_final = returncode
        self.returncode: int | None = None
        self._chunks = list(stdout_chunks or []) + [b""]  # EOF sentinel
        self._chunk_idx = 0
        self._first_chunk_delay = first_chunk_delay
        self._subsequent_delay = subsequent_delay
        self._stderr_data = stderr_data
        self._stderr_sent = False

        self.stdout = MagicMock()
        self.stderr = MagicMock()
        self.stdout.read = AsyncMock(side_effect=self._read_stdout)
        self.stderr.read = AsyncMock(side_effect=self._read_stderr)
        self.kill = MagicMock(side_effect=self._do_kill)
        self.wait = AsyncMock(side_effect=self._do_wait)

    async def _read_stdout(self, n: int = 32768) -> bytes:
        delay = self._first_chunk_delay if self._chunk_idx == 0 else self._subsequent_delay
        if delay > 0:
            await asyncio.sleep(delay)
        chunk = self._chunks[self._chunk_idx] if self._chunk_idx < len(self._chunks) else b""
        self._chunk_idx += 1
        if chunk == b"":
            # Simulate real process: when stdout closes the process has exited.
            if self.returncode is None:
                self.returncode = self._returncode_final
        return chunk

    async def _read_stderr(self, n: int = 4096) -> bytes:
        if not self._stderr_sent:
            self._stderr_sent = True
            return self._stderr_data
        return b""

    def _do_kill(self) -> None:
        self.returncode = -9

    async def _do_wait(self) -> int:
        if self.returncode is None:
            self.returncode = self._returncode_final
        return self.returncode


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _collect(gen):
    """Collect all chunks from an async generator into a string."""
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return "".join(chunks)


async def _collect_expect_error(gen):
    """Collect chunks until the generator raises; return (chunks, exception)."""
    chunks = []
    exc = None
    try:
        async for chunk in gen:
            chunks.append(chunk)
    except Exception as e:
        exc = e
    return "".join(chunks), exc


# ---------------------------------------------------------------------------
# 1-6: _stream_cli
# ---------------------------------------------------------------------------

class TestStreamCLI:
    def test_cli_hang_raises_fast_provider_error(self, monkeypatch):
        """If no output arrives within _FIRST_BYTE_TIMEOUT the error fires fast."""
        # Use a tiny first-byte timeout so the test runs in milliseconds
        monkeypatch.setattr(_qwen_mod, "_FIRST_BYTE_TIMEOUT", 0.05)

        provider = _make_provider()
        proc = _MockProc(first_chunk_delay=999.0)  # effectively never

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                return await _collect_expect_error(
                    provider._stream_cli("hello", None, timeout=30)
                )

        _text, err = _run(_run_test())
        assert _text == ""
        assert isinstance(err, ProviderError)
        assert "no output within" in str(err).lower()
        # Process must have been killed
        proc.kill.assert_called_once()

    def test_cli_not_found_raises_provider_error(self):
        """FileNotFoundError from exec → ProviderError with install hint."""
        provider = _make_provider()

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
                return await _collect_expect_error(
                    provider._stream_cli("hello", None, timeout=30)
                )

        _text, err = _run(_run_test())
        assert isinstance(err, ProviderError)
        assert "not found" in str(err).lower()

    def test_cli_nonzero_exit_raises_provider_error(self):
        """Exit code != 0 → ProviderError containing exit code."""
        provider = _make_provider()
        proc = _MockProc(
            stdout_chunks=[b"some output"],
            stderr_data=b"fatal: something went wrong",
            returncode=1,
        )

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                return await _collect_expect_error(
                    provider._stream_cli("hello", None, timeout=30)
                )

        _text, err = _run(_run_test())
        assert isinstance(err, ProviderError)
        assert "exit 1" in str(err) or "error" in str(err).lower()

    def test_cli_rate_limit_stderr_raises_rate_limit_error(self, monkeypatch):
        """When stderr contains a rate-limit signal, RateLimitError is raised."""
        provider = _make_provider()
        # Patch is_rate_limit_error to always return True for this test
        monkeypatch.setattr(provider, "is_rate_limit_error", lambda _: True)

        proc = _MockProc(
            stdout_chunks=[b""],
            stderr_data=b"429 rate limit exceeded",
            returncode=1,
        )

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                return await _collect_expect_error(
                    provider._stream_cli("hello", None, timeout=30)
                )

        _text, err = _run(_run_test())
        assert isinstance(err, RateLimitError)

    def test_cli_success_yields_chunks(self):
        """Happy path: chunks arrive and are yielded in order."""
        provider = _make_provider()
        proc = _MockProc(
            stdout_chunks=[b"Hello, ", b"world!"],
            returncode=0,
        )

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                return await _collect(provider._stream_cli("hello", None, timeout=30))

        result = _run(_run_test())
        assert result == "Hello, world!"

    def test_cli_full_timeout_raises_provider_error(self, monkeypatch):
        """After first byte, if CLI hangs past total timeout → ProviderError."""
        monkeypatch.setattr(_qwen_mod, "_FIRST_BYTE_TIMEOUT", 30)  # don't fire first-byte

        provider = _make_provider()
        # First chunk arrives immediately, second chunk hangs forever
        proc = _MockProc(
            stdout_chunks=[b"partial", b""],  # EOF only after delay
            subsequent_delay=999.0,
            returncode=0,
        )
        # Override second read to hang
        call_count = 0
        original_read = proc._read_stdout

        async def _controlled_read(n=32768):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"partial"
            await asyncio.sleep(999)
            return b""

        proc.stdout.read = AsyncMock(side_effect=_controlled_read)

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                return await _collect_expect_error(
                    provider._stream_cli("hello", None, timeout=0.1)  # very short total timeout
                )

        _text, err = _run(_run_test())
        assert isinstance(err, ProviderError)
        assert "timed out" in str(err).lower()


# ---------------------------------------------------------------------------
# 7-9: stream()
# ---------------------------------------------------------------------------

class TestStream:
    def test_no_api_key_uses_cli(self, monkeypatch):
        """Without OpenRouter key, stream() delegates to _stream_cli."""
        provider = _make_provider(openrouter_key=None)
        captured = []

        async def _fake_stream_cli(prompt, history, timeout=120):
            yield "chunk1"
            yield "chunk2"

        monkeypatch.setattr(provider, "_stream_cli", _fake_stream_cli)

        async def _run_test():
            async for token in provider.stream("hi"):
                captured.append(token)

        _run(_run_test())
        assert captured == ["chunk1", "chunk2"]

    def test_api_key_uses_openrouter(self, monkeypatch):
        """With OpenRouter key, stream() uses the API and does NOT touch CLI."""
        provider = _make_provider(openrouter_key="or-fake-key")

        async def _fake_stream_cli(*args, **kwargs):
            raise AssertionError("CLI should not be called when API key is set")
            yield  # make it a generator

        monkeypatch.setattr(provider, "_stream_cli", _fake_stream_cli)

        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "api token"

        async def _fake_sse():
            yield mock_chunk

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=_fake_sse())

        async def _run_test():
            tokens = []
            with patch.dict("sys.modules", {"openai": mock_openai}):
                async for token in provider.stream("hi"):
                    tokens.append(token)
            return tokens

        tokens = _run(_run_test())
        assert "api token" in tokens

    def test_openai_missing_with_api_key_falls_back_to_send(self, monkeypatch):
        """If openai is not installed but we have a key, falls back to send()."""
        provider = _make_provider(openrouter_key="or-fake-key")
        provider.send = AsyncMock(return_value=ProviderResponse(
            text="fallback text",
            provider="qwen",
            model="qwen3-coder",
            backend=BackendType.API,
        ))

        async def _run_test():
            tokens = []
            with patch.dict("sys.modules", {"openai": None}):
                async for token in provider.stream("hi"):
                    tokens.append(token)
            return tokens

        tokens = _run(_run_test())
        assert "".join(tokens) == "fallback text"
        provider.send.assert_awaited_once()


# ---------------------------------------------------------------------------
# 10-12: _send_cli
# ---------------------------------------------------------------------------

class TestSendCLI:
    def test_timeout_raises_provider_error(self):
        """_send_cli with a very short timeout raises ProviderError."""
        provider = _make_provider()
        proc = _MockProc(first_chunk_delay=999.0, returncode=0)

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                return await provider._send_cli("hello", None, timeout=0.05)

        with pytest.raises(ProviderError, match="timed out"):
            _run(_run_test())

    def test_nonzero_exit_raises_provider_error(self):
        """Non-zero exit from _send_cli → ProviderError."""
        provider = _make_provider()

        async def _fake_exec(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 2

            async def _communicate():
                return b"", b"something crashed"

            proc.communicate = AsyncMock(side_effect=_communicate)
            proc.stdout = MagicMock()

            async def _wait_for_read(*args, **kwargs):
                return b""

            with patch("asyncio.wait_for", side_effect=_wait_for_read):
                pass

            # Use a simple mock that returns immediately
            proc2 = _MockProc(stdout_chunks=[b""], stderr_data=b"crash", returncode=2)
            return proc2

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", new=_fake_exec):
                return await provider._send_cli("hello", None, timeout=5)

        with pytest.raises(ProviderError):
            _run(_run_test())

    def test_success_returns_provider_response(self):
        """_send_cli success → ProviderResponse with correct fields."""
        provider = _make_provider()

        async def _fake_exec(*args, stdin, stdout, stderr):
            proc = MagicMock()
            proc.returncode = 0

            async def _read(*a, **kw):
                return b"The answer is 42"

            proc.stdout = MagicMock()
            proc.stdout.read = AsyncMock(side_effect=_read)

            async def _drain_stderr(s):
                return b""

            proc.stderr = MagicMock()
            proc.stderr.read = AsyncMock(return_value=b"")

            async def _wait():
                return 0

            proc.wait = AsyncMock(side_effect=_wait)
            return proc

        async def _run_test():
            with patch("asyncio.create_subprocess_exec", new=_fake_exec):
                return await provider._send_cli("hello", None, timeout=10)

        resp = _run(_run_test())
        assert isinstance(resp, ProviderResponse)
        assert resp.text == "The answer is 42"
        assert resp.provider == "qwen"
        assert resp.backend == BackendType.CLI
        assert resp.cost_usd == 0.0


# ---------------------------------------------------------------------------
# 13: Executor cooldown integration
# ---------------------------------------------------------------------------

class TestExecutorCooldown:
    def test_timeout_sets_60s_cooldown(self):
        """After a 'timed out' ProviderError the quota tracker marks a 60s cooldown."""
        from uai.core.fallback import FallbackChain
        from uai.core.quota import QuotaTracker
        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmp:
            quota = QuotaTracker(pathlib.Path(tmp) / "q.db")

            # Simulate what execute_stream does when qwen times out
            from uai.providers.base import ProviderError as PE
            err = PE("Qwen CLI produced no output within 15s")

            # Check the condition used in executor.py
            assert "no output within" in str(err).lower()

            # Apply the cooldown
            if "timed out" in str(err).lower() or "no output within" in str(err).lower():
                quota.set_cooldown("qwen", 60)

            assert quota.in_cooldown("qwen"), "qwen should be in cooldown after timeout"

    def test_regular_provider_error_no_cooldown(self):
        """Non-timeout ProviderError should NOT trigger cooldown."""
        from uai.core.quota import QuotaTracker
        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmp:
            quota = QuotaTracker(pathlib.Path(tmp) / "q.db")

            err = ProviderError("Qwen CLI error (exit 1): some other problem")

            if "timed out" in str(err).lower() or "no output within" in str(err).lower():
                quota.set_cooldown("qwen", 60)

            assert not quota.in_cooldown("qwen"), "non-timeout error should not set cooldown"

    def test_cooldown_expires_and_provider_is_available_again(self):
        """After cooldown duration passes, in_cooldown() returns False."""
        from uai.core.quota import QuotaTracker
        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmp:
            quota = QuotaTracker(pathlib.Path(tmp) / "q.db")
            quota.set_cooldown("qwen", 0.0)  # 0-second cooldown — already expired

            # Allow a tiny moment for the clock to advance
            time.sleep(0.01)
            assert not quota.in_cooldown("qwen")


# ---------------------------------------------------------------------------
# 14: First-byte timeout constant is respected
# ---------------------------------------------------------------------------

class TestFirstByteTimeoutConstant:
    def test_default_value(self):
        assert _qwen_mod._FIRST_BYTE_TIMEOUT == 15

    def test_monkeypatch_is_effective(self, monkeypatch):
        monkeypatch.setattr(_qwen_mod, "_FIRST_BYTE_TIMEOUT", 99)
        assert _qwen_mod._FIRST_BYTE_TIMEOUT == 99
