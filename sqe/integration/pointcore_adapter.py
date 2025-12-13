"""
PointCore-Simulator Adapter

Integrates Signal Quality Engine with PointCore-Simulator.
Consumes analog points and provides wrapped Signal objects to SQE.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from sqe.core.engine import SignalQualityEngine, SignalConfig


@dataclass
class PointCoreSignal:
    """Wrapper for PointCore analog point."""
    point_id: str
    point_type: str      # "AI" for analog input
    value: Optional[float]
    timestamp: float
    quality: str         # "GOOD", "BAD", "UNCERTAIN"
    address: str         # Point address in simulator


class PointCoreAdapter:
    """
    Adapter for PointCore-Simulator integration.

    Maps PointCore analog points to SQE signal processing.
    """

    def __init__(self, engine: SignalQualityEngine):
        """
        Initialize PointCore adapter.

        Args:
            engine: SignalQualityEngine instance
        """
        self.engine = engine
        self.point_mapping: Dict[str, str] = {}  # point_id -> signal_id
        self.point_configs: Dict[str, SignalConfig] = {}

    def register_point(
        self,
        point_id: str,
        signal_config: Optional[SignalConfig] = None
    ) -> None:
        """
        Register a PointCore point for SQE processing.

        Args:
            point_id: PointCore point identifier
            signal_config: Optional custom signal configuration
        """
        # Use point_id as signal_id by default
        signal_id = point_id

        # Store mapping
        self.point_mapping[point_id] = signal_id

        # Register with engine
        self.engine.register_signal(signal_id, signal_config)

        if signal_config:
            self.point_configs[point_id] = signal_config

    def process_point(self, point: PointCoreSignal) -> Optional[Dict]:
        """
        Process a single PointCore point through SQE.

        Args:
            point: PointCoreSignal from simulator

        Returns:
            Processed signal dictionary or None
        """
        if point.point_id not in self.point_mapping:
            # Auto-register unknown points
            self.register_point(point.point_id)

        signal_id = self.point_mapping[point.point_id]

        # Convert quality to value (None for BAD quality)
        value = point.value if point.quality == "GOOD" else None

        # Process through engine
        result = self.engine.update_single(signal_id, value)

        if result:
            return result.to_dict()
        return None

    def process_scan(self, points: List[PointCoreSignal]) -> Dict[str, Dict]:
        """
        Process a complete scan of PointCore points.

        Args:
            points: List of PointCoreSignal objects

        Returns:
            Dictionary mapping point_id to processed results
        """
        # Build signals dictionary
        signals = {}
        for point in points:
            if point.point_id not in self.point_mapping:
                self.register_point(point.point_id)

            signal_id = self.point_mapping[point.point_id]
            value = point.value if point.quality == "GOOD" else None
            signals[signal_id] = value

        # Process through engine
        results = self.engine.update(signals)

        # Convert to dictionaries
        return {
            point_id: result.to_dict()
            for point_id, result in results.items()
        }

    def from_simulator_data(self, simulator_data: Dict[str, Any]) -> List[PointCoreSignal]:
        """
        Convert PointCore simulator data format to PointCoreSignal objects.

        Args:
            simulator_data: Dictionary from PointCore-Simulator

        Returns:
            List of PointCoreSignal objects

        Example simulator_data format:
        {
            "AI_001": {"value": 42.5, "quality": "GOOD", "timestamp": 1234567890.0},
            "AI_002": {"value": 100.2, "quality": "GOOD", "timestamp": 1234567890.0}
        }
        """
        signals = []

        for point_id, data in simulator_data.items():
            signal = PointCoreSignal(
                point_id=point_id,
                point_type="AI",  # Assume analog input
                value=data.get("value"),
                timestamp=data.get("timestamp", 0.0),
                quality=data.get("quality", "GOOD"),
                address=data.get("address", point_id)
            )
            signals.append(signal)

        return signals

    def get_point_stats(self, point_id: str) -> Dict:
        """
        Get statistics for a specific PointCore point.

        Args:
            point_id: Point identifier

        Returns:
            Statistics dictionary
        """
        if point_id not in self.point_mapping:
            raise ValueError(f"Point {point_id} not registered")

        signal_id = self.point_mapping[point_id]
        return self.engine.get_signal_stats(signal_id)

    def get_all_point_stats(self) -> Dict[str, Dict]:
        """
        Get statistics for all registered points.

        Returns:
            Dictionary mapping point_id to statistics
        """
        return {
            point_id: self.get_point_stats(point_id)
            for point_id in self.point_mapping.keys()
        }
