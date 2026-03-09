"""Request and response models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from uai.models.provider import BackendType, TaskCapability


# Alias for external use
TaskType = TaskCapability


@dataclass
class UAIRequest:
    prompt: str
    session_name: str = "default"
    provider: str | None = None          # None = auto-route
    model: str | None = None
    backend: BackendType | None = None
    task_type: TaskCapability | None = None
    free_only: bool = False
    use_context: bool = True             # Inject session history
    output_json: bool = False
    timeout: int = 120
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UAIResponse:
    text: str
    provider: str
    model: str
    backend: BackendType
    session_name: str
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float | None = None
    latency_ms: float = 0.0
    fallback_used: bool = False          # True if primary provider failed
    providers_tried: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: dict[str, Any] | None = None
