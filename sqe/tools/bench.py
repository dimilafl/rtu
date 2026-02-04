"""Deterministic performance benchmark for SQE."""

from __future__ import annotations

import argparse
import logging
import math
import statistics
import time
from typing import Any, Dict, List, Optional
import random

from sqe.config.loader import (
    build_signal_config,
    get_engine_auto_register,
    get_engine_max_signals,
    get_engine_scan_interval,
    get_incident_policy,
    get_performance_settings,
    load_config,
)
from sqe.core.engine import SignalQualityEngine
from sqe.core.incidents import IncidentEngine
from sqe.ops.service import RealtimeQualityService


def _apply_fast_mode(config: Dict[str, Any]) -> Dict[str, Any]:
    frequency = dict(config.get("frequency", {}))
    frequency["enable_fft"] = False
    frequency.setdefault("default_references", [])
    config["frequency"] = frequency
    return config


def run_bench(
    signals: int,
    scans: int,
    scan_interval: float,
    missing_rate: float,
    config_path: Optional[str],
    fast: bool,
    progress_interval: int,
) -> None:
    logger = logging.getLogger(__name__)
    rng = random.Random(42)
    config = load_config(config_path)
    if fast:
        config = _apply_fast_mode(config)

    performance_settings = get_performance_settings(config)
    engine = SignalQualityEngine(
        scan_interval=scan_interval,
        auto_register=get_engine_auto_register(config),
        max_signals=get_engine_max_signals(config),
        log_scan_timing=False,
        log_quality_changes=False,
        log_anomalies=False,
        compute_budget_ms=performance_settings["compute_budget_ms"],
        load_shed_p95_window=performance_settings["load_shed_p95_window"],
        load_shed_oscillation_cadence=performance_settings[
            "load_shed_oscillation_cadence"
        ],
        load_shed_skip_fft=performance_settings["load_shed_skip_fft"],
    )
    signal_ids = [f"SIG_{index:04d}" for index in range(signals)]
    for signal_id in signal_ids:
        engine.register_signal(
            signal_id,
            build_signal_config(config, signal_id, scan_interval),
        )

    incident_engine = IncidentEngine(get_incident_policy(config))
    service = RealtimeQualityService(engine, incident_engine)

    base_values = {signal_id: rng.uniform(-5.0, 5.0) for signal_id in signal_ids}
    scan_durations: List[float] = []
    total_events = 0
    bench_start = time.perf_counter()

    for scan_index in range(scans):
        timestamp = scan_index * scan_interval
        scan_values: Dict[str, Optional[float]] = {}
        for signal_id in signal_ids:
            if rng.random() < missing_rate:
                scan_values[signal_id] = None
                continue
            base = base_values[signal_id]
            noise = rng.gauss(0.0, 0.1)
            scan_values[signal_id] = base + math.sin(scan_index * 0.01) + noise

        start = time.perf_counter()
        _, events, _ = service.process_scan(scan_values, timestamp=timestamp)
        end = time.perf_counter()
        scan_durations.append(end - start)
        total_events += len(events)
        if progress_interval > 0 and (scan_index + 1) % progress_interval == 0:
            elapsed = time.perf_counter() - bench_start
            logger.info(
                "Processed %d/%d scans (elapsed %.2fs)",
                scan_index + 1,
                scans,
                elapsed,
            )

    total_time = sum(scan_durations)
    mean_scan_time = statistics.mean(scan_durations) if scan_durations else 0.0
    sorted_times = sorted(scan_durations)
    if sorted_times:
        p95_index = int(0.95 * (len(sorted_times) - 1))
        p95 = sorted_times[p95_index]
    else:
        p95 = 0.0

    events_per_1000 = (total_events / scans * 1000) if scans else 0.0

    print("SQE Benchmark Report")
    print(f"Signals: {signals}")
    print(f"Scans: {scans}")
    print(f"Scan interval: {scan_interval}")
    print(f"Missing rate: {missing_rate:.2f}")
    print(f"Total time: {total_time:.4f}s")
    print(f"Mean scan time: {mean_scan_time:.6f}s")
    print(f"P95 scan time: {p95:.6f}s")
    print(f"Events per 1000 scans: {events_per_1000:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SQE performance benchmark")
    parser.add_argument("--signals", type=int, default=200)
    parser.add_argument("--scans", type=int, default=1000)
    parser.add_argument("--scan-interval", type=float, default=0.1)
    parser.add_argument("--missing-rate", type=float, default=0.01)
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=100,
        help="Log progress every N scans (0 to disable)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--config", type=str, help="Path to config YAML")
    mode_group.add_argument(
        "--fast",
        action="store_true",
        help="Disable FFT-heavy analysis for quick, deterministic runs",
    )
    args = parser.parse_args()

    if args.signals <= 0 or args.scans <= 0:
        raise SystemExit("Signals and scans must be > 0")
    if args.missing_rate < 0.0 or args.missing_rate > 1.0:
        raise SystemExit("Missing rate must be between 0 and 1")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    run_bench(
        signals=args.signals,
        scans=args.scans,
        scan_interval=args.scan_interval,
        missing_rate=args.missing_rate,
        config_path=args.config,
        fast=args.fast,
        progress_interval=args.progress_interval,
    )


if __name__ == "__main__":
    main()
