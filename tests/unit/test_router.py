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


@pytest.mark.asyncio
async def test_classification_cache_hit_miss():
    from uai.core.router import ClassificationCache, SmartClassification
    
    cache = ClassificationCache(max_size=10, ttl_seconds=60)
    
    # Miss inicial
    assert cache.get("prompt1") is None
    
    # Set e get
    classification = SmartClassification(task_type=TaskCapability.DEBUGGING)
    cache.set("prompt1", classification)
    assert cache.get("prompt1") == classification
    
    # Hit
    assert cache.get("prompt1") == classification

@pytest.mark.asyncio
async def test_classification_cache_ttl():
    from uai.core.router import ClassificationCache, SmartClassification
    
    cache = ClassificationCache(max_size=10, ttl_seconds=1)  # 1 segundo
    classification = SmartClassification(task_type=TaskCapability.DEBUGGING)
    cache.set("prompt_ttl", classification)
    
    # Assert before expiration
    assert cache.get("prompt_ttl") == classification
    
    # Wait for expiration
    import asyncio
    await asyncio.sleep(1.1)
    
    # Assert after expiration
    assert cache.get("prompt_ttl") is None

@pytest.mark.asyncio
async def test_classification_cache_lru_eviction():
    from uai.core.router import ClassificationCache, SmartClassification
    
    cache = ClassificationCache(max_size=3, ttl_seconds=300)
    
    # Fill cache to its max size
    for i in range(3):
        cache.set(f"prompt{i}", SmartClassification(task_type=TaskCapability.DEBUGGING))
    
    # Access prompt0 to make it MRU
    assert cache.get("prompt0") is not None
    
    # Add a new item, which should evict the LRU item (prompt1)
    cache.set("prompt_new", SmartClassification(task_type=TaskCapability.DEBUGGING))
    
    # prompt1 should be evicted
    assert cache.get("prompt1") is None
    assert cache.get("prompt0") is not None # prompt0 was accessed, so not evicted
    assert cache.get("prompt2") is not None # prompt2 was last added before prompt_new
    assert cache.get("prompt_new") is not None
