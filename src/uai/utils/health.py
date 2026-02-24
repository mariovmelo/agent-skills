"""Provider health check utilities with caching."""
from __future__ import annotations
import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uai.providers.base import BaseProvider

from uai.models.provider import ProviderStatus

_CACHE_TTL = 60.0          # seconds
_COOLDOWN_DURATION = 300.0 # 5 minutes after a hard failure

_status_cache: dict[str, tuple[ProviderStatus, float]] = {}
_cooldown_until: dict[str, float] = {}


async def get_provider_status_with_age(
    provider: "BaseProvider",
) -> tuple[ProviderStatus, float | None]:
    """
    Return (status, age_seconds) where age_seconds is None if freshly checked.
    Useful for showing cache staleness in status displays.
    """
    now = time.monotonic()
    name = provider.name

    if name in _cooldown_until and now < _cooldown_until[name]:
        return ProviderStatus.COOLDOWN, None

    if name in _status_cache:
        status, ts = _status_cache[name]
        age = now - ts
        if age < _CACHE_TTL:
            return status, age

    status = await get_provider_status(provider)
    return status, None


async def get_provider_status(provider: "BaseProvider") -> ProviderStatus:
    """Return cached health status, refreshing if TTL expired."""
    now = time.monotonic()
    name = provider.name

    # Check cooldown first
    if name in _cooldown_until and now < _cooldown_until[name]:
        return ProviderStatus.COOLDOWN

    # Check cache
    if name in _status_cache:
        status, ts = _status_cache[name]
        if now - ts < _CACHE_TTL:
            return status

    # Actually ping the provider
    try:
        status = await asyncio.wait_for(provider.health_check(), timeout=10.0)
    except Exception:
        status = ProviderStatus.UNAVAILABLE

    _status_cache[name] = (status, now)

    # If hard failure, enter cooldown
    if status in (ProviderStatus.UNAVAILABLE, ProviderStatus.AUTH_ERROR):
        _cooldown_until[name] = now + _COOLDOWN_DURATION

    return status


def mark_cooldown(provider_name: str) -> None:
    """Manually put a provider in cooldown (e.g., after rate limit)."""
    _cooldown_until[provider_name] = time.monotonic() + _COOLDOWN_DURATION


def clear_cache(provider_name: str | None = None) -> None:
    if provider_name:
        _status_cache.pop(provider_name, None)
        _cooldown_until.pop(provider_name, None)
    else:
        _status_cache.clear()
        _cooldown_until.clear()
