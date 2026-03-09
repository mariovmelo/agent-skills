"""Tests for src/uai/cli/slash_commands.py"""
from __future__ import annotations
import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console

from uai.cli.slash_commands import (
    ChatContext,
    SlashCommand,
    SlashCommandRegistry,
    build_default_registry,
)


def _make_console() -> Console:
    buf = StringIO()
    return Console(file=buf, highlight=False, force_terminal=False), buf


def _make_ctx(console=None) -> ChatContext:
    if console is None:
        console, _ = _make_console()
    return ChatContext(
        session_name="test-session",
        executor=MagicMock(),
        session=MagicMock(),
        console=console,
        current_provider=None,
    )


@pytest.mark.asyncio
class TestSlashCommandRegistry:
    async def test_register_adds_command(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value="handled")
        cmd = SlashCommand("test", handler, "Test command")
        registry.register(cmd)
        assert "/test" in registry.all_names()

    async def test_register_adds_aliases(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value="handled")
        cmd = SlashCommand("foo", handler, "Foo", aliases=["f", "bar"])
        registry.register(cmd)
        # all_names() deduplicates by command identity — returns primary names only
        assert "/foo" in registry.all_names()

    async def test_all_names_no_duplicates(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value="handled")
        cmd = SlashCommand("foo", handler, "Foo", aliases=["f", "fo"])
        registry.register(cmd)
        names = registry.all_names()
        assert len(names) == len(set(names))

    async def test_dispatch_known_command(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value="handled")
        registry.register(SlashCommand("ping", handler, "Ping"))
        ctx = _make_ctx()
        result = await registry.dispatch("/ping", ctx)
        assert result == "handled"
        handler.assert_awaited_once()

    async def test_dispatch_with_args(self):
        registry = SlashCommandRegistry()
        received_args: list[str] = []

        async def _capture(args: str, ctx: ChatContext) -> str | None:
            received_args.append(args)
            return "handled"

        registry.register(SlashCommand("cmd", _capture, "Cmd"))
        ctx = _make_ctx()
        await registry.dispatch("/cmd hello world", ctx)
        assert received_args[0] == "hello world"

    async def test_dispatch_unknown_command_returns_handled(self):
        registry = SlashCommandRegistry()
        ctx = _make_ctx()
        result = await registry.dispatch("/nonexistent", ctx)
        # Unknown commands print a message and return "handled" (not None)
        assert result == "handled"

    async def test_dispatch_alias(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value="exit")
        registry.register(SlashCommand("exit", handler, "Exit", aliases=["quit", "q"]))
        ctx = _make_ctx()
        result = await registry.dispatch("/quit", ctx)
        assert result == "exit"

    async def test_get_by_name(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value=None)
        cmd = SlashCommand("foo", handler, "Foo")
        registry.register(cmd)
        found = registry.get("foo")
        assert found is cmd

    async def test_get_with_slash_prefix(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value=None)
        cmd = SlashCommand("bar", handler, "Bar")
        registry.register(cmd)
        found = registry.get("/bar")
        assert found is cmd

    async def test_print_help_outputs_something(self):
        registry = SlashCommandRegistry()
        handler = AsyncMock(return_value=None)
        registry.register(SlashCommand("foo", handler, "Foo command"))
        console, buf = _make_console()
        registry.print_help(console)
        output = buf.getvalue()
        assert len(output) > 0


@pytest.mark.asyncio
class TestBuildDefaultRegistry:
    async def test_creates_registry(self):
        registry = build_default_registry()
        assert isinstance(registry, SlashCommandRegistry)

    async def test_has_at_least_eight_commands(self):
        registry = build_default_registry()
        assert len(registry.all_names()) >= 8

    async def test_has_help_command(self):
        registry = build_default_registry()
        assert "/help" in registry.all_names()

    async def test_has_exit_command(self):
        registry = build_default_registry()
        assert "/exit" in registry.all_names()

    async def test_exit_via_quit_alias(self):
        registry = build_default_registry()
        console, _ = _make_console()
        ctx = _make_ctx(console)
        result = await registry.dispatch("/quit", ctx)
        assert result == "exit"

    async def test_provider_switch_returns_provider_colon_name(self):
        registry = build_default_registry()
        console, _ = _make_console()
        ctx = _make_ctx(console)
        result = await registry.dispatch("/provider gemini", ctx)
        assert result == "provider:gemini"

    async def test_provider_reset_returns_provider_colon_empty(self):
        registry = build_default_registry()
        console, _ = _make_console()
        ctx = _make_ctx(console)
        result = await registry.dispatch("/provider", ctx)
        assert result == "provider:"

    async def test_help_command_returns_handled(self):
        registry = build_default_registry()
        console, _ = _make_console()
        ctx = _make_ctx(console)
        result = await registry.dispatch("/help", ctx)
        assert result == "handled"


