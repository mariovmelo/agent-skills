"""Quota and usage tracking models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class UsageRecord:
    provider: str
    model: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    backend: str = "api"
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class QuotaSnapshot:
    provider: str
    is_free: bool
    requests_today: int
    requests_month: int
    tokens_today: int
    tokens_month: int
    cost_today_usd: float
    cost_month_usd: float
    daily_limit: int | None      # None = unlimited
    success_rate_24h: float      # 0.0 - 1.0
    in_cooldown: bool = False
    cooldown_until: datetime | None = None
