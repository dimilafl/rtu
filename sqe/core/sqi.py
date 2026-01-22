"""
Signal Quality Index (SQI) Calculator

Computes a weighted composite metric of signal quality based on:
- Noise level (variance)
- Drift rate
- Spike frequency
- Oscillation energy
- Missing sample ratio

Output range: 0-100 (100 = perfect quality)
"""

from typing import Dict, Optional
from dataclasses import dataclass
import numpy as np


@dataclass
class SQIWeights:
    """Weight configuration for SQI components."""
    noise: float = 0.25        # Weight for noise level
    drift: float = 0.25        # Weight for drift rate
    spikes: float = 0.20       # Weight for spike frequency
    oscillation: float = 0.15  # Weight for oscillation energy
    missing: float = 0.15      # Weight for missing samples

    def normalize(self) -> 'SQIWeights':
        """Normalize weights to sum to 1.0."""
        total = self.noise + self.drift + self.spikes + self.oscillation + self.missing
        if total == 0:
            raise ValueError("SQI weights must sum to a positive value.")
        return SQIWeights(
            noise=self.noise / total,
            drift=self.drift / total,
            spikes=self.spikes / total,
            oscillation=self.oscillation / total,
            missing=self.missing / total
        )


@dataclass
class SQIComponents:
    """Individual quality scores for each component."""
    noise_score: float          # 0-100
    drift_score: float          # 0-100
    spike_score: float          # 0-100
    oscillation_score: float    # 0-100
    missing_score: float        # 0-100


