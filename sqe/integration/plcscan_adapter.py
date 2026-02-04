"""
PLC_Scan_Engine Adapter

Integrates Signal Quality Engine with PLC_Scan_Engine.
Synchronizes SQE updates with PLC scan timing for deterministic execution.
"""

from typing import Dict, Optional, Callable, Any
import logging
import time

from sqe.core.engine import SignalQualityEngine


class PLCScanAdapter:
    """
    Adapter for PLC_Scan_Engine integration.

    Ensures SQE operates synchronously with PLC scan cycles.
    All processing is deterministic and sequential.
    """

    def __init__(
        self,
        engine: SignalQualityEngine,
        scan_interval: float = 0.1,
        warn_on_overrun: bool = True,
        logger: Optional[logging.Logger] = None,
        enable_callbacks: bool = True,
        track_performance: bool = True,
        max_scan_history: int = 100,
    ):
        """
        Initialize PLC scan adapter.

        Args:
            engine: SignalQualityEngine instance
            scan_interval: Target scan interval in seconds
        """
        self.engine = engine
        self.scan_interval = scan_interval
        self.warn_on_overrun = warn_on_overrun
        self.logger = logger or logging.getLogger(__name__)
        self.enable_callbacks = enable_callbacks
        self.track_performance = track_performance

        # Scan metrics
        self.scan_number = 0
        self.last_scan_time: Optional[float] = None
        self.scan_durations = []
        self.max_scan_history = max_scan_history
        self.error_count = 0
        self.last_error: Optional[str] = None
        self.overruns = 0

        # Callbacks
        self.pre_scan_callback: Optional[Callable] = None
        self.post_scan_callback: Optional[Callable] = None

    @classmethod
    def from_config(
        cls,
        engine: SignalQualityEngine,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ) -> "PLCScanAdapter":
        """Construct adapter from merged configuration dictionary."""
        integration = config.get("integration", {})
        plcscan = integration.get("plcscan", {})
        return cls(
            engine=engine,
            scan_interval=float(config.get("engine", {}).get("scan_interval", 0.1)),
            warn_on_overrun=bool(plcscan.get("warn_on_overrun", True)),
            logger=logger,
            enable_callbacks=bool(plcscan.get("enable_callbacks", True)),
            track_performance=bool(plcscan.get("track_performance", True)),
            max_scan_history=int(plcscan.get("max_scan_history", 100)),
        )

    def set_pre_scan_callback(self, callback: Callable[[int], None]) -> None:
        """
        Set callback to execute before each scan.

        Args:
            callback: Function that takes scan_number as argument
        """
        self.pre_scan_callback = callback

    def set_post_scan_callback(
        self,
        callback: Callable[[int, float, Dict], None]
    ) -> None:
        """
        Set callback to execute after each scan.

        Args:
            callback: Function that takes (scan_number, duration, results)
        """
        self.post_scan_callback = callback

    def execute_scan(
        self,
        signal_values: Dict[str, Optional[float]]
    ) -> Dict[str, Any]:
        """
        Execute one PLC scan cycle.

        This method should be called from PLC_Scan_Engine's scan loop.
        All processing is synchronous and deterministic.

        Args:
            signal_values: Dictionary of signal_id -> current value

        Returns:
            Dictionary with scan results and metrics
        """
        scan_start = time.time()
        perf_start = time.perf_counter()
        self.scan_number += 1

        # Pre-scan callback
        if self.enable_callbacks and self.pre_scan_callback:
            self.pre_scan_callback(self.scan_number)

        # Process all signals through SQE
        status = "ok"
        error = None
        try:
            processed_signals = self.engine.update(signal_values)
        except Exception as exc:
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            self.error_count += 1
            self.last_error = error
            processed_signals = {}

        # Calculate scan timing
        scan_end = time.time()
        perf_end = time.perf_counter()
        scan_duration = scan_end - scan_start
        elapsed = perf_end - perf_start

        # Track scan performance
        if self.track_performance:
            self.scan_durations.append(scan_duration)
            if len(self.scan_durations) > self.max_scan_history:
                self.scan_durations = self.scan_durations[-self.max_scan_history:]

        # Calculate timing metrics
        if self.last_scan_time is not None:
            actual_interval = scan_start - self.last_scan_time
        else:
            actual_interval = self.scan_interval

        self.last_scan_time = scan_start
        utilization = elapsed / self.scan_interval if self.scan_interval > 0 else 0.0
        overrun = max(0.0, elapsed - (self.scan_interval or 0.0))
        if overrun > 0:
            self.overruns += 1
            if self.warn_on_overrun and self.logger:
                self.logger.warning(
                    "scan overrun %.6fs utilization=%.3f", overrun, utilization
                )

        # Build scan result
        scan_result = {
            "scan_number": self.scan_number,
            "timestamp": scan_start,
            "scan_duration": scan_duration,
            "actual_interval": actual_interval,
            "target_interval": self.scan_interval,
            "timing_error": actual_interval - self.scan_interval,
            "utilization": utilization,
            "overrun": overrun,
            "overruns": self.overruns,
            "status": status,
            "error": error,
            "processed_signals": {
                sig_id: sig.to_dict()
                for sig_id, sig in processed_signals.items()
            },
            "signal_count": len(processed_signals)
        }

        # Post-scan callback
        if self.enable_callbacks and self.post_scan_callback:
            self.post_scan_callback(self.scan_number, scan_duration, scan_result)

        return scan_result

    def get_scan_performance(self) -> Dict:
        """
        Get scan performance statistics.

        Returns:
            Dictionary with timing statistics
        """
        if not self.scan_durations:
            return {
                "scans_executed": 0,
                "mean_duration": 0.0,
                "max_duration": 0.0,
                "min_duration": 0.0,
                "utilization": 0.0,
                "error_count": self.error_count,
                "last_error": self.last_error,
                "overruns": self.overruns,
            }

        mean_duration = sum(self.scan_durations) / len(self.scan_durations)
        max_duration = max(self.scan_durations)
        min_duration = min(self.scan_durations)
        utilization = mean_duration / self.scan_interval if self.scan_interval > 0 else 0

        return {
            "scans_executed": self.scan_number,
            "mean_duration": mean_duration,
            "max_duration": max_duration,
            "min_duration": min_duration,
            "utilization": utilization,
            "target_interval": self.scan_interval,
            "overruns": self.overruns,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }

    def check_scan_overrun(self, scan_duration: float) -> bool:
        """
        Check if scan exceeded target interval.

        Args:
            scan_duration: Duration of scan in seconds

        Returns:
            True if scan overrun occurred
        """
        return scan_duration > self.scan_interval

    def reset_metrics(self) -> None:
        """Reset scan performance metrics."""
        self.scan_number = 0
        self.last_scan_time = None
        self.scan_durations = []
        self.error_count = 0
        self.last_error = None
        self.overruns = 0


