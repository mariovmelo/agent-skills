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
        if not self.config_path.exists():
            self._cache = ConfigSchema()
            return self._cache
        with self.config_path.open() as f:
            raw = yaml.safe_load(f) or {}
        self._cache = ConfigSchema.model_validate(raw)
        return self._cache

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

        # Attempt to coerce booleans and integers
        coerced: object = value
        if value.lower() in ("true", "false"):
            coerced = value.lower() == "true"
        else:
            try:
                coerced = int(value)
            except ValueError:
                try:
                    coerced = float(value)
                except ValueError:
                    pass

        node[parts[-1]] = coerced
        updated = ConfigSchema.model_validate(raw)
        self.save(updated)

    # ------------------------------------------------------------------
    def _write(self, schema: ConfigSchema) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w") as f:
            yaml.dump(schema.model_dump(), f, default_flow_style=False, allow_unicode=True)
