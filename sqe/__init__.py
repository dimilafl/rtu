"""
Signal-Quality Engine (SQE) for SCADA Simulation Stack

A DSP-style conditioning and diagnostics engine for telemetry signals
from simulated RTUs in SCADA systems.
"""

__version__ = "1.0.0"

from sqe.core.engine import SignalQualityEngine
from sqe.core.sqi import SignalQualityIndex

__all__ = ["SignalQualityEngine", "SignalQualityIndex"]
