"""RCA state management for tracking onset and stability.

Maintains minimal per-signal and per-node rolling state for deterministic
root cause analysis. Includes retention policy for memory management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class SignalState:
    """State for a single signal.

    Attributes:
        is_affected: Whether signal is currently affected
        onset_scan: Scan index when signal became affected
        last_seen_scan: Last scan where signal was processed
        last_cause: Last known cause
        last_quality_class: Last known quality class
    """

    is_affected: bool = False
    onset_scan: Optional[int] = None
    last_seen_scan: int = 0
    last_cause: Optional[str] = None
    last_quality_class: str = "GOOD"


@dataclass
class CandidateStability:
    """Stability tracking for a root cause candidate.

    Attributes:
        node_id: Node identifier
        consecutive_above_threshold: Scans above confidence threshold
        last_score: Last computed score
        last_confidence: Last computed confidence
    """

    node_id: str
    consecutive_above_threshold: int = 0
    last_score: float = 0.0
    last_confidence: float = 0.0


class RCAState:
    """Rolling state for root cause analysis.

    Maintains deterministic state that can be:
    - Serialized for replay
    - Pruned for memory management
    - Reset for new analysis sessions

    Attributes:
        signal_states: Per-signal state tracking
        candidate_stability: Per-candidate stability tracking
        retention_scans: Number of scans before pruning inactive signals
        current_scan: Current scan index
    """

    def __init__(self, retention_scans: int = 2000) -> None:
        """Initialize RCA state.

        Args:
            retention_scans: Scans before pruning inactive signal state
        """
        self.retention_scans = retention_scans
        self.current_scan: int = 0
        self._signal_states: Dict[str, SignalState] = {}
        self._candidate_stability: Dict[str, CandidateStability] = {}
        self._active_signals: Set[str] = set()

    def advance_scan(self, scan_index: int) -> None:
        """Advance to a new scan index.

        Args:
            scan_index: New scan index
        """
        self.current_scan = scan_index

    def update_signal(
        self,
        signal_id: str,
        is_affected: bool,
        cause: Optional[str] = None,
        quality_class: str = "GOOD",
    ) -> Optional[int]:
        """Update signal state and return onset scan.

        Args:
            signal_id: Signal identifier
            is_affected: Whether signal is affected this scan
            cause: Cause of issue if affected
            quality_class: Quality class

        Returns:
            Onset scan index if signal is affected, None otherwise
        """
        self._active_signals.add(signal_id)

        if signal_id not in self._signal_states:
            self._signal_states[signal_id] = SignalState()

        state = self._signal_states[signal_id]
        state.last_seen_scan = self.current_scan
        state.last_cause = cause
        state.last_quality_class = quality_class

        if is_affected:
            if not state.is_affected:
                # Transition to affected - record onset
                state.onset_scan = self.current_scan
            state.is_affected = True
            return state.onset_scan
        else:
            # Clear affected state
            state.is_affected = False
            state.onset_scan = None
            return None

    def get_signal_onset(self, signal_id: str) -> Optional[int]:
        """Get onset scan for a signal.

        Args:
            signal_id: Signal identifier

        Returns:
            Onset scan index or None if not affected
        """
        state = self._signal_states.get(signal_id)
        if state and state.is_affected:
            return state.onset_scan
        return None

    def get_signal_state(self, signal_id: str) -> Optional[SignalState]:
        """Get full state for a signal.

        Args:
            signal_id: Signal identifier

        Returns:
            SignalState or None if not tracked
        """
        return self._signal_states.get(signal_id)

    def update_candidate_stability(
        self,
        node_id: str,
        score: float,
        confidence: float,
        min_confidence: float,
    ) -> int:
        """Update stability tracking for a candidate.

        Args:
            node_id: Node identifier
            score: Current score
            confidence: Current confidence
            min_confidence: Threshold for "above threshold"

        Returns:
            Consecutive scans above threshold
        """
        if node_id not in self._candidate_stability:
            self._candidate_stability[node_id] = CandidateStability(node_id=node_id)

        stability = self._candidate_stability[node_id]
        stability.last_score = score
        stability.last_confidence = confidence

        if confidence >= min_confidence:
            stability.consecutive_above_threshold += 1
        else:
            stability.consecutive_above_threshold = 0

        return stability.consecutive_above_threshold

    def get_candidate_stability(self, node_id: str) -> Optional[CandidateStability]:
        """Get stability tracking for a candidate.

        Args:
            node_id: Node identifier

        Returns:
            CandidateStability or None if not tracked
        """
        return self._candidate_stability.get(node_id)

    def reset_candidate_stability(self, node_id: str) -> None:
        """Reset stability tracking for a candidate.

        Args:
            node_id: Node identifier
        """
        if node_id in self._candidate_stability:
            self._candidate_stability[node_id].consecutive_above_threshold = 0

    def prune_inactive(self) -> int:
        """Prune state for signals not seen in retention window.

        Returns:
            Number of signals pruned
        """
        cutoff = self.current_scan - self.retention_scans
        to_prune = [
            signal_id
            for signal_id, state in self._signal_states.items()
            if state.last_seen_scan < cutoff
        ]

        for signal_id in to_prune:
            del self._signal_states[signal_id]
            self._active_signals.discard(signal_id)

        return len(to_prune)

    def prune_candidates(self, active_node_ids: Set[str]) -> int:
        """Prune stability tracking for inactive candidates.

        Args:
            active_node_ids: Set of currently active node IDs

        Returns:
            Number of candidates pruned
        """
        to_prune = [
            node_id
            for node_id in self._candidate_stability
            if node_id not in active_node_ids
        ]

        for node_id in to_prune:
            del self._candidate_stability[node_id]

        return len(to_prune)

    def reset(self) -> None:
        """Reset all state."""
        self.current_scan = 0
        self._signal_states.clear()
        self._candidate_stability.clear()
        self._active_signals.clear()

    @property
    def signal_count(self) -> int:
        """Number of tracked signals."""
        return len(self._signal_states)

    @property
    def candidate_count(self) -> int:
        """Number of tracked candidates."""
        return len(self._candidate_stability)

    def get_affected_signals(self) -> Set[str]:
        """Get set of currently affected signal IDs."""
        return {
            signal_id
            for signal_id, state in self._signal_states.items()
            if state.is_affected
        }

    def to_dict(self) -> Dict:
        """Serialize state to dictionary for persistence."""
        return {
            "current_scan": self.current_scan,
            "retention_scans": self.retention_scans,
            "signal_states": {
                signal_id: {
                    "is_affected": state.is_affected,
                    "onset_scan": state.onset_scan,
                    "last_seen_scan": state.last_seen_scan,
                    "last_cause": state.last_cause,
                    "last_quality_class": state.last_quality_class,
                }
                for signal_id, state in sorted(self._signal_states.items())
            },
            "candidate_stability": {
                node_id: {
                    "consecutive_above_threshold": stab.consecutive_above_threshold,
                    "last_score": stab.last_score,
                    "last_confidence": stab.last_confidence,
                }
                for node_id, stab in sorted(self._candidate_stability.items())
            },
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "RCAState":
        """Restore state from dictionary."""
        state = cls(retention_scans=data.get("retention_scans", 2000))
        state.current_scan = data.get("current_scan", 0)

        for signal_id, sig_data in data.get("signal_states", {}).items():
            sig_state = SignalState(
                is_affected=sig_data.get("is_affected", False),
                onset_scan=sig_data.get("onset_scan"),
                last_seen_scan=sig_data.get("last_seen_scan", 0),
                last_cause=sig_data.get("last_cause"),
                last_quality_class=sig_data.get("last_quality_class", "GOOD"),
            )
            state._signal_states[signal_id] = sig_state
            if sig_state.is_affected:
                state._active_signals.add(signal_id)

        for node_id, stab_data in data.get("candidate_stability", {}).items():
            state._candidate_stability[node_id] = CandidateStability(
                node_id=node_id,
                consecutive_above_threshold=stab_data.get("consecutive_above_threshold", 0),
                last_score=stab_data.get("last_score", 0.0),
                last_confidence=stab_data.get("last_confidence", 0.0),
            )

        return state
