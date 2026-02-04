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
from sqe.core.event_filter import EventFilterPolicy
from sqe.core.incidents import IncidentCause, IncidentPolicy
from sqe.core.group_incidents import GroupIncidentPolicy
from sqe.core.grouping import GroupDefinition, GroupingConfig

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
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _validate_override_keys(
    override: Dict[str, Any],
    base: Dict[str, Any],
    path: str = "",
) -> None:
    for key, value in override.items():
        if key not in base:
            dotted = f"{path}{key}" if path else key
            raise ConfigError(f"Unknown configuration key: {dotted}")
        base_value = base[key]
        if isinstance(value, dict):
            if not isinstance(base_value, dict):
                dotted = f"{path}{key}" if path else key
                raise ConfigError(
                    f"Configuration section '{dotted}' must not be a mapping"
                )
            _validate_override_keys(value, base_value, f"{path}{key}.")


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
        _validate_override_keys(user_config, defaults)
        return _deep_merge(defaults, user_config)
    return defaults


def load_groups_config(user_path: str) -> Dict[str, Any]:
    """Load grouping configuration from a YAML file."""
    return _load_yaml(Path(user_path))


def get_engine_scan_interval(config: Dict[str, Any]) -> float:
    """Get scan interval from config with fallback to default."""
    return config.get("engine", {}).get("scan_interval", 0.1)


def get_engine_auto_register(config: Dict[str, Any]) -> bool:
    """Get auto-registration toggle from config with fallback to default."""
    return config.get("engine", {}).get("auto_register", True)


def get_engine_treat_missing_signals_as_none(config: Dict[str, Any]) -> bool:
    """Get missing signal handling policy."""
    return bool(config.get("engine", {}).get("treat_missing_signals_as_none", True))


def get_engine_unknown_signal_policy(config: Dict[str, Any]) -> str:
    """Get policy for unknown signals."""
    return str(config.get("engine", {}).get("unknown_signal_policy", "error"))


def get_engine_max_signals_policy(config: Dict[str, Any]) -> str:
    """Get policy for max signal limit handling."""
    return str(config.get("engine", {}).get("max_signals_policy", "error"))


def get_engine_max_signals(config: Dict[str, Any]) -> Optional[int]:
    """Get maximum signal count from config with fallback to default."""
    max_signals = config.get("performance", {}).get("max_signals", 1000)
    if max_signals is None:
        return None
    max_signals = int(max_signals)
    return max_signals if max_signals > 0 else None


