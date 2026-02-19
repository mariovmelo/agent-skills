"""Tests for ConfigManager."""
from __future__ import annotations
import pytest
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
