"""Quota tracker — SQLite-backed usage monitoring across all providers."""
from __future__ import annotations
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path

from uai.models.quota import QuotaSnapshot, UsageRecord


class QuotaTracker:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._cooldowns: dict[str, float] = {}  # provider -> monotonic time until cooldown ends
        self._ensure_db()

    # ──────────────────────────────────────────────────────────────────
    def record(self, record: UsageRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO usage
                    (provider, model, backend, tokens_input, tokens_output,
                     cost_usd, latency_ms, success, error, timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.provider, record.model, record.backend,
                    record.tokens_input, record.tokens_output,
                    record.cost_usd, record.latency_ms,
                    1 if record.success else 0,
                    record.error,
                    record.timestamp.isoformat(),
                ),
            )

    def is_exhausted(self, provider: str, daily_limit: int | None = None) -> bool:
        """True if the provider has hit its daily request limit."""
        if daily_limit is None:
            return False
        today_count = self._count_today(provider)
        return today_count >= daily_limit

    def in_cooldown(self, provider: str) -> bool:
        until = self._cooldowns.get(provider, 0)
        return time.monotonic() < until

    def set_cooldown(self, provider: str, duration_seconds: float = 300.0) -> None:
        self._cooldowns[provider] = time.monotonic() + duration_seconds

    def get_success_rate(self, provider: str, window_hours: int = 24) -> float:
        """Return success rate 0.0–1.0 for the last N hours."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successes
                FROM usage
                WHERE provider = ?
                  AND timestamp >= datetime('now', ? || ' hours')
                """,
                (provider, -window_hours),
            ).fetchone()
        if not row or row[0] == 0:
            return 1.0  # No data → assume healthy
        return row[1] / row[0]

    def get_snapshot(self, provider: str, is_free: bool, daily_limit: int | None) -> QuotaSnapshot:
        with self._conn() as conn:
            today = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(tokens_input+tokens_output),0),
                       COALESCE(SUM(cost_usd),0)
                FROM usage
                WHERE provider=? AND date(timestamp)=date('now')
                """,
                (provider,),
            ).fetchone()
            month = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(tokens_input+tokens_output),0),
                       COALESCE(SUM(cost_usd),0)
                FROM usage
                WHERE provider=? AND strftime('%Y-%m', timestamp)=strftime('%Y-%m','now')
                """,
                (provider,),
            ).fetchone()

        cooldown_ts: datetime | None = None
        until = self._cooldowns.get(provider, 0)
        in_cd = time.monotonic() < until
        if in_cd:
            remaining = until - time.monotonic()
            cooldown_ts = datetime.utcnow()

        return QuotaSnapshot(
            provider=provider,
            is_free=is_free,
            requests_today=today[0] if today else 0,
            requests_month=month[0] if month else 0,
            tokens_today=today[1] if today else 0,
            tokens_month=month[1] if month else 0,
            cost_today_usd=today[2] if today else 0.0,
            cost_month_usd=month[2] if month else 0.0,
            daily_limit=daily_limit,
            success_rate_24h=self.get_success_rate(provider),
            in_cooldown=in_cd,
            cooldown_until=cooldown_ts,
        )

    def get_all_snapshots(self, provider_configs: dict) -> list[QuotaSnapshot]:
        snapshots = []
        for name, cfg in provider_configs.items():
            if not cfg.enabled:
                continue
            from uai.providers import get_provider_class
            try:
                prov_cls = get_provider_class(name)
                is_free = prov_cls.is_free
            except Exception:
                is_free = False
            snapshots.append(self.get_snapshot(name, is_free, cfg.daily_limit))
        return snapshots

    def total_cost_month(self) -> float:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM usage "
                "WHERE strftime('%Y-%m', timestamp)=strftime('%Y-%m','now')"
            ).fetchone()
        return row[0] if row else 0.0

    # ──────────────────────────────────────────────────────────────────
    def _count_today(self, provider: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM usage WHERE provider=? AND date(timestamp)=date('now')",
                (provider,),
            ).fetchone()
        return row[0] if row else 0

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider     TEXT NOT NULL,
                    model        TEXT DEFAULT '',
                    backend      TEXT DEFAULT 'api',
                    tokens_input INTEGER DEFAULT 0,
                    tokens_output INTEGER DEFAULT 0,
                    cost_usd     REAL DEFAULT 0.0,
                    latency_ms   REAL DEFAULT 0.0,
                    success      INTEGER DEFAULT 1,
                    error        TEXT,
                    timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_ts ON usage(provider, timestamp)")


import asyncio
import time

class RateLimiter:
    """Token bucket rate limiter for CLI requests."""
    
    def __init__(self, rate: float = 10.0, capacity: float = 20.0) -> None:
        """
        rate: tokens per second added to bucket
        capacity: maximum tokens in bucket
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens. Returns True if successful."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    async def wait_for_token(self, tokens: int = 1) -> None:
        """Wait until tokens are available."""
        while not await self.acquire(tokens):
            wait_time = (tokens - self._tokens) / self._rate
            await asyncio.sleep(min(wait_time, 1.0))
