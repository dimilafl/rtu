"""
Configuration loader for Signal Quality Engine.

Loads default settings from defaults.yaml and merges user overrides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union
import copy

import yaml


DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")


@dataclass(frozen=True)
class SQEConfig:
    """Immutable wrapper around configuration data."""

    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Return a deep copy of the configuration data."""
        return copy.deepcopy(self.data)


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config file must define a mapping: {path}")

    return data


def merge_configs(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> Dict[str, Any]:
    """Deep-merge two config mappings, preferring overrides."""
    merged: Dict[str, Any] = copy.deepcopy(dict(base))

    for key, value in overrides.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)

    return merged


def load_config(
    config_path: Optional[Union[str, Path]] = None,
    *,
    as_object: bool = False
) -> Union[Dict[str, Any], SQEConfig]:
    """Load defaults and merge with optional overrides."""
    defaults = _load_yaml(DEFAULTS_PATH)
    overrides = {}

    if config_path:
        overrides = _load_yaml(Path(config_path))

    merged = merge_configs(defaults, overrides)

    if as_object:
        return SQEConfig(merged)

    return merged


def normalize_config(config: Optional[Union[Dict[str, Any], SQEConfig]]) -> Dict[str, Any]:
    """Normalize configuration input into a dictionary."""
    defaults = _load_yaml(DEFAULTS_PATH)

    if config is None:
        return defaults

    if isinstance(config, SQEConfig):
        return merge_configs(defaults, config.to_dict())

    if hasattr(config, "to_dict"):
        return merge_configs(defaults, config.to_dict())

    if isinstance(config, dict):
        return merge_configs(defaults, copy.deepcopy(config))

    raise TypeError("Config must be a dict or SQEConfig instance")
