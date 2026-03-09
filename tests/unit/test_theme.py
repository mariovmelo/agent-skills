"""Tests for src/uai/cli/theme.py"""
from __future__ import annotations
import pytest

from rich.console import Console

from uai.cli.theme import THEMES, ThemeManager


class TestThemes:
    def test_three_built_in_themes(self):
        assert "default" in THEMES
        assert "dark" in THEMES
        assert "minimal" in THEMES

    def test_all_themes_have_identical_key_sets(self):
        key_sets = [frozenset(v.keys()) for v in THEMES.values()]
        assert all(k == key_sets[0] for k in key_sets), (
            "Themes have different key sets: "
            + str([sorted(k) for k in key_sets])
        )

    def test_default_theme_has_primary_key(self):
        assert "uai.primary" in THEMES["default"]

    def test_default_theme_has_error_key(self):
        assert "uai.error" in THEMES["default"]

    def test_default_theme_has_success_key(self):
        assert "uai.success" in THEMES["default"]

    def test_default_theme_has_dim_key(self):
        assert "uai.dim" in THEMES["default"]


class TestThemeManager:
    def test_known_theme_name(self):
        tm = ThemeManager("default")
        assert tm.name == "default"

    def test_dark_theme_name(self):
        tm = ThemeManager("dark")
        assert tm.name == "dark"

    def test_minimal_theme_name(self):
        tm = ThemeManager("minimal")
        assert tm.name == "minimal"

    def test_unknown_theme_falls_back_to_default(self):
        tm = ThemeManager("nonexistent")
        assert tm.name == "default"

    def test_no_arg_defaults_to_default(self):
        tm = ThemeManager()
        assert tm.name == "default"

    def test_make_console_returns_console_instance(self):
        tm = ThemeManager("dark")
        console = tm.make_console()
        assert isinstance(console, Console)

    def test_make_console_accepts_kwargs(self):
        tm = ThemeManager("default")
        from io import StringIO
        buf = StringIO()
        console = tm.make_console(file=buf, force_terminal=False)
        assert isinstance(console, Console)

    def test_available_themes(self):
        themes = ThemeManager.available_themes()
        assert "default" in themes
        assert "dark" in themes
        assert "minimal" in themes

    def test_available_themes_is_list(self):
        assert isinstance(ThemeManager.available_themes(), list)
