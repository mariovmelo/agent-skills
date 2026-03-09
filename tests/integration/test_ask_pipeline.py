"""Integration tests for the `uai ask` pipeline.

All external calls are mocked. Tests verify the full flow from
`_ask()` through execute_stream() through context save.
"""
from __future__ import annotations
import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console

from uai.cli.commands.ask import _ask
from uai.core.executor import RequestExecutor
from uai.core.router import RoutingDecision
from uai.models.provider import BackendType, TaskCapability


def _make_routing_decision(provider="test"):
    return RoutingDecision(
        provider=provider,
        model="test-model",
        backend=BackendType.API,
        task_type=TaskCapability.GENERAL_CHAT,
        estimated_cost=0.0,
        reason="test",
        alternatives=[],
    )


def _make_streaming_provider(tokens=("Hello", " world", "!")):
    """Make a provider whose stream() yields the given tokens."""
    mock = MagicMock()
    mock.name = "test"

    async def _stream(*args, **kwargs):
        for t in tokens:
            yield t

    mock.stream = _stream
    return mock


def _make_mock_executor(tmp_path, tokens=("Hello", " world", "!")):
    """Build a fully mocked RequestExecutor."""
    from uai.core.context import ContextManager
    from uai.core.fallback import FallbackChain

    provider_mock = _make_streaming_provider(tokens)

    config = MagicMock()
    config.config_dir = tmp_path
    config.load = MagicMock(return_value=MagicMock(
        defaults=MagicMock(
            session="default",
            cost_mode="free_only",
            context_strategy="auto",
            context_window_turns=20,
        ),
        context=MagicMock(keep_recent_turns=10, max_history_tokens=50_000),
    ))

    auth = MagicMock()
    quota = MagicMock()
    context = ContextManager(tmp_path / "sessions")
    router = MagicMock()
    router.route = AsyncMock(return_value=_make_routing_decision("test"))
    providers = {"test": provider_mock}
    fallback = FallbackChain(providers, quota=None)

    return RequestExecutor(
        config=config,
        auth=auth,
        quota=quota,
        context=context,
        router=router,
        fallback=fallback,
        providers=providers,
    )


class TestAskPipeline:
    async def test_ask_completes_without_error(self, tmp_path):
        executor = _make_mock_executor(tmp_path)

        with patch("uai.core.executor.RequestExecutor.create_default", return_value=executor):
            with patch("uai.cli.commands.ask.console", Console(file=StringIO())):
                with patch("uai.core.project_context.find_project_instructions", return_value=None):
                    await _ask(
                        prompt="say hello",
                        provider=None,
                        model=None,
                        session="integration-test",
                        free=False,
                        no_context=True,
                        raw=True,
                        verbose=False,
                    )

    async def test_ask_raw_mode_outputs_tokens(self, tmp_path, capsys):
        executor = _make_mock_executor(tmp_path, tokens=("test ", "output"))

        with patch("uai.core.executor.RequestExecutor.create_default", return_value=executor):
            with patch("uai.core.project_context.find_project_instructions", return_value=None):
                await _ask(
                    prompt="hello",
                    provider=None,
                    model=None,
                    session="raw-test",
                    free=False,
                    no_context=True,
                    raw=True,
                    verbose=False,
                )

        captured = capsys.readouterr()
        assert "test " in captured.out or "output" in captured.out

    async def test_ask_saves_messages_to_session(self, tmp_path):
        executor = _make_mock_executor(tmp_path, tokens=("response text",))

        with patch("uai.core.executor.RequestExecutor.create_default", return_value=executor):
            with patch("uai.cli.commands.ask.console", Console(file=StringIO())):
                with patch("uai.core.project_context.find_project_instructions", return_value=None):
                    await _ask(
                        prompt="hi there",
                        provider=None,
                        model=None,
                        session="save-test",
                        free=False,
                        no_context=False,  # context ON → messages saved
                        raw=True,
                        verbose=False,
                    )

        session = executor.context.get_session("save-test")
        messages = executor.context.get_messages(session)
        roles = [m.role.value for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    async def test_ask_handles_provider_error_gracefully(self, tmp_path):
        """_ask should handle errors without crashing with an unhandled exception."""
        from uai.core.errors import NoProviderAvailableError

        executor = _make_mock_executor(tmp_path)
        executor._providers = {}  # No providers → will raise

        executor._router.route = AsyncMock(return_value=_make_routing_decision("nonexistent"))

        import typer

        with patch("uai.core.executor.RequestExecutor.create_default", return_value=executor):
            with patch("uai.cli.commands.ask.console", Console(file=StringIO())):
                with patch("uai.core.project_context.find_project_instructions", return_value=None):
                    with pytest.raises(typer.Exit):
                        await _ask(
                            prompt="test",
                            provider=None,
                            model=None,
                            session="error-test",
                            free=False,
                            no_context=True,
                            raw=True,
                            verbose=False,
                        )
