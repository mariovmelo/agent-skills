"""Configuration manager — reads/writes ~/.uai/config.yaml."""
from __future__ import annotations
from pathlib import Path

import yaml

from uai.models.config import ConfigSchema, ProviderConfig


class ConfigManager:
    DEFAULT_DIR = Path.home() / ".uai"
    CONFIG_FILE = "config.yaml"

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or self.DEFAULT_DIR
        self.config_path = self.config_dir / self.CONFIG_FILE
        self._cache: ConfigSchema | None = None

    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Create ~/.uai/ and default config.yaml if they don't exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "sessions").mkdir(exist_ok=True)

        if not self.config_path.exists():
            default = ConfigSchema()
            self._write(default)

    def load(self) -> ConfigSchema:
        if self._cache is not None:
            return self._cache

        # Layer 1: user config (~/.uai/config.yaml)
        user_raw: dict = {}
        if self.config_path.exists():
            with self.config_path.open() as f:
                user_raw = yaml.safe_load(f) or {}

        # Layer 2: project config (.uai/config.yaml in cwd or parents)
        project_raw: dict = {}
        project_path = self._find_project_config()
        if project_path and project_path != self.config_path:
            with project_path.open() as f:
                project_raw = yaml.safe_load(f) or {}

        # Layer 3: environment variable overrides
        env_raw: dict = self._load_env_overrides()

        # Deep merge: user < project < env
        merged = self._deep_merge(user_raw, project_raw)
        merged = self._deep_merge(merged, env_raw)

        self._cache = ConfigSchema.model_validate(merged) if merged else ConfigSchema()
        return self._cache

    def _find_project_config(self) -> "Path | None":
        """Walk up from cwd looking for .uai/config.yaml (project-level config)."""
        import os
        cwd = Path(os.getcwd())
        home = Path.home()
        for parent in [cwd, *cwd.parents]:
            candidate = parent / ".uai" / "config.yaml"
            if candidate.exists():
                return candidate
            if parent == home or parent == parent.parent:
                break
        return None

    @staticmethod
    def _coerce_value(val: str) -> object:
        """Coerce a string to bool, int, float, or leave as str."""
        if val.lower() in ("true", "false"):
            return val.lower() == "true"
        try:
            return int(val)
        except ValueError:
            pass
        try:
            return float(val)
        except ValueError:
            return val

    @staticmethod
    def _load_env_overrides() -> dict:
        """Map UAI_* environment variables to nested config dict paths."""
        import os
        mapping: dict[str, list[str]] = {
            "UAI_DEFAULT_PROVIDER":  ["defaults", "provider"],
            "UAI_COST_MODE":         ["defaults", "cost_mode"],
            "UAI_DEFAULT_SESSION":   ["defaults", "session"],
            "UAI_THEME":             ["ux", "theme"],
            "UAI_STREAMING":         ["ux", "streaming"],
            "UAI_EDIT_MODE":         ["ux", "edit_mode"],
            "UAI_TIMEOUT":           ["defaults", "timeout"],
        }
        overrides: dict = {}
        for env_key, path in mapping.items():
            val = os.environ.get(env_key)
            if val is not None:
                node = overrides
                for part in path[:-1]:
                    node = node.setdefault(part, {})
                node[path[-1]] = ConfigManager._coerce_value(val)
        return overrides

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge override into base (override wins on conflict)."""
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def save(self, schema: ConfigSchema) -> None:
        self._write(schema)
        self._cache = schema

    def reload(self) -> ConfigSchema:
        self._cache = None
        return self.load()

    # ------------------------------------------------------------------
    def get_provider_config(self, name: str) -> ProviderConfig:
        cfg = self.load()
        return cfg.providers.get(name, ProviderConfig(enabled=False))

    def set(self, key_path: str, value: str) -> None:
        """Set a nested config value using dot-notation, e.g. defaults.cost_mode."""
        cfg = self.load()
        raw = cfg.model_dump()

        parts = key_path.split(".")
        node: dict = raw  # type: ignore[assignment]
        for part in parts[:-1]:
            node = node.setdefault(part, {})

        node[parts[-1]] = self._coerce_value(value)
        updated = ConfigSchema.model_validate(raw)
        self.save(updated)

    # ------------------------------------------------------------------
    def _write(self, schema: ConfigSchema) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w") as f:
            yaml.dump(schema.model_dump(), f, default_flow_style=False, allow_unicode=True)
