"""Configuration schema models (dataclasses — no external deps)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields
from typing import Any


def _from_dict(cls, data: dict) -> Any:
    """Recursively construct a dataclass from a dict, ignoring unknown keys."""
    if not isinstance(data, dict):
        return data
    kwargs = {}
    cls_fields = {f.name: f for f in fields(cls)}
    for name, f in cls_fields.items():
        if name not in data:
            continue
        val = data[name]
        ft = f.type
        # Unwrap string annotations
        if isinstance(ft, str):
            import sys
            ft = eval(ft, sys.modules[cls.__module__].__dict__)  # noqa: S307
        # Recurse into nested dataclasses
        try:
            if hasattr(ft, '__dataclass_fields__') and isinstance(val, dict):
                val = _from_dict(ft, val)
        except Exception:
            pass
        kwargs[name] = val
    return cls(**kwargs)


@dataclass
class ProviderConfig:
    enabled: bool = True
    default_model: str | None = None
    preferred_backend: str = "cli"
    priority: int = 3
    daily_limit: int | None = None
    cli_authenticated: bool = False
    file_access: str = "readwrite"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: dict) -> "ProviderConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class DefaultsConfig:
    session: str = "default"
    cost_mode: str = "free_only"
    max_cost_per_request: float = 0.10
    context_strategy: str = "auto"
    context_window_turns: int = 20
    output_format: str = "text"
    timeout: int = 120

    @classmethod
    def model_validate(cls, data: dict) -> "DefaultsConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class RoutingConfig:
    fallback_chain: list[str] = field(
        default_factory=lambda: ["gemini", "qwen", "claude", "codex"]
    )
    task_routing: dict[str, list[str]] = field(
        default_factory=lambda: {
            "debugging":        ["codex", "claude", "gemini", "qwen"],
            "code_generation":  ["codex", "claude", "qwen", "gemini"],
            "code_review":      ["qwen", "gemini", "claude"],
            "architecture":     ["gemini", "claude", "codex", "qwen"],
            "long_context":     ["gemini", "claude"],
            "general_chat":     ["gemini", "qwen", "claude"],
            "batch_processing": ["qwen", "gemini"],
            "privacy_audit":    ["qwen", "gemini", "claude"],
        }
    )

    @classmethod
    def model_validate(cls, data: dict) -> "RoutingConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class ContextConfig:
    summarize_with: str = "gemini"
    summarize_model: str = "flash"
    max_history_tokens: int = 50_000
    keep_recent_turns: int = 10

    @classmethod
    def model_validate(cls, data: dict) -> "ContextConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class QuotaAlertConfig:
    alert_threshold_usd: float = 1.0
    alert_threshold_percent: int = 80

    @classmethod
    def model_validate(cls, data: dict) -> "QuotaAlertConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class UXConfig:
    theme: str = "default"
    streaming: bool = True
    spinner_style: str = "dots"
    edit_mode: str = "show"

    @classmethod
    def model_validate(cls, data: dict) -> "UXConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class SessionConfig:
    max_sessions: int = 50
    max_age_days: int = 90
    project_isolation: bool = False

    @classmethod
    def model_validate(cls, data: dict) -> "SessionConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class RouterConfig:
    classification_cache_ttl: int = 300
    classification_cache_size: int = 512
    smart_classifier_timeout: float = 2.5
    rate_limiter_rate: float = 10.0
    rate_limiter_capacity: float = 20.0

    @classmethod
    def model_validate(cls, data: dict) -> "RouterConfig":
        return _from_dict(cls, data)

    def model_dump(self) -> dict:
        return asdict(self)


# Backward-compat alias
QuotaConfig = QuotaAlertConfig


def _providers_from_dict(data: dict) -> dict[str, ProviderConfig]:
    return {k: _from_dict(ProviderConfig, v) if isinstance(v, dict) else v
            for k, v in data.items()}


@dataclass
class ConfigSchema:
    version: int = 1
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    ux: UXConfig = field(default_factory=UXConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    providers: dict[str, ProviderConfig] = field(
        default_factory=lambda: {
            "gemini":   ProviderConfig(preferred_backend="cli",  priority=5),
            "qwen":     ProviderConfig(preferred_backend="cli",  priority=4, daily_limit=1000),
            "claude":   ProviderConfig(preferred_backend="cli",  priority=2),
            "codex":    ProviderConfig(preferred_backend="cli",  priority=2),
            "deepseek": ProviderConfig(enabled=False, preferred_backend="api", priority=3),
            "groq":     ProviderConfig(enabled=False, preferred_backend="api", priority=3),
        }
    )
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    quota: QuotaAlertConfig = field(default_factory=QuotaAlertConfig)
    router: RouterConfig = field(default_factory=RouterConfig)

    @classmethod
    def model_validate(cls, data: dict) -> "ConfigSchema":
        if not data:
            return cls()
        kwargs: dict[str, Any] = {}
        nested = {
            "defaults": DefaultsConfig,
            "ux": UXConfig,
            "sessions": SessionConfig,
            "routing": RoutingConfig,
            "context": ContextConfig,
            "quota": QuotaAlertConfig,
            "router": RouterConfig,
        }
        for key, val in data.items():
            if key == "providers" and isinstance(val, dict):
                kwargs["providers"] = _providers_from_dict(val)
            elif key in nested and isinstance(val, dict):
                kwargs[key] = _from_dict(nested[key], val)
            else:
                kwargs[key] = val
        return cls(**kwargs)

    def model_dump(self) -> dict:
        result = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if f.name == "providers":
                result["providers"] = {k: asdict(v) for k, v in val.items()}
            elif hasattr(val, "__dataclass_fields__"):
                result[f.name] = asdict(val)
            else:
                result[f.name] = val
        return result
