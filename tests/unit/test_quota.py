"""Tests for QuotaTracker."""
from __future__ import annotations
import pytest
from datetime import datetime
from uai.models.quota import UsageRecord


def test_record_and_count(quota_tracker):
    quota_tracker.record(UsageRecord(provider="gemini", success=True))
    quota_tracker.record(UsageRecord(provider="gemini", success=True))
    snap = quota_tracker.get_snapshot("gemini", is_free=True, daily_limit=None)
    assert snap.requests_today >= 2


def test_not_exhausted_without_limit(quota_tracker):
    assert not quota_tracker.is_exhausted("gemini", daily_limit=None)


def test_exhausted_when_at_limit(quota_tracker):
    for _ in range(5):
        quota_tracker.record(UsageRecord(provider="qwen", success=True))
    assert quota_tracker.is_exhausted("qwen", daily_limit=5)
    assert not quota_tracker.is_exhausted("qwen", daily_limit=100)


def test_cooldown(quota_tracker):
    assert not quota_tracker.in_cooldown("gemini")
    quota_tracker.set_cooldown("gemini", duration_seconds=3600)
    assert quota_tracker.in_cooldown("gemini")


def test_success_rate_no_data(quota_tracker):
    rate = quota_tracker.get_success_rate("unknown_provider")
    assert rate == 1.0  # No data → assume healthy


def test_success_rate_with_failures(quota_tracker):
    quota_tracker.record(UsageRecord(provider="codex", success=True))
    quota_tracker.record(UsageRecord(provider="codex", success=True))
    quota_tracker.record(UsageRecord(provider="codex", success=False, error="timeout"))
    rate = quota_tracker.get_success_rate("codex")
    assert abs(rate - 2 / 3) < 0.01


def test_total_cost_month(quota_tracker):
    quota_tracker.record(UsageRecord(provider="claude", cost_usd=0.05, success=True))
    quota_tracker.record(UsageRecord(provider="claude", cost_usd=0.10, success=True))
    total = quota_tracker.total_cost_month()
    assert total >= 0.15