class ScanCycleController:
    """
    Controller for running SQE in a PLC-style scan loop.

    Provides a complete scan loop implementation for testing
    or standalone operation.
    """

    def __init__(
        self,
        adapter: PLCScanAdapter,
        data_source: Callable[[int], Dict[str, Optional[float]]]
    ):
        """
        Initialize scan cycle controller.

        Args:
            adapter: PLCScanAdapter instance
            data_source: Function that returns signal values for each scan
        """
        self.adapter = adapter
        self.data_source = data_source
        self.running = False

    def start(self, max_scans: Optional[int] = None) -> None:
        """
        Start scan loop.

        Args:
            max_scans: Maximum number of scans (None = run indefinitely)
        """
        self.running = True
        scan_count = 0

        while self.running:
            # Get signal data
            signal_values = self.data_source(scan_count)

            # Execute scan
            result = self.adapter.execute_scan(signal_values)

            # Check for overrun
            if self.adapter.check_scan_overrun(result["scan_duration"]):
                print(f"Warning: Scan {scan_count} overrun: {result['scan_duration']:.4f}s")

            scan_count += 1

            # Check max scans
            if max_scans and scan_count >= max_scans:
                break

            # Sleep to maintain scan interval
            sleep_time = self.adapter.scan_interval - result["scan_duration"]
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop(self) -> None:
        """Stop scan loop."""
        self.running = False
