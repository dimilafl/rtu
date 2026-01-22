"""
Configuration loader for Signal Quality Engine.

Loads sqe/config/defaults.yaml and merges optional user overrides.
"""

from __future__ import annotations

from copy import deepcopy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from sqe.core.engine import SignalConfig
from sqe.core.incidents import IncidentCause, IncidentPolicy

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "defaults.yaml"


class ConfigError(RuntimeError):
    """Raised when configuration files cannot be loaded."""


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Top-level YAML must be a mapping: {path}")
    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config(user_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from defaults.yaml and optional user override.

    Args:
        user_path: Optional path to user YAML config.

    Returns:
        Merged configuration dictionary.
    """
    defaults = _load_yaml(DEFAULT_CONFIG_PATH)
    if user_path:
        user_config = _load_yaml(Path(user_path))
        return _deep_merge(defaults, user_config)
    return defaults


def get_engine_scan_interval(config: Dict[str, Any]) -> float:
    """Get scan interval from config with fallback to default."""
    return config.get("engine", {}).get("scan_interval", 0.1)


def get_engine_auto_register(config: Dict[str, Any]) -> bool:
    """Get auto-registration toggle from config with fallback to default."""
    return config.get("engine", {}).get("auto_register", True)


def get_engine_max_signals(config: Dict[str, Any]) -> Optional[int]:
    """Get maximum signal count from config with fallback to default."""
    max_signals = config.get("performance", {}).get("max_signals", 1000)
    if max_signals is None:
        return None
    max_signals = int(max_signals)
    return max_signals if max_signals > 0 else None


def get_logging_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get logging settings from config with defaults."""
    logging_config = config.get("logging", {})
    return {
        "level": logging_config.get("level", "INFO"),
        "log_scan_timing": logging_config.get("log_scan_timing", False),
        "log_quality_changes": logging_config.get("log_quality_changes", True),
        "log_anomalies": logging_config.get("log_anomalies", True),
    }


def configure_logging(config: Dict[str, Any]) -> Dict[str, Any]:
    """Configure Python logging based on config settings."""
    settings = get_logging_settings(config)
    level_name = str(settings["level"]).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return settings


def build_signal_config(
    config: Dict[str, Any],
    signal_id: str,
    sample_interval: float,
) -> SignalConfig:
    """
    Build SignalConfig from merged config values.

    Mapping:
        engine.scan_interval -> SignalConfig.sample_interval
        filters.default_ewma_alpha -> SignalConfig.ewma_alpha
        filters.default_ma_window -> SignalConfig.ma_window
        drift.small_threshold -> SignalConfig.small_drift_threshold
        drift.large_threshold -> SignalConfig.large_drift_threshold
        variance.default_window -> SignalConfig.variance_window
        variance.spike_k_sigma -> SignalConfig.spike_k_sigma
        frequency.default_references -> SignalConfig.reference_frequencies
        frequency.window_size -> SignalConfig.freq_window
        sqi.weights -> SignalConfig.sqi_weights
        sqi.thresholds.noise -> SignalConfig.sqi_noise_threshold
        sqi.thresholds.drift -> SignalConfig.sqi_drift_threshold
        sqi.thresholds.spike_frequency -> SignalConfig.sqi_spike_threshold
        sqi.thresholds.oscillation -> SignalConfig.sqi_oscillation_threshold
        alerts.sqi_critical_threshold -> SignalConfig.sqi_critical_threshold
        alerts.sqi_warning_threshold -> SignalConfig.sqi_warning_threshold
        alerts.drift_alert_threshold -> SignalConfig.drift_alert_threshold
        alerts.spike_alert_threshold -> SignalConfig.spike_alert_threshold
    """
    filters = config.get("filters", {})
    drift = config.get("drift", {})
    variance = config.get("variance", {})
    frequency = config.get("frequency", {})
    sqi = config.get("sqi", {})
    sqi_thresholds = sqi.get("thresholds", {})
    alerts = config.get("alerts", {})

    return SignalConfig(
        signal_id=signal_id,
        ewma_alpha=filters.get("default_ewma_alpha", 0.3),
        ma_window=filters.get("default_ma_window", 10),
        small_drift_threshold=drift.get("small_threshold", 0.5),
        large_drift_threshold=drift.get("large_threshold", 5.0),
        variance_window=variance.get("default_window", 20),
        spike_k_sigma=variance.get("spike_k_sigma", 3.0),
        reference_frequencies=frequency.get("default_references"),
        sample_interval=sample_interval,
        freq_window=frequency.get("window_size", 50),
        sqi_weights=sqi.get("weights"),
        sqi_noise_threshold=sqi_thresholds.get("noise", 0.1),
        sqi_drift_threshold=sqi_thresholds.get("drift", 1.0),
        sqi_spike_threshold=sqi_thresholds.get("spike_frequency", 0.05),
        sqi_oscillation_threshold=sqi_thresholds.get("oscillation", 0.3),
        sqi_critical_threshold=alerts.get("sqi_critical_threshold", 25.0),
        sqi_warning_threshold=alerts.get("sqi_warning_threshold", 50.0),
        drift_alert_threshold=alerts.get("drift_alert_threshold", 5.0),
        spike_alert_threshold=alerts.get("spike_alert_threshold", 0.1),
    )


def get_incident_policy(config: Dict[str, Any]) -> IncidentPolicy:
    """Build IncidentPolicy from merged config values."""
    incidents = config.get("incidents", {})

    def require_range(name: str, value: Any, min_value: float, max_value: float) -> float:
        number = float(value)
        if number < min_value or number > max_value:
            raise ValueError(f"{name} must be between {min_value} and {max_value}")
        return number

    def require_positive_int(name: str, value: Any) -> int:
        number = int(value)
        if number <= 0:
            raise ValueError(f"{name} must be > 0")
        return number

    start_sqi_threshold = require_range(
        "incidents.start_sqi_threshold",
        incidents.get("start_sqi_threshold", 50),
        0,
        100,
    )
    end_sqi_threshold = require_range(
        "incidents.end_sqi_threshold",
        incidents.get("end_sqi_threshold", 60),
        0,
        100,
    )
    critical_sqi_threshold = require_range(
        "incidents.critical_sqi_threshold",
        incidents.get("critical_sqi_threshold", 25),
        0,
        100,
    )
    component_score_floor = require_range(
        "incidents.component_score_floor",
        incidents.get("component_score_floor", 70),
        0,
        100,
    )
    start_persistence_scans = require_positive_int(
        "incidents.start_persistence_scans",
        incidents.get("start_persistence_scans", 5),
    )
    end_persistence_scans = require_positive_int(
        "incidents.end_persistence_scans",
        incidents.get("end_persistence_scans", 10),
    )

    priority_config = incidents.get("cause_priority")
    if priority_config:
        priority: List[IncidentCause] = []
        for name in priority_config:
            try:
                priority.append(IncidentCause(str(name).lower()))
            except ValueError as exc:
                raise ValueError(f"Unknown incident cause: {name}") from exc
    else:
        priority = [
            IncidentCause.MISSING,
            IncidentCause.DRIFT,
            IncidentCause.SPIKES,
            IncidentCause.NOISE,
            IncidentCause.OSCILLATION,
            IncidentCause.UNKNOWN,
        ]

    return IncidentPolicy(
        start_sqi_threshold=start_sqi_threshold,
        end_sqi_threshold=end_sqi_threshold,
        start_persistence_scans=start_persistence_scans,
        end_persistence_scans=end_persistence_scans,
        critical_sqi_threshold=critical_sqi_threshold,
        component_score_floor=component_score_floor,
        cause_priority=priority,
        emit_update_on_cause_change=bool(
            incidents.get("emit_update_on_cause_change", True)
        ),
        emit_update_on_severity_change=bool(
            incidents.get("emit_update_on_severity_change", True)
        ),
    )
