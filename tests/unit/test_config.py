"""Tests for ConfigManager."""
from __future__ import annotations
import pytest
import yaml
from uai.models.config import ConfigSchema


def test_initialize_creates_dirs(tmp_dir, config_mgr):
    assert config_mgr.config_dir.exists()
    assert (config_mgr.config_dir / "sessions").exists()


def test_load_returns_default_schema(config_mgr):
    cfg = config_mgr.load()
    assert isinstance(cfg, ConfigSchema)
    assert cfg.version == 1
    assert "gemini" in cfg.providers
    assert "qwen" in cfg.providers


def test_save_and_reload(config_mgr):
    cfg = config_mgr.load()
    cfg.defaults.cost_mode = "performance"
    config_mgr.save(cfg)

    reloaded = config_mgr.reload()
    assert reloaded.defaults.cost_mode == "performance"


def test_set_dot_notation(config_mgr):
    config_mgr.set("defaults.cost_mode", "balanced")
    cfg = config_mgr.reload()
    assert cfg.defaults.cost_mode == "balanced"


def test_set_boolean(config_mgr):
    config_mgr.set("providers.claude.enabled", "false")
    cfg = config_mgr.reload()
    assert cfg.providers["claude"].enabled is False


def test_get_provider_config(config_mgr):
    prov = config_mgr.get_provider_config("gemini")
    assert prov.enabled is True


def test_get_unknown_provider_config(config_mgr):
    prov = config_mgr.get_provider_config("unknown_provider")
    assert prov.enabled is False


# ── New tests for layered config and refactored helpers ────────────────────────

def test_project_config_overrides_user_config(tmp_dir):
    """Project .uai/config.yaml should win over user config."""
    import yaml
    from uai.core.config import ConfigManager

    # User config: cost_mode = free
    user_cfg = ConfigManager(tmp_dir)
    user_cfg.initialize()
    cfg = user_cfg.load()
    cfg.defaults.cost_mode = "free"
    user_cfg.save(cfg)
    user_cfg.reload()

    # Project config: cost_mode = performance
    import os
    project_dir = tmp_dir / "project"
    project_dir.mkdir()
    dot_uai = project_dir / ".uai"
    dot_uai.mkdir()
    (dot_uai / "config.yaml").write_text("defaults:\n  cost_mode: performance\n")

    # Load with project dir as cwd
    original_cwd = os.getcwd()
    try:
        os.chdir(project_dir)
        user_cfg._cache = None  # force reload
        loaded = user_cfg.load()
        assert loaded.defaults.cost_mode == "performance"
    finally:
        os.chdir(original_cwd)


def test_env_var_overrides_config(tmp_dir, monkeypatch):
    """UAI_THEME env var should override the theme from config files."""
    from uai.core.config import ConfigManager
    monkeypatch.setenv("UAI_THEME", "dark")

    mgr = ConfigManager(tmp_dir)
    mgr.initialize()
    cfg = mgr.load()
    assert cfg.ux.theme == "dark"


def test_env_var_streaming_coerced_to_bool(tmp_dir, monkeypatch):
    """UAI_STREAMING=false should coerce to bool False."""
    from uai.core.config import ConfigManager
    monkeypatch.setenv("UAI_STREAMING", "false")

    mgr = ConfigManager(tmp_dir)
    mgr.initialize()
    cfg = mgr.load()
    assert cfg.ux.streaming is False


def test_deep_merge_adds_nested_keys():
    """_deep_merge should combine nested dicts without losing keys from base."""
    from uai.core.config import ConfigManager
    result = ConfigManager._deep_merge(
        {"a": {"b": 1}},
        {"a": {"c": 2}},
    )
    assert result == {"a": {"b": 1, "c": 2}}


def test_deep_merge_override_wins_on_conflict():
    """_deep_merge: when both have same key, override wins."""
    from uai.core.config import ConfigManager
    result = ConfigManager._deep_merge(
        {"a": 1},
        {"a": 99},
    )
    assert result["a"] == 99


def test_coerce_value_bool_true():
    from uai.core.config import ConfigManager
    assert ConfigManager._coerce_value("true") is True
    assert ConfigManager._coerce_value("True") is True


def test_coerce_value_bool_false():
    from uai.core.config import ConfigManager
    assert ConfigManager._coerce_value("false") is False


def test_coerce_value_int():
    from uai.core.config import ConfigManager
    assert ConfigManager._coerce_value("42") == 42
    assert isinstance(ConfigManager._coerce_value("42"), int)


def test_coerce_value_float():
    from uai.core.config import ConfigManager
    assert ConfigManager._coerce_value("3.14") == pytest.approx(3.14)


def test_coerce_value_string_unchanged():
    from uai.core.config import ConfigManager
    assert ConfigManager._coerce_value("hello") == "hello"