class SignalQualityIndex:
    """
    Calculates overall signal quality index.

    Combines multiple quality metrics into a single 0-100 score
    where 100 represents perfect signal quality.
    """

    def __init__(
        self,
        weights: Optional[SQIWeights] = None,
        noise_threshold: float = 0.1,
        drift_threshold: float = 1.0,
        spike_threshold: float = 0.05,
        oscillation_threshold: float = 0.3
    ):
        """
        Initialize SQI calculator.

        Args:
            weights: Component weights (normalized automatically)
            noise_threshold: Noise level for 0 quality score
            drift_threshold: Drift rate for 0 quality score
            spike_threshold: Spike frequency for 0 quality score
            oscillation_threshold: Oscillation energy for 0 quality score
        """
        thresholds = {
            "noise_threshold": noise_threshold,
            "drift_threshold": drift_threshold,
            "spike_threshold": spike_threshold,
            "oscillation_threshold": oscillation_threshold,
        }
        invalid_thresholds = [
            f"{name}={value}"
            for name, value in thresholds.items()
            if value <= 0
        ]
        if invalid_thresholds:
            joined_thresholds = ", ".join(invalid_thresholds)
            raise ValueError(
                "Invalid thresholds (must be > 0): "
                f"{joined_thresholds}"
            )
        self.weights = (weights or SQIWeights()).normalize()
        self.noise_threshold = noise_threshold
        self.drift_threshold = drift_threshold
        self.spike_threshold = spike_threshold
        self.oscillation_threshold = oscillation_threshold

        # Running statistics for adaptive thresholds
        self.sample_count = 0
        self.sqi_history = []

    def calculate(
        self,
        noise_level: float,
        drift_rate: float,
        spike_frequency: float,
        oscillation_energy: float,
        missing_ratio: float
    ) -> Dict:
        """
        Calculate signal quality index.

        Args:
            noise_level: Current noise level (coefficient of variation)
            drift_rate: Absolute drift rate
            spike_frequency: Ratio of spikes to total samples
            oscillation_energy: Total oscillation energy
            missing_ratio: Ratio of missing samples

        Returns:
            Dictionary with SQI score and component breakdown
        """
        # Calculate individual component scores (0-100)
        components = self._calculate_components(
            noise_level,
            drift_rate,
            spike_frequency,
            oscillation_energy,
            missing_ratio
        )

        # Calculate weighted composite SQI
        sqi = (
            components.noise_score * self.weights.noise +
            components.drift_score * self.weights.drift +
            components.spike_score * self.weights.spikes +
            components.oscillation_score * self.weights.oscillation +
            components.missing_score * self.weights.missing
        )

        # Ensure in range [0, 100]
        sqi = np.clip(sqi, 0, 100)

        # Update history
        self.sample_count += 1
        self.sqi_history.append(sqi)
        if len(self.sqi_history) > 100:
            self.sqi_history = self.sqi_history[-100:]

        # Calculate trend
        trend = self._calculate_trend()

        # Classify quality
        quality_class = self._classify_quality(sqi)

        return {
            "sqi": float(sqi),
            "quality_class": quality_class,
            "trend": trend,
            "components": {
                "noise": components.noise_score,
                "drift": components.drift_score,
                "spikes": components.spike_score,
                "oscillation": components.oscillation_score,
                "missing": components.missing_score
            },
            "weights": {
                "noise": self.weights.noise,
                "drift": self.weights.drift,
                "spikes": self.weights.spikes,
                "oscillation": self.weights.oscillation,
                "missing": self.weights.missing
            }
        }

    def _calculate_components(
        self,
        noise_level: float,
        drift_rate: float,
        spike_frequency: float,
        oscillation_energy: float,
        missing_ratio: float
    ) -> SQIComponents:
        """
        Calculate individual component scores.

        Each score is 0-100, where 100 is perfect.
        """
        # Noise score: decreases with increasing noise
        noise_score = 100 * np.exp(-noise_level / self.noise_threshold)

        # Drift score: decreases with increasing drift
        drift_score = 100 * np.exp(-abs(drift_rate) / self.drift_threshold)

        # Spike score: decreases with spike frequency
        spike_score = 100 * (1 - min(spike_frequency / self.spike_threshold, 1.0))

        # Oscillation score: decreases with oscillation energy
        oscillation_score = 100 * np.exp(-oscillation_energy / self.oscillation_threshold)

        # Missing score: linear decrease with missing ratio
        missing_score = 100 * (1 - missing_ratio)

        return SQIComponents(
            noise_score=float(noise_score),
            drift_score=float(drift_score),
            spike_score=float(spike_score),
            oscillation_score=float(oscillation_score),
            missing_score=float(missing_score)
        )

    def _calculate_trend(self) -> str:
        """
        Calculate SQI trend over recent history.

        Returns:
            "improving", "degrading", or "stable"
        """
        if len(self.sqi_history) < 10:
            return "stable"

        recent = self.sqi_history[-10:]
        first_half = np.mean(recent[:5])
        second_half = np.mean(recent[5:])

        diff = second_half - first_half

        if diff > 5:
            return "improving"
        elif diff < -5:
            return "degrading"
        else:
            return "stable"

    def _classify_quality(self, sqi: float) -> str:
        """
        Classify signal quality based on SQI score.

        Args:
            sqi: Signal quality index (0-100)

        Returns:
            Quality classification string
        """
        if sqi >= 90:
            return "excellent"
        elif sqi >= 75:
            return "good"
        elif sqi >= 50:
            return "fair"
        elif sqi >= 25:
            return "poor"
        else:
            return "critical"

    def get_statistics(self) -> Dict:
        """
        Get SQI statistics over history.

        Returns:
            Dictionary with mean, min, max SQI
        """
        if not self.sqi_history:
            return {
                "mean_sqi": 0.0,
                "min_sqi": 0.0,
                "max_sqi": 0.0,
                "current_sqi": 0.0
            }

        return {
            "mean_sqi": float(np.mean(self.sqi_history)),
            "min_sqi": float(np.min(self.sqi_history)),
            "max_sqi": float(np.max(self.sqi_history)),
            "current_sqi": float(self.sqi_history[-1])
        }

    def reset(self) -> None:
        """Reset SQI calculator state."""
        self.sample_count = 0
        self.sqi_history = []