def get_performance_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get performance settings from config with defaults."""
    performance = config.get("performance", {})
    compute_budget_ms = performance.get("compute_budget_ms")
    return {
        "compute_budget_ms": (
            float(compute_budget_ms) if compute_budget_ms is not None else None
        ),
        "load_shed_p95_window": int(performance.get("load_shed_p95_window", 50)),
        "load_shed_oscillation_cadence": int(
            performance.get("load_shed_oscillation_cadence", 3)
        ),
        "load_shed_skip_fft": bool(performance.get("load_shed_skip_fft", True)),
    }


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
    stale = config.get("stale", {})
    step_change = config.get("step_change", {})
    plausibility = config.get("plausibility", {})
    frequency = config.get("frequency", {})
    sqi = config.get("sqi", {})
    sqi_thresholds = sqi.get("thresholds", {})
    alerts = config.get("alerts", {})
    plausibility_rule = _resolve_plausibility_rule(plausibility, signal_id)

    return SignalConfig(
        signal_id=signal_id,
        ewma_alpha=filters.get("default_ewma_alpha", 0.3),
        ma_window=filters.get("default_ma_window", 10),
        small_drift_threshold=drift.get("small_threshold", 0.5),
        large_drift_threshold=drift.get("large_threshold", 5.0),
        variance_window=variance.get("default_window", 20),
        spike_k_sigma=variance.get("spike_k_sigma", 3.0),
        stale_window=stale.get("window", 5),
        stale_recovery_window=stale.get("recovery_window", 3),
        step_baseline_window=step_change.get("baseline_window", 10),
        step_threshold=step_change.get("threshold", 5.0),
        step_persistence_scans=step_change.get("persistence_scans", 3),
        step_recovery_scans=step_change.get("recovery_scans", 5),
        plausibility_min=plausibility_rule.get("min"),
        plausibility_max=plausibility_rule.get("max"),
        plausibility_max_rate=plausibility_rule.get("max_rate"),
        plausibility_persistence_scans=plausibility_rule.get("persistence_scans", 1),
        plausibility_recovery_scans=plausibility_rule.get("recovery_scans", 1),
        reference_frequencies=frequency.get("default_references"),
        sample_interval=sample_interval,
        freq_window=frequency.get("window_size", 50),
        enable_fft=frequency.get("enable_fft", False),
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


def _resolve_plausibility_rule(
    plausibility: Dict[str, Any],
    signal_id: str,
) -> Dict[str, Any]:
    default_rule = plausibility.get("default", {}) if plausibility else {}
    by_signal = plausibility.get("by_signal", {}) if plausibility else {}
    by_prefix = plausibility.get("by_prefix", {}) if plausibility else {}

    rule: Dict[str, Any] = {}
    rule.update(default_rule)
    if signal_id in by_signal:
        rule.update(by_signal[signal_id] or {})
        return rule

    matched_prefix = ""
    for prefix, prefix_rule in (by_prefix or {}).items():
        if signal_id.startswith(prefix) and len(prefix) > len(matched_prefix):
            matched_prefix = prefix
            rule.update(prefix_rule or {})

    return rule


def get_incident_policy(config: Dict[str, Any]) -> IncidentPolicy:
    """Build IncidentPolicy from merged config values."""
    incidents = config.get("incidents", {})

    def require_range(
        name: str, value: Any, min_value: float, max_value: float
    ) -> float:
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
            IncidentCause.STALE,
            IncidentCause.STEP,
            IncidentCause.PLAUSIBILITY,
            IncidentCause.DRIFT,
            IncidentCause.SPIKES,
            IncidentCause.NOISE,
            IncidentCause.OSCILLATION,
            IncidentCause.UNKNOWN,
        ]

    hard_fault_config = incidents.get("hard_fault_causes")
    if hard_fault_config is None:
        hard_fault_causes = [
            IncidentCause.MISSING,
            IncidentCause.STALE,
            IncidentCause.STEP,
            IncidentCause.PLAUSIBILITY,
        ]
    else:
        hard_fault_causes = []
        for name in hard_fault_config:
            try:
                hard_fault_causes.append(IncidentCause(str(name).lower()))
            except ValueError as exc:
                raise ValueError(f"Unknown hard fault cause: {name}") from exc

    return IncidentPolicy(
        start_sqi_threshold=start_sqi_threshold,
        end_sqi_threshold=end_sqi_threshold,
        start_persistence_scans=start_persistence_scans,
        end_persistence_scans=end_persistence_scans,
        critical_sqi_threshold=critical_sqi_threshold,
        component_score_floor=component_score_floor,
        cause_priority=priority,
        hard_fault_causes=hard_fault_causes,
        emit_update_on_cause_change=bool(
            incidents.get("emit_update_on_cause_change", True)
        ),
        emit_update_on_severity_change=bool(
            incidents.get("emit_update_on_severity_change", True)
        ),
    )


def get_grouping_config(config: Dict[str, Any]) -> GroupingConfig:
    """Build GroupingConfig from grouping configuration values."""
    grouping = config.get("grouping", {})
    mode = str(grouping.get("mode", "prefix")).lower()
    if mode not in {"prefix", "explicit"}:
        raise ValueError("grouping.mode must be 'prefix' or 'explicit'")

    prefix_delimiter = str(grouping.get("prefix_delimiter", "_"))
    prefix_depth = int(grouping.get("prefix_depth", 2))
    if prefix_depth <= 0:
        raise ValueError("grouping.prefix_depth must be > 0")

    explicit_groups: List[GroupDefinition] = []
    for entry in grouping.get("explicit_groups", []) or []:
        if not isinstance(entry, dict):
            raise ValueError("grouping.explicit_groups must be a list of mappings")
        group_id = str(entry.get("group_id", "")).strip()
        if not group_id:
            raise ValueError("grouping.explicit_groups group_id is required")
        signal_ids = entry.get("signal_ids")
        if not isinstance(signal_ids, list):
            raise ValueError(
                f"grouping.explicit_groups signal_ids missing for {group_id}"
            )
        explicit_groups.append(
            GroupDefinition(
                group_id=group_id,
                signal_ids=[str(signal_id) for signal_id in signal_ids],
            )
        )

    min_members = int(grouping.get("min_members_for_group_incident", 2))
    if min_members <= 0:
        raise ValueError("grouping.min_members_for_group_incident must be > 0")
    min_fraction = float(grouping.get("min_fraction_for_group_incident", 0.5))
    if min_fraction < 0.0 or min_fraction > 1.0:
        raise ValueError(
            "grouping.min_fraction_for_group_incident must be between 0 and 1"
        )
    persistence_scans = int(grouping.get("persistence_scans", 2))
    resolve_scans = int(grouping.get("resolve_persistence_scans", 2))
    if persistence_scans <= 0 or resolve_scans <= 0:
        raise ValueError("grouping persistence scans must be > 0")

    return GroupingConfig(
        mode=mode,
        prefix_delimiter=prefix_delimiter,
        prefix_depth=prefix_depth,
        explicit_groups=explicit_groups,
        min_members_for_group_incident=min_members,
        min_fraction_for_group_incident=min_fraction,
        persistence_scans=persistence_scans,
        resolve_persistence_scans=resolve_scans,
    )


def get_group_incident_policy(
    config: Dict[str, Any],
    grouping_config: Optional[GroupingConfig] = None,
) -> GroupIncidentPolicy:
    """Build GroupIncidentPolicy from group incident configuration values."""
    group_incidents = config.get("group_incidents", {})
    grouping = grouping_config or GroupingConfig(mode="prefix")

    def read_int(name: str, value: Any, fallback: int) -> int:
        number = int(value if value is not None else fallback)
        if number <= 0:
            raise ValueError(f"{name} must be > 0")
        return number

    def read_fraction(name: str, value: Any, fallback: float) -> float:
        number = float(value if value is not None else fallback)
        if number < 0.0 or number > 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        return number

    min_members = read_int(
        "group_incidents.min_members_for_start",
        group_incidents.get("min_members_for_start"),
        grouping.min_members_for_group_incident,
    )
    min_fraction = read_fraction(
        "group_incidents.min_fraction_for_start",
        group_incidents.get("min_fraction_for_start"),
        grouping.min_fraction_for_group_incident,
    )
    start_persistence = read_int(
        "group_incidents.start_persistence_scans",
        group_incidents.get("start_persistence_scans"),
        grouping.persistence_scans,
    )
    end_persistence = read_int(
        "group_incidents.end_persistence_scans",
        group_incidents.get("end_persistence_scans"),
        grouping.resolve_persistence_scans,
    )
    critical_fraction = read_fraction(
        "group_incidents.critical_fraction_threshold",
        group_incidents.get("critical_fraction_threshold"),
        0.8,
    )
    emit_updates = bool(group_incidents.get("emit_updates", True))

    return GroupIncidentPolicy(
        min_members_for_start=min_members,
        min_fraction_for_start=min_fraction,
        start_persistence_scans=start_persistence,
        end_persistence_scans=end_persistence,
        critical_fraction_threshold=critical_fraction,
        emit_updates=emit_updates,
    )


def get_event_filter_policy(config: Dict[str, Any]) -> EventFilterPolicy:
    """Build EventFilterPolicy from config values."""
    event_filter = config.get("event_filter")
    if not event_filter:
        return EventFilterPolicy(
            suppress_member_events=True,
            suppress_when_group_event_active=True,
        )

    suppress_group_causes = event_filter.get("suppress_group_causes", ["comms"])
    if not isinstance(suppress_group_causes, list):
        raise ValueError("event_filter.suppress_group_causes must be a list")
    suppress_event_types = event_filter.get(
        "suppress_event_types", ["started", "updated"]
    )
    if not isinstance(suppress_event_types, list):
        raise ValueError("event_filter.suppress_event_types must be a list")

    return EventFilterPolicy(
        suppress_member_events=bool(event_filter.get("suppress_member_events", True)),
        suppress_when_group_event_active=bool(
            event_filter.get("suppress_when_group_event_active", True)
        ),
        suppress_group_causes=[str(cause) for cause in suppress_group_causes],
        suppress_event_types=[str(event_type) for event_type in suppress_event_types],
        allow_resolved_passthrough=bool(
            event_filter.get("allow_resolved_passthrough", True)
        ),
        include_suppression_stats=bool(
            event_filter.get("include_suppression_stats", True)
        ),
    )
