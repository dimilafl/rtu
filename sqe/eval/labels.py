"""Incident label loading for evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class IncidentLabel:
    signal_id: str
    start_scan_index: int
    end_scan_index: int
    cause: Optional[str]
    severity: Optional[str]


def load_labels(path: str) -> List[IncidentLabel]:
    """Load incident labels from YAML or JSON."""
    label_path = Path(path)
    if not label_path.exists():
        raise FileNotFoundError(f"Labels file not found: {path}")

    suffix = label_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        with label_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    elif suffix == ".json":
        with label_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        with label_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

    if not isinstance(payload, list):
        raise ValueError("Labels file must contain a list of labels")

    labels: List[IncidentLabel] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("Each label must be a mapping")
        signal_id = str(entry.get("signal_id", "")).strip()
        if not signal_id:
            raise ValueError("Each label must include signal_id")
        start_scan_index = _require_int(entry, "start_scan_index")
        end_scan_index = _require_int(entry, "end_scan_index")
        cause = _optional_str(entry.get("cause"))
        severity = _optional_str(entry.get("severity"))
        labels.append(
            IncidentLabel(
                signal_id=signal_id,
                start_scan_index=start_scan_index,
                end_scan_index=end_scan_index,
                cause=cause,
                severity=severity,
            )
        )

    labels.sort(key=lambda item: (item.signal_id, item.start_scan_index))
    return labels


def _require_int(entry: Dict[str, Any], key: str) -> int:
    if key not in entry:
        raise ValueError(f"Missing required label field: {key}")
    value = int(entry[key])
    return value


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
