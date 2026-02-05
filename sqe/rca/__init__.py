"""Root Cause Analysis module for topology-aware fault localization."""

from sqe.rca.schema import (
    NodeEvidence,
    RootCauseCandidate,
    TroubleshootReport,
    OverallState,
    LeafObservation,
    SCHEMA_VERSION,
)
from sqe.rca.evidence import (
    build_leaf_observations,
    aggregate_node_evidence,
    select_representative_signals,
)
from sqe.rca.state import RCAState
from sqe.rca.scoring import (
    ScoringConfig,
    score_candidates,
    get_default_scoring_config,
    get_primary_and_secondary,
    filter_candidates_by_threshold,
)
from sqe.rca.confidence import (
    ConfidenceConfig,
    compute_confidence,
    compute_all_confidences,
    get_default_confidence_config,
    get_confidence_assessment,
)
from sqe.rca.engine import (
    RCAEngine,
    create_rca_engine_from_config,
)
from sqe.rca.node_incidents import (
    NodeIncident,
    NodeIncidentConfig,
    NodeIncidentTracker,
    get_default_incident_config,
)

__all__ = [
    "NodeEvidence",
    "RootCauseCandidate",
    "TroubleshootReport",
    "OverallState",
    "LeafObservation",
    "SCHEMA_VERSION",
    "build_leaf_observations",
    "aggregate_node_evidence",
    "select_representative_signals",
    "RCAState",
    "ScoringConfig",
    "score_candidates",
    "get_default_scoring_config",
    "get_primary_and_secondary",
    "filter_candidates_by_threshold",
    "ConfidenceConfig",
    "compute_confidence",
    "compute_all_confidences",
    "get_default_confidence_config",
    "get_confidence_assessment",
    "RCAEngine",
    "create_rca_engine_from_config",
    "NodeIncident",
    "NodeIncidentConfig",
    "NodeIncidentTracker",
    "get_default_incident_config",
]
