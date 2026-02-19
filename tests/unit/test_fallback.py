"""Tests for FallbackChain."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from uai.core.fallback import FallbackChain, AllProvidersFailedError
from uai.core.router import RoutingDecision
from uai.models.provider import BackendType, TaskCapability
from uai.providers.base import ProviderError, ProviderResponse, RateLimitError


def _make_decision(provider="gemini", alternatives=None):
    return RoutingDecision(
        provider=provider,
        model="flash",
        backend=BackendType.API,
        task_type=TaskCapability.GENERAL_CHAT,
        estimated_cost=0.0,
        reason="test",
        alternatives=alternatives or [],
    )


def _make_response(provider="gemini"):
    return ProviderResponse(
        text="answer",
        provider=provider,
        model="test-model",
        backend=BackendType.API,
        cost_usd=0.0,
        latency_ms=50.0,
    )


@pytest.mark.asyncio
async def test_success_on_first_try(quota_tracker):
    mock_prov = MagicMock()
    mock_prov.send = AsyncMock(return_value=_make_response("gemini"))
    mock_prov.supported_backends = [BackendType.API]

    chain = FallbackChain({"gemini": mock_prov}, quota_tracker)
    resp, tried = await chain.execute("hello", _make_decision("gemini"))
    assert resp.text == "answer"
    assert tried == ["gemini"]


@pytest.mark.asyncio
async def test_fallback_on_rate_limit(quota_tracker):
    gemini = MagicMock()
    gemini.send = AsyncMock(side_effect=RateLimitError("rate limited"))
    gemini.supported_backends = [BackendType.API]

    qwen = MagicMock()
    qwen.send = AsyncMock(return_value=_make_response("qwen"))
    qwen.supported_backends = [BackendType.API]

    chain = FallbackChain({"gemini": gemini, "qwen": qwen}, quota_tracker)
    resp, tried = await chain.execute(
        "hello", _make_decision("gemini", alternatives=["qwen"]),
        max_retries_per_provider=1,
    )
    assert resp.provider == "qwen"
    assert "gemini" in tried
    assert "qwen" in tried


@pytest.mark.asyncio
async def test_all_fail_raises(quota_tracker):
    p1 = MagicMock()
    p1.send = AsyncMock(side_effect=ProviderError("fail"))
    p1.supported_backends = [BackendType.API]

    chain = FallbackChain({"gemini": p1}, quota_tracker)
    with pytest.raises(AllProvidersFailedError):
        await chain.execute(
            "hello", _make_decision("gemini"),
            max_retries_per_provider=1, backoff=(0.01,),
        )
