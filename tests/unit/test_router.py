"""Tests for RouterEngine."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from uai.models.provider import TaskCapability


@pytest.mark.asyncio
async def test_route_free_only_skips_paid(config_mgr, auth_mgr, quota_tracker):
    from uai.core.router import RouterEngine
    from uai.models.provider import ProviderStatus

    router = RouterEngine(config_mgr, auth_mgr, quota_tracker)

    with patch("uai.core.router.get_provider_class") as mock_get:
        # Mock: gemini is free, claude is paid
        gemini_cls = MagicMock()
        gemini_cls.is_free = True
        gemini_cls.capabilities = [TaskCapability.GENERAL_CHAT]
        gemini_cls.supported_backends = [MagicMock(value="api")]
        gemini_cls.context_window_tokens = 1_000_000

        claude_cls = MagicMock()
        claude_cls.is_free = False
        claude_cls.capabilities = [TaskCapability.GENERAL_CHAT]
        claude_cls.supported_backends = [MagicMock(value="api")]
        claude_cls.context_window_tokens = 200_000

        def side_effect(name):
            if name == "gemini":
                return gemini_cls
            if name == "claude":
                return claude_cls
            raise ValueError(f"Unknown: {name}")

        mock_get.side_effect = side_effect

        decision = await router.route("hello", free_only=True)
        assert decision.provider == "gemini"


def test_classify_debugging():
    from uai.core.router import RouterEngine
    router = RouterEngine.__new__(RouterEngine)
    assert router._classify("fix the bug in auth.py") == TaskCapability.DEBUGGING
    assert router._classify("debug this error") == TaskCapability.DEBUGGING


def test_classify_architecture():
    from uai.core.router import RouterEngine
    router = RouterEngine.__new__(RouterEngine)
    assert router._classify("design the architecture") == TaskCapability.ARCHITECTURE
    assert router._classify("apply SOLID principles") == TaskCapability.ARCHITECTURE


def test_classify_code_review():
    from uai.core.router import RouterEngine
    router = RouterEngine.__new__(RouterEngine)
    assert router._classify("review this code") == TaskCapability.CODE_REVIEW


def test_classify_general_chat():
    from uai.core.router import RouterEngine
    router = RouterEngine.__new__(RouterEngine)
    assert router._classify("what is dependency injection?") == TaskCapability.GENERAL_CHAT
