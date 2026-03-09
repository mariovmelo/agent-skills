"""Exponential backoff retry decorator."""
from __future__ import annotations
import asyncio
import functools
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def async_retry(
    max_attempts: int = 3,
    backoff_seconds: tuple[float, ...] = (5.0, 15.0, 45.0),
    reraise_on: tuple[type[Exception], ...] = (),
) -> Callable[[F], F]:
    """Decorator: retry an async function with exponential backoff."""
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except reraise_on:
                    raise
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        wait = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
                        await asyncio.sleep(wait)
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
