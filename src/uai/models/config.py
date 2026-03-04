"""Configuration schema models (Pydantic)."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    enabled: bool = True
    default_model: str | None = None
    preferred_backend: str = "cli"   # "cli" | "api" | "auto"  — cli is default
    priority: int = 3                # 1-5; higher = preferred (when cost is equal)
    daily_limit: int | None = None
    cli_authenticated: bool = False  # True after `uai connect` OAuth is completed
    file_access: str = "readwrite"   # "readonly" | "readwrite" — controls whether AI responses can write files on disk
    extra: dict[str, Any] = Field(default_factory=dict)


class DefaultsConfig(BaseModel):
    session: str = "default"
    cost_mode: str = "free_only"          # free_only | balanced | performance
    max_cost_per_request: float = 0.10
    context_strategy: str = "auto"        # auto | full | windowed | summarized
    context_window_turns: int = 20
    output_format: str = "text"           # text | json | markdown
    timeout: int = 120


class RoutingConfig(BaseModel):
    fallback_chain: list[str] = Field(
        default_factory=lambda: ["gemini", "qwen", "claude", "codex"]
    )
    task_routing: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "debugging":       ["codex", "claude", "gemini", "qwen"],
            "code_generation": ["codex", "qwen", "claude", "gemini"],
            "code_review":     ["qwen", "gemini", "claude"],
            "architecture":    ["gemini", "claude", "codex", "qwen"],
            "long_context":    ["gemini", "claude"],
            "general_chat":    ["gemini", "qwen", "claude"],
            "batch_processing":["qwen", "gemini"],
            "privacy_audit":   ["qwen", "gemini", "claude"],
        }
    )


class ContextConfig(BaseModel):
    summarize_with: str = "gemini"
    summarize_model: str = "flash"
    max_history_tokens: int = 50_000
    keep_recent_turns: int = 10


class QuotaAlertConfig(BaseModel):
    alert_threshold_usd: float = 1.0
    alert_threshold_percent: int = 80


class UXConfig(BaseModel):
    theme: str = "default"          # default | dark | minimal
    streaming: bool = True          # enable streaming responses
    spinner_style: str = "dots"     # dots | line | arc | bouncingBar
    edit_mode: str = "show"         # "show" (display diffs) | "apply" (write to files)


class SessionConfig(BaseModel):
    max_sessions: int = 50
    max_age_days: int = 90
    project_isolation: bool = False


# Backward-compat alias
QuotaConfig = QuotaAlertConfig


class ConfigSchema(BaseModel):
    version: int = 1
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    ux: UXConfig = Field(default_factory=UXConfig)
    sessions: SessionConfig = Field(default_factory=SessionConfig)
    providers: dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "gemini":   ProviderConfig(preferred_backend="cli",  priority=5),
            "qwen":     ProviderConfig(preferred_backend="cli",  priority=4, daily_limit=1000),
            "claude":   ProviderConfig(preferred_backend="cli",  priority=2),
            "codex":    ProviderConfig(preferred_backend="cli",  priority=2),
            "deepseek": ProviderConfig(enabled=False, preferred_backend="api", priority=3),
            "groq":     ProviderConfig(enabled=False, preferred_backend="api", priority=3),
        }
    )
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    quota: QuotaAlertConfig = Field(default_factory=QuotaAlertConfig)
