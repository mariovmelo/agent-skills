"""Context and session models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    SUMMARY = "summary"   # Compressed checkpoint of older turns


@dataclass
class Message:
    id: int
    role: MessageRole
    content: str
    provider: str | None = None    # Which provider generated this (for assistant msgs)
    model: str | None = None
    tokens: int | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Session:
    name: str
    db_path: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)
    total_messages: int = 0
    total_tokens: int = 0


@dataclass
class SessionInfo:
    """Lightweight session info for listing."""
    name: str
    created_at: datetime
    last_active: datetime
    total_messages: int
    total_tokens: int
    size_bytes: int
