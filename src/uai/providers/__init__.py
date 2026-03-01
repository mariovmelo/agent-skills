"""Provider registry with plugin discovery via entry points."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uai.providers.base import BaseProvider

_BUILTIN: dict[str, str] = {
    "claude":    "uai.providers.claude:ClaudeProvider",
    "gemini":    "uai.providers.gemini:GeminiProvider",
    "codex":     "uai.providers.codex:CodexProvider",
    "qwen":      "uai.providers.qwen:QwenProvider",
    "deepseek":  "uai.providers.deepseek:DeepSeekProvider",
    "groq":      "uai.providers.groq:GroqProvider",
}


def get_provider_class(name: str) -> type["BaseProvider"]:
    if name in _BUILTIN:
        module_path, class_name = _BUILTIN[name].rsplit(":", 1)
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)

    # Try third-party entry-points: uai.providers group
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="uai.providers")
        for ep in eps:
            if ep.name == name:
                return ep.load()
    except Exception:
        pass

    raise ValueError(f"Unknown provider: '{name}'. Available: {list_providers()}")


def list_providers() -> list[str]:
    names = list(_BUILTIN.keys())
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="uai.providers")
        names += [ep.name for ep in eps if ep.name not in names]
    except Exception:
        pass
    return names
