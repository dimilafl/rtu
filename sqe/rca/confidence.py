"""Confidence computation for root cause candidates.

Deterministic confidence scoring based on:
- Normalized score within type
- Margin over runner-up
- Stability across scans
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqe.rca.schema import RootCauseCandidate
from sqe.rca.state import RCAState


@dataclass
class ConfidenceConfig:
    """Configuration for confidence computation.

    Attributes:
        required_scans: Scans above threshold for stability term
        margin_scale: Scale factor for margin term
        stability_weight: Weight for stability component
        margin_weight: Weight for margin component
        score_weight: Weight for normalized score component
    """

    required_scans: int = 2
    margin_scale: float = 0.2
    stability_weight: float = 0.3
    margin_weight: float = 0.3
    score_weight: float = 0.4


def get_default_confidence_config() -> ConfidenceConfig:
    """Get default confidence configuration."""
    return ConfidenceConfig()


def compute_confidence(
    candidate: RootCauseCandidate,
    runner_up: Optional[RootCauseCandidate],
    state: RCAState,
    config: ConfidenceConfig,
    *,
    min_confidence_threshold: float = 0.0,
) -> float:
    """Compute confidence for a candidate.

    Confidence combines:
    - Normalized score (how high is the score vs expected range)
    - Margin (how much higher than runner-up)
    - Stability (how long has this been the top candidate)

    Args:
        candidate: The candidate to compute confidence for
        runner_up: Second-place candidate (if any)
        state: RCA state for stability tracking
        config: Confidence configuration
        min_confidence_threshold: Threshold for stability tracking

    Returns:
        Confidence value in [0, 1]
    """
    # Score component: candidate.score is already normalized to [0, 1]
    score_term = candidate.score

    # Margin component: (score - runner_up_score) / margin_scale
    if runner_up is not None:
        margin = candidate.score - runner_up.score
        margin_term = min(1.0, max(0.0, margin / config.margin_scale))
    else:
        # No runner-up means this candidate is uncontested
        margin_term = 1.0

    # Stability component: consecutive scans above threshold / required_scans
    stability = state.get_candidate_stability(candidate.node_id)
    if stability is not None:
        consecutive = stability.consecutive_above_threshold
        stability_term = min(1.0, consecutive / config.required_scans)
    else:
        stability_term = 0.0

    # Combine components
    confidence = (
        config.score_weight * score_term +
        config.margin_weight * margin_term +
        config.stability_weight * stability_term
    )

    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, confidence))

    # Update stability tracking
    state.update_candidate_stability(
        candidate.node_id,
        candidate.score,
        confidence,
        min_confidence_threshold,
    )

    return confidence


def compute_all_confidences(
    candidates: List[RootCauseCandidate],
    state: RCAState,
    config: ConfidenceConfig,
    *,
    min_confidence_threshold: float = 0.0,
) -> List[RootCauseCandidate]:
    """Compute confidence for all candidates.

    Modifies candidates in place and returns the list.

    Args:
        candidates: List of candidates (sorted by score descending)
        state: RCA state
        config: Confidence configuration
        min_confidence_threshold: Threshold for stability tracking

    Returns:
        Same list with confidence values filled in
    """
    if not candidates:
        return candidates

    # Track which nodes are active for pruning later
    active_nodes = {c.node_id for c in candidates}
    state.prune_candidates(active_nodes)

    for i, candidate in enumerate(candidates):
        # Runner-up is next candidate if exists
        runner_up = candidates[i + 1] if i + 1 < len(candidates) else None

        confidence = compute_confidence(
            candidate,
            runner_up,
            state,
            config,
            min_confidence_threshold=min_confidence_threshold,
        )
        # Update candidate confidence
        candidate.confidence = confidence

    return candidates


def reset_non_top_stability(
    candidates: List[RootCauseCandidate],
    state: RCAState,
    keep_top_n: int = 3,
) -> None:
    """Reset stability for candidates not in top N.

    This prevents lower-ranked candidates from accumulating stability
    that would carry over if they later become top candidates.

    Args:
        candidates: List of candidates (sorted by score descending)
        state: RCA state
        keep_top_n: Number of top candidates to keep stability for
    """
    for i, candidate in enumerate(candidates):
        if i >= keep_top_n:
            state.reset_candidate_stability(candidate.node_id)


def get_confidence_assessment(confidence: float) -> str:
    """Get human-readable confidence assessment.

    Args:
        confidence: Confidence value in [0, 1]

    Returns:
        Assessment string
    """
    if confidence >= 0.9:
        return "VERY_HIGH"
    elif confidence >= 0.75:
        return "HIGH"
    elif confidence >= 0.5:
        return "MODERATE"
    elif confidence >= 0.25:
        return "LOW"
    else:
        return "VERY_LOW"
