"""Shared test fixtures for UAI test suite."""
from __future__ import annotations
import pytest
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console

from uai.core.auth import AuthManager
from uai.core.config import ConfigManager
from uai.core.context import ContextManager
from uai.core.quota import QuotaTracker
from uai.models.config import ProviderConfig


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def config_mgr(tmp_dir):
    mgr = ConfigManager(tmp_dir)
    mgr.initialize()
    return mgr


@pytest.fixture
def auth_mgr(tmp_dir):
    return AuthManager(tmp_dir)


@pytest.fixture
def quota_tracker(tmp_dir):
    return QuotaTracker(tmp_dir / "quota.db")


@pytest.fixture
def context_mgr(tmp_dir):
    return ContextManager(tmp_dir / "sessions")


@pytest.fixture
def free_provider_cfg():
    return ProviderConfig(enabled=True, preferred_backend="cli", priority=4)


@pytest.fixture
def paid_provider_cfg():
    return ProviderConfig(enabled=True, preferred_backend="api", priority=2)


@pytest.fixture
def mock_console():
    """Rich Console that writes to a StringIO buffer, for output assertions."""
    buf = StringIO()
    return Console(file=buf, highlight=False, markup=False), buf


@pytest.fixture
def tmp_project_dir(tmp_path):
    """A fresh temporary directory to simulate a project root."""
    proj = tmp_path / "project"
    proj.mkdir()
    return proj


@pytest.fixture
def mock_provider_fixture():
    """A mock provider as a pytest fixture (same as make_mock_provider())."""
    return make_mock_provider()


def make_mock_provider(name="gemini", is_free=True, response_text="test response"):
    """Create a mock provider that returns a canned response."""
    from uai.models.provider import BackendType, ProviderStatus, TaskCapability
    from uai.providers.base import ProviderResponse

    mock = MagicMock()
    mock.name = name
    mock.is_free = is_free
    mock.capabilities = [TaskCapability.GENERAL_CHAT]
    mock.supported_backends = [BackendType.API, BackendType.CLI]
    mock.context_window_tokens = 100_000

    mock.send = AsyncMock(return_value=ProviderResponse(
        text=response_text,
        provider=name,
        model=f"{name}-test",
        backend=BackendType.API,
        tokens_input=10,
        tokens_output=20,
        cost_usd=0.0,
        latency_ms=100.0,
    ))
    mock.health_check = AsyncMock(return_value=ProviderStatus.AVAILABLE)
    mock.is_configured = MagicMock(return_value=True)
    mock.estimate_cost = MagicMock(return_value=0.0)
    return mock
