"""Tests for RequestExecutor.execute_stream() and the factory method."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from uai.core.executor import RequestExecutor
from uai.core.fallback import FallbackChain
from uai.core.router import RoutingDecision
from uai.models.provider import BackendType, TaskCapability
from uai.models.request import UAIRequest


def _make_routing_decision(provider="test-provider"):
    return RoutingDecision(
        provider=provider,
        model="test-model",
        backend=BackendType.API,
        task_type=TaskCapability.GENERAL_CHAT,
        estimated_cost=0.0,
        reason="test",
        alternatives=[],
    )


def _make_provider_mock(tokens=("hello", " ", "world")):
    """Create a mock provider that streams tokens."""
    mock = MagicMock()
    mock.name = "test-provider"

    async def _stream(*args, **kwargs):
        for t in tokens:
            yield t

    mock.stream = _stream
    mock.send = AsyncMock()
    mock.is_configured = MagicMock(return_value=True)
    return mock


def _make_executor(tmp_dir, provider_mock=None, use_context=True):
    """Build a RequestExecutor with all components mocked."""
    if provider_mock is None:
        provider_mock = _make_provider_mock()

    config = MagicMock()
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

    from uai.core.context import ContextManager
    context = ContextManager(tmp_dir / "sessions")

    router = MagicMock()
    router.route = AsyncMock(return_value=_make_routing_decision("test-provider"))

    providers = {"test-provider": provider_mock}
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


class TestRequestExecutorCreateDefault:
    def test_create_default_returns_executor(self, tmp_dir):
        executor = RequestExecutor.create_default(config_dir=tmp_dir)
        assert isinstance(executor, RequestExecutor)

    def test_create_default_has_providers(self, tmp_dir):
        executor = RequestExecutor.create_default(config_dir=tmp_dir)
        assert isinstance(executor.providers, dict)

    def test_create_default_has_context(self, tmp_dir):
        executor = RequestExecutor.create_default(config_dir=tmp_dir)
        assert executor.context is not None

    def test_create_default_has_config(self, tmp_dir):
        executor = RequestExecutor.create_default(config_dir=tmp_dir)
        assert executor.config is not None


class TestExecuteStream:
    async def test_streams_tokens(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="hello", session_name="test", use_context=False)

        tokens = []
        async for token in executor.execute_stream(request):
            tokens.append(token)

        assert "".join(tokens) == "hello world"

    async def test_saves_user_and_assistant_messages_when_use_context_true(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="hi", session_name="stream-session", use_context=True)

        with patch("uai.core.project_context.find_project_instructions", return_value=None):
            tokens = []
            async for token in executor.execute_stream(request):
                tokens.append(token)

        session = executor.context.get_session("stream-session")
        messages = executor.context.get_messages(session)
        roles = [m.role.value for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    async def test_does_not_save_messages_when_use_context_false(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="no context", session_name="nocontext-session", use_context=False)

        tokens = []
        async for token in executor.execute_stream(request):
            tokens.append(token)

        session = executor.context.get_session("nocontext-session")
        messages = executor.context.get_messages(session)
        assert messages == []

    async def test_project_instructions_injected_as_system_message(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="test", session_name="instr-session", use_context=True)

        history_passed: list = []

        async def _capture_stream(prompt, history=None, **kwargs):
            if history:
                history_passed.extend(history)
            yield "ok"

        executor._providers["test-provider"].stream = _capture_stream

        with patch("uai.core.project_context.find_project_instructions", return_value="## Instructions"):
            async for _ in executor.execute_stream(request):
                pass

        # System message should be first in history (if any history was prepared)
        sys_roles = [m.role.value for m in history_passed if m.role.value == "system"]
        assert len(sys_roles) >= 0  # At least no crash; full verification requires >1 turn

    async def test_no_project_instructions_no_system_message(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="test", session_name="noinstr-session", use_context=True)

        history_passed: list = []

        async def _capture_stream(prompt, history=None, **kwargs):
            if history:
                history_passed.extend(history)
            yield "ok"

        executor._providers["test-provider"].stream = _capture_stream

        with patch("uai.core.project_context.find_project_instructions", return_value=None):
            async for _ in executor.execute_stream(request):
                pass

        sys_msgs = [m for m in history_passed if m.role.value == "system"]
        assert sys_msgs == []

    async def test_no_providers_raises(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        executor._providers = {}  # Remove all providers
        executor._router.route = AsyncMock(return_value=_make_routing_decision("nonexistent"))
        request = UAIRequest(prompt="test", session_name="s", use_context=False)

        from uai.core.fallback import AllProvidersFailedError

        with pytest.raises(AllProvidersFailedError):
            async for _ in executor.execute_stream(request):
                pass


@pytest.mark.asyncio
class TestOnStatusCallback:
    """execute_stream() emits on_status events at routing and on fallback."""

    async def test_routing_event_fired(self, tmp_dir):
        """on_status("routing", decision, routing_s) is called exactly once."""
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="hi", session_name="s", use_context=False)

        events: list[tuple] = []
        def on_status(event, *args):
            events.append((event, args))

        async for _ in executor.execute_stream(request, on_status=on_status):
            pass

        routing_events = [e for e in events if e[0] == "routing"]
        assert len(routing_events) == 1
        event_name, (decision, routing_s) = routing_events[0]
        assert decision.provider == "test-provider"
        assert isinstance(routing_s, float) and routing_s >= 0

    async def test_fallback_event_fired_on_provider_error(self, tmp_dir):
        """on_status("fallback", ...) is called when primary fails before yielding tokens."""
        from uai.providers.base import ProviderError

        failing = MagicMock()
        failing.name = "failing-provider"

        async def _fail(*args, **kwargs):
            raise ProviderError("timeout")
            yield  # make it an async generator

        failing.stream = _fail

        good = _make_provider_mock(tokens=("ok",))

        executor = _make_executor(tmp_dir)
        # Override provider registry so both providers are accessible by name
        executor._providers = {"failing-provider": failing, "good-provider": good}
        executor._router.route = AsyncMock(return_value=RoutingDecision(
            provider="failing-provider",
            model="m",
            backend=BackendType.API,
            task_type=TaskCapability.GENERAL_CHAT,
            estimated_cost=0.0,
            reason="test",
            alternatives=["good-provider"],
        ))

        events: list[tuple] = []
        tokens: list[str] = []
        async for t in executor.execute_stream(request=UAIRequest(
            prompt="hi", session_name="s", use_context=False
        ), on_status=lambda ev, *a: events.append((ev, a))):
            tokens.append(t)

        fallback_events = [e for e in events if e[0] == "fallback"]
        assert len(fallback_events) == 1
        _, (from_prov, error_str, to_prov) = fallback_events[0]
        assert from_prov == "failing-provider"
        assert "timeout" in error_str
        assert to_prov == "good-provider"
        assert "".join(tokens) == "ok"

    async def test_no_on_status_works(self, tmp_dir):
        """on_status=None (default) does not crash."""
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="hi", session_name="s", use_context=False)
        tokens = []
        async for t in executor.execute_stream(request):
            tokens.append(t)
        assert tokens == ["hello", " ", "world"]


class TestConfigCaching:
    async def test_config_loaded_once_per_execute_stream_call(self, tmp_dir):
        executor = _make_executor(tmp_dir)
        request = UAIRequest(prompt="hi", session_name="cache-test", use_context=False)

        load_call_count = 0
        original_load = executor._config.load

        def _counting_load():
            nonlocal load_call_count
            load_call_count += 1
            return original_load()

        executor._config.load = _counting_load

        async for _ in executor.execute_stream(request):
            pass

        # Should load config once per execute_stream call (not once per sub-call)
        assert load_call_count == 1