@pytest.mark.asyncio
class TestDefaultCommandHandlers:
    def _make_ctx_with_executor(self, console=None):
        """Create a ChatContext with a mock executor that has context methods."""
        if console is None:
            console, _ = _make_console()
        executor = MagicMock()
        executor.context = MagicMock()
        executor.context.clear_messages = MagicMock()
        executor.context.get_messages = MagicMock(return_value=[MagicMock(), MagicMock()])
        executor.context.list_sessions = MagicMock(return_value=[])
        executor.context.export_session = MagicMock(return_value="# Exported")
        executor.providers = {}
        session = MagicMock()
        return ChatContext(
            session_name="test-session",
            executor=executor,
            session=session,
            console=console,
            current_provider=None,
        )

    async def test_clear_handler_clears_messages(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        result = await registry.dispatch("/clear", ctx)
        assert result == "handled"
        ctx.executor.context.clear_messages.assert_called_once_with(ctx.session)

    async def test_clear_handler_prints_confirmation(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        await registry.dispatch("/clear", ctx)
        assert "cleared" in buf.getvalue().lower()

    async def test_history_handler_shows_message_count(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        result = await registry.dispatch("/history", ctx)
        assert result == "handled"
        assert "2" in buf.getvalue()  # 2 mock messages

    async def test_history_handler_shows_session_name(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        await registry.dispatch("/history", ctx)
        assert "test-session" in buf.getvalue()

    async def test_export_handler_writes_file(self, tmp_path):
        registry = build_default_registry()
        console, _ = _make_console()
        ctx = self._make_ctx_with_executor(console)
        outfile = str(tmp_path / "out.md")
        result = await registry.dispatch(f"/export {outfile}", ctx)
        assert result == "handled"
        import os
        assert os.path.exists(outfile)
        with open(outfile) as f:
            assert f.read() == "# Exported"

    async def test_export_handler_default_filename(self, tmp_path, monkeypatch):
        registry = build_default_registry()
        console, _ = _make_console()
        ctx = self._make_ctx_with_executor(console)
        monkeypatch.chdir(tmp_path)
        result = await registry.dispatch("/export", ctx)
        assert result == "handled"
        import os
        assert os.path.exists("test-session.md")

    async def test_status_handler_with_no_providers(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        ctx.executor.providers = {}
        result = await registry.dispatch("/status", ctx)
        assert result == "handled"
        assert "Provider status" in buf.getvalue()

    async def test_status_handler_shows_provider_status(self):
        from unittest.mock import AsyncMock as AM
        from uai.models.provider import ProviderStatus
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        mock_prov = MagicMock()
        mock_prov.health_check = AM(return_value=ProviderStatus.AVAILABLE)
        ctx.executor.providers = {"test-prov": mock_prov}
        result = await registry.dispatch("/status", ctx)
        assert result == "handled"
        assert "test-prov" in buf.getvalue()

    async def test_status_handler_unavailable_on_exception(self):
        from unittest.mock import AsyncMock as AM
        from uai.models.provider import ProviderStatus
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        mock_prov = MagicMock()
        mock_prov.health_check = AM(side_effect=RuntimeError("fail"))
        ctx.executor.providers = {"bad-prov": mock_prov}
        await registry.dispatch("/status", ctx)
        assert "bad-prov" in buf.getvalue()

    async def test_session_handler_shows_current_session(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        result = await registry.dispatch("/session", ctx)
        assert result == "handled"
        assert "test-session" in buf.getvalue()

    async def test_session_handler_lists_available_sessions(self):
        registry = build_default_registry()
        console, buf = _make_console()
        ctx = self._make_ctx_with_executor(console)
        s1 = MagicMock()
        s1.name = "session-a"
        s2 = MagicMock()
        s2.name = "test-session"
        ctx.executor.context.list_sessions.return_value = [s1, s2]
        await registry.dispatch("/session", ctx)
        assert "session-a" in buf.getvalue()
