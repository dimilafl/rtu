"""Metrics for incident detection evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqe.eval.labels import IncidentLabel


@dataclass(frozen=True)
class PredictedIncidentStart:
    signal_id: str
    start_scan_index: int
    end_scan_index: Optional[int]
    cause: Optional[str]
    severity: Optional[str]


def load_predicted_started_events(path: str) -> List[PredictedIncidentStart]:
    """Load predicted started events from incidents.jsonl."""
    events: List[PredictedIncidentStart] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if record.get("event_type") != "started":
                continue
            incident = record.get("incident", {})
            events.append(
                PredictedIncidentStart(
                    signal_id=str(incident.get("signal_id", "")).strip(),
                    start_scan_index=int(incident.get("start_scan_index", 0)),
                    end_scan_index=_optional_int(incident.get("last_scan_index")),
                    cause=_optional_str(incident.get("cause")),
                    severity=_optional_str(incident.get("severity")),
                )
            )
    events.sort(key=lambda item: (item.signal_id, item.start_scan_index))
    return events


def count_group_started_events(path: str) -> int:
    """Count group incident started events from group_incidents.jsonl."""
    count = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if record.get("event_type") == "started":
                count += 1
    return count


def match_predicted_to_labels(
    predicted_started_events: List[PredictedIncidentStart],
    labels: List[IncidentLabel],
) -> Tuple[List[Tuple[PredictedIncidentStart, IncidentLabel]], List[IncidentLabel]]:
    """Match predicted incidents to labels using greedy interval overlap."""
    predicted_sorted = sorted(
        predicted_started_events,
        key=lambda item: (item.signal_id, item.start_scan_index),
    )
    label_sorted = sorted(
        labels,
        key=lambda item: (item.signal_id, item.start_scan_index),
    )
    matched: List[Tuple[PredictedIncidentStart, IncidentLabel]] = []
    unmatched_labels: List[IncidentLabel] = []
    label_used = [False] * len(label_sorted)

    for predicted in predicted_sorted:
        matched_label_index = None
        pred_start = predicted.start_scan_index
        pred_end = (
            predicted.end_scan_index
            if predicted.end_scan_index is not None
            else predicted.start_scan_index
        )
        for idx, label in enumerate(label_sorted):
            if label_used[idx]:
                continue
            if label.signal_id != predicted.signal_id:
                continue
            if _intervals_overlap(
                pred_start, pred_end, label.start_scan_index, label.end_scan_index
            ):
                matched_label_index = idx
                break
        if matched_label_index is not None:
            label_used[matched_label_index] = True
            matched.append((predicted, label_sorted[matched_label_index]))

    for idx, label in enumerate(label_sorted):
        if not label_used[idx]:
            unmatched_labels.append(label)

    return matched, unmatched_labels


def compute_metrics(
    predicted_started_events: List[PredictedIncidentStart],
    labels: List[IncidentLabel],
    group_started_count: int,
) -> Dict[str, object]:
    """Compute detection and spam metrics."""
    matched, _unmatched_labels = match_predicted_to_labels(
        predicted_started_events, labels
    )

    total_predicted = len(predicted_started_events)
    total_labels = len(labels)
    matched_count = len(matched)

    precision = matched_count / total_predicted if total_predicted else 0.0
    recall = matched_count / total_labels if total_labels else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    time_to_detect = [
        max(0, predicted.start_scan_index - label.start_scan_index)
        for predicted, label in matched
    ]
    mean_time_to_detect = (
        sum(time_to_detect) / len(time_to_detect) if time_to_detect else 0.0
    )

    cause_total = 0
    cause_correct = 0
    severity_total = 0
    severity_correct = 0
    for predicted, label in matched:
        if label.cause is not None:
            cause_total += 1
            if _normalize(label.cause) == _normalize(predicted.cause):
                cause_correct += 1
        if label.severity is not None:
            severity_total += 1
            if _normalize(label.severity) == _normalize(predicted.severity):
                severity_correct += 1

    cause_accuracy = cause_correct / cause_total if cause_total else 0.0
    severity_accuracy = (
        severity_correct / severity_total if severity_total else 0.0
    )

    total_signal_started = total_predicted
    total_group_started = group_started_count
    starts_ratio = total_signal_started / max(1, total_group_started)

    return {
        "detection_precision": precision,
        "detection_recall": recall,
        "detection_f1": f1,
        "mean_time_to_detect_scans": mean_time_to_detect,
        "cause_accuracy": cause_accuracy,
        "severity_accuracy": severity_accuracy,
        "spam_metrics": {
            "total_signal_started": total_signal_started,
            "total_group_started": total_group_started,
            "starts_ratio": starts_ratio,
        },
    }


def _intervals_overlap(
    start_a: int, end_a: int, start_b: int, end_b: int
) -> bool:
    return start_a <= end_b and end_a >= start_b


def _optional_int(value: Optional[object]) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()
