"""Theme system for UAI CLI using Rich's Theme."""
from __future__ import annotations

from rich.console import Console
from rich.theme import Theme


THEMES: dict[str, dict[str, str]] = {
    "default": {
        "uai.primary":      "bold cyan",
        "uai.secondary":    "yellow",
        "uai.success":      "bold green",
        "uai.error":        "bold red",
        "uai.warning":      "yellow",
        "uai.dim":          "dim",
        "uai.provider":     "cyan",
        "uai.model":        "dim cyan",
        "uai.cost.free":    "green",
        "uai.cost.paid":    "yellow",
        "uai.session":      "yellow",
        "uai.user_prompt":  "bold",
        "uai.spinner":      "cyan",
        "uai.fallback":     "yellow",
    },
    "dark": {
        "uai.primary":      "bold bright_cyan",
        "uai.secondary":    "bright_yellow",
        "uai.success":      "bold bright_green",
        "uai.error":        "bold bright_red",
        "uai.warning":      "bright_yellow",
        "uai.dim":          "grey50",
        "uai.provider":     "bright_cyan",
        "uai.model":        "grey70",
        "uai.cost.free":    "bright_green",
        "uai.cost.paid":    "yellow",
        "uai.session":      "bright_yellow",
        "uai.user_prompt":  "bold white",
        "uai.spinner":      "bright_cyan",
        "uai.fallback":     "bright_yellow",
    },
    "minimal": {
        "uai.primary":      "bold",
        "uai.secondary":    "italic",
        "uai.success":      "bold",
        "uai.error":        "bold",
        "uai.warning":      "italic",
        "uai.dim":          "dim",
        "uai.provider":     "bold",
        "uai.model":        "dim",
        "uai.cost.free":    "",
        "uai.cost.paid":    "italic",
        "uai.session":      "bold",
        "uai.user_prompt":  "bold",
        "uai.spinner":      "",
        "uai.fallback":     "italic",
    },
}


class ThemeManager:
    """Manages UAI color themes backed by Rich's Theme system."""

    def __init__(self, theme_name: str = "default") -> None:
        self._name = theme_name if theme_name in THEMES else "default"

    def make_console(self, **kwargs) -> Console:
        """Create a Rich Console pre-loaded with this theme's styles."""
        styles = THEMES[self._name]
        return Console(theme=Theme(styles), **kwargs)

    @property
    def name(self) -> str:
        return self._name

    @staticmethod
    def available_themes() -> list[str]:
        return list(THEMES.keys())
