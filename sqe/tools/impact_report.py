"""Generate impact report from replay outputs."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class IncidentStats:
    started: int
    updated: int
    resolved: int
    active_end: int
    mean_duration: float
    p50: float
    p95: float


def _read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = int((percentile / 100) * len(sorted_values) + 0.999999) - 1
    rank = max(0, min(rank, len(sorted_values) - 1))
    return sorted_values[rank]


def _format_float(value: float) -> str:
    return f"{value:.3f}"


def _signal_incident_stats(events: Iterable[Dict]) -> Tuple[IncidentStats, Dict[str, int]]:
    started = updated = resolved = 0
    durations: List[float] = []
    active: Dict[str, float] = {}
    cause_histogram: Dict[str, int] = {}
    for event in events:
        event_type = event["event_type"]
        incident = event["incident"]
        incident_id = incident["incident_id"]
        if event_type == "started":
            started += 1
            active[incident_id] = incident["start_timestamp"]
            cause = incident["cause"]
            cause_histogram[cause] = cause_histogram.get(cause, 0) + 1
        elif event_type == "updated":
            updated += 1
        elif event_type == "resolved":
            resolved += 1
            start = active.pop(incident_id, incident["start_timestamp"])
            end = incident["end_timestamp"] or incident["last_timestamp"]
            durations.append(max(0.0, end - start))
    stats = _build_stats(started, updated, resolved, len(active), durations)
    return stats, cause_histogram


def _group_incident_stats(
    events: Iterable[Dict],
) -> Tuple[IncidentStats, Dict[str, int], Dict[str, int]]:
    started = updated = resolved = 0
    durations: List[float] = []
    active: Dict[str, float] = {}
    cause_histogram: Dict[str, int] = {}
    starts_per_group: Dict[str, int] = {}
    for event in events:
        event_type = event["event_type"]
        group_id = event["group_id"]
        group_incident_id = event["group_incident_id"]
        if event_type == "started":
            started += 1
            active[group_incident_id] = event["timestamp"]
            cause = event["cause"]
            cause_histogram[cause] = cause_histogram.get(cause, 0) + 1
            starts_per_group[group_id] = starts_per_group.get(group_id, 0) + 1
        elif event_type == "updated":
            updated += 1
        elif event_type == "resolved":
            resolved += 1
            start = active.pop(group_incident_id, event["timestamp"])
            durations.append(max(0.0, event["timestamp"] - start))
    stats = _build_stats(started, updated, resolved, len(active), durations)
    return stats, cause_histogram, starts_per_group


def _build_stats(
    started: int,
    updated: int,
    resolved: int,
    active_end: int,
    durations: List[float],
) -> IncidentStats:
    mean_duration = sum(durations) / len(durations) if durations else 0.0
    p50 = _percentile(durations, 50)
    p95 = _percentile(durations, 95)
    return IncidentStats(
        started=started,
        updated=updated,
        resolved=resolved,
        active_end=active_end,
        mean_duration=mean_duration,
        p50=p50,
        p95=p95,
    )


def _sorted_histogram(histogram: Dict[str, int]) -> List[Tuple[str, int]]:
    return sorted(histogram.items(), key=lambda item: (-item[1], item[0]))


def _sorted_leaderboard(starts_per_group: Dict[str, int]) -> List[Tuple[str, int]]:
    return sorted(starts_per_group.items(), key=lambda item: (-item[1], item[0]))


def _build_report(
    signal_stats: IncidentStats,
    group_stats: IncidentStats,
    signal_causes: Dict[str, int],
    group_causes: Dict[str, int],
    starts_per_group: Dict[str, int],
) -> str:
    lines: List[str] = []
    lines.append("# Impact Report")
    lines.append("")
    lines.append("## Signal incidents")
    lines.append(f"- started: {signal_stats.started}")
    lines.append(f"- updated: {signal_stats.updated}")
    lines.append(f"- resolved: {signal_stats.resolved}")
    lines.append(f"- active_end: {signal_stats.active_end}")
    lines.append(f"- mean_duration: {_format_float(signal_stats.mean_duration)}")
    lines.append(f"- p50: {_format_float(signal_stats.p50)}")
    lines.append(f"- p95: {_format_float(signal_stats.p95)}")
    lines.append("")
    lines.append("## Group incidents")
    lines.append(f"- started: {group_stats.started}")
    lines.append(f"- updated: {group_stats.updated}")
    lines.append(f"- resolved: {group_stats.resolved}")
    lines.append(f"- active_end: {group_stats.active_end}")
    lines.append(f"- mean_duration: {_format_float(group_stats.mean_duration)}")
    lines.append(f"- p50: {_format_float(group_stats.p50)}")
    lines.append(f"- p95: {_format_float(group_stats.p95)}")
    lines.append("")
    lines.append("## Signal incident causes")
    for cause, count in _sorted_histogram(signal_causes):
        lines.append(f"- {cause}: {count}")
    if not signal_causes:
        lines.append("- none: 0")
    lines.append("")
    lines.append("## Group incident causes")
    for cause, count in _sorted_histogram(group_causes):
        lines.append(f"- {cause}: {count}")
    if not group_causes:
        lines.append("- none: 0")
    lines.append("")
    lines.append("## Spam reduction")
    lines.append(f"- signal_started_events: {signal_stats.started}")
    lines.append(f"- group_started_events: {group_stats.started}")
    ratio = (
        signal_stats.started / group_stats.started
        if group_stats.started
        else 0.0
    )
    lines.append(f"- ratio: {_format_float(ratio)}")
    lines.append("- starts_per_group:")
    for group_id, count in _sorted_leaderboard(starts_per_group):
        lines.append(f"  - {group_id}: {count}")
    if not starts_per_group:
        lines.append("  - none: 0")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate impact report from replay outputs."
    )
    parser.add_argument("--replay-dir", required=True, help="Replay output dir")
    parser.add_argument("--out-md", help="Optional markdown output path")
    args = parser.parse_args()

    replay_dir = Path(args.replay_dir)
    incidents = _read_jsonl(replay_dir / "incidents.jsonl")
    group_incidents = _read_jsonl(replay_dir / "group_incidents.jsonl")

    signal_stats, signal_causes = _signal_incident_stats(incidents)
    group_stats, group_causes, starts_per_group = _group_incident_stats(
        group_incidents
    )

    report = _build_report(
        signal_stats,
        group_stats,
        signal_causes,
        group_causes,
        starts_per_group,
    )
    print(report)
    if args.out_md:
        Path(args.out_md).write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
