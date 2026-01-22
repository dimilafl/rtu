"""Configuration loader for Signal Quality Engine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import yaml

from sqe.core.engine import SignalConfig
from sqe.core.sqi import SQIWeights


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base."""
    merged: Dict[str, Any] = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a mapping at the root.")
    return data


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load default SQE configuration and merge a user config if provided.

    Args:
        config_path: Optional path to a YAML config file to merge.

    Returns:
        Combined configuration dictionary.
    """
    defaults_path = Path(__file__).with_name("defaults.yaml")
    config = _load_yaml(defaults_path)

    if config_path:
        user_path = Path(config_path)
        if not user_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        user_config = _load_yaml(user_path)
        config = _deep_merge(config, user_config)

    return config


def build_engine_settings(
    config: Mapping[str, Any],
    signal_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Build engine settings from configuration mapping.

    Args:
        config: Merged configuration dictionary.
        signal_ids: Optional sequence of signal identifiers to pre-register.

    Returns:
        Dictionary with engine instance and optional per-signal configs.
    """
    engine_config = config.get("engine", {})
    scan_interval = float(engine_config.get("scan_interval", 0.1))
    auto_register = bool(engine_config.get("auto_register", True))

    filters_config = config.get("filters", {})
    drift_config = config.get("drift", {})
    variance_config = config.get("variance", {})
    frequency_config = config.get("frequency", {})
    sqi_config = config.get("sqi", {})

    default_references = frequency_config.get("default_references") or [0.1, 0.5, 1.0]

    weights_config = sqi_config.get("weights", {})
    weights = SQIWeights(
        noise=float(weights_config.get("noise", 0.25)),
        drift=float(weights_config.get("drift", 0.25)),
        spikes=float(weights_config.get("spikes", 0.20)),
        oscillation=float(weights_config.get("oscillation", 0.15)),
        missing=float(weights_config.get("missing", 0.15)),
    )

    thresholds_config = sqi_config.get("thresholds", {})
    signal_defaults = {
        "ewma_alpha": float(filters_config.get("default_ewma_alpha", 0.3)),
        "ma_window": int(filters_config.get("default_ma_window", 10)),
        "small_drift_threshold": float(drift_config.get("small_threshold", 0.5)),
        "large_drift_threshold": float(drift_config.get("large_threshold", 5.0)),
        "variance_window": int(variance_config.get("default_window", 20)),
        "spike_k_sigma": float(variance_config.get("spike_k_sigma", 3.0)),
        "reference_frequencies": list(default_references),
        "sample_interval": scan_interval,
        "freq_window": int(frequency_config.get("window_size", 50)),
        "sqi_weights": weights,
        "sqi_noise_threshold": float(thresholds_config.get("noise", 0.1)),
        "sqi_drift_threshold": float(thresholds_config.get("drift", 1.0)),
        "sqi_spike_threshold": float(thresholds_config.get("spike_frequency", 0.05)),
        "sqi_oscillation_threshold": float(thresholds_config.get("oscillation", 0.3)),
    }

    signal_configs = {}
    for signal_id in signal_ids or []:
        signal_configs[signal_id] = SignalConfig(
            signal_id=signal_id,
            ewma_alpha=signal_defaults["ewma_alpha"],
            ma_window=signal_defaults["ma_window"],
            small_drift_threshold=signal_defaults["small_drift_threshold"],
            large_drift_threshold=signal_defaults["large_drift_threshold"],
            variance_window=signal_defaults["variance_window"],
            spike_k_sigma=signal_defaults["spike_k_sigma"],
            reference_frequencies=signal_defaults["reference_frequencies"],
            sample_interval=signal_defaults["sample_interval"],
            freq_window=signal_defaults["freq_window"],
            sqi_weights=signal_defaults["sqi_weights"],
            sqi_noise_threshold=signal_defaults["sqi_noise_threshold"],
            sqi_drift_threshold=signal_defaults["sqi_drift_threshold"],
            sqi_spike_threshold=signal_defaults["sqi_spike_threshold"],
            sqi_oscillation_threshold=signal_defaults["sqi_oscillation_threshold"],
        )

    return {
        "scan_interval": scan_interval,
        "auto_register": auto_register,
        "signal_defaults": signal_defaults,
        "signal_configs": signal_configs,
    }
