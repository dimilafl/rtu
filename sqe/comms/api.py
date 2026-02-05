"""API for deterministic comms capacity budgeting."""

from __future__ import annotations

from typing import Dict, List, Tuple

from sqe.comms.budget import BudgetConfig, UtilizationStatus, compute_utilization_status
from sqe.comms.schema import CommsAggregate
from sqe.comms.topology_index import CommsTopologyIndex
from sqe.topology.model import NodeType, TopologySnapshot


def _reference_scan(comms_aggregates: Dict[Tuple[str, str], CommsAggregate]) -> Tuple[int, float]:
    if not comms_aggregates:
        return 0, 0.0
    key = sorted(comms_aggregates.keys())[0]
    agg = comms_aggregates[key]
    return int(agg.scan_index), float(agg.scan_timestamp)


def build_utilization_statuses(
    snapshot: TopologySnapshot,
    comms_aggregates: Dict[Tuple[str, str], CommsAggregate],
    cfg: BudgetConfig,
) -> List[UtilizationStatus]:
    """Build utilization statuses in deterministic order."""
    index = CommsTopologyIndex(snapshot)
    statuses: List[UtilizationStatus] = []
    default_scan_index, default_scan_timestamp = _reference_scan(comms_aggregates)

    type_order = [
        ("COMMS_DOMAIN", NodeType.COMMS_DOMAIN),
        ("POLL_GROUP", NodeType.POLL_GROUP),
        ("RTU", NodeType.RTU),
    ]

    for node_type_label, node_type in type_order:
        node_ids = sorted(snapshot.get_nodes_by_type(node_type))
        for node_id in node_ids:
            aggregate = comms_aggregates.get((node_type_label, node_id))
            if aggregate is None:
                scan_index = default_scan_index
                scan_timestamp = default_scan_timestamp
            else:
                scan_index = int(aggregate.scan_index)
                scan_timestamp = float(aggregate.scan_timestamp)

            statuses.append(
                compute_utilization_status(
                    node_type=node_type_label,
                    node_id=node_id,
                    scan_index=scan_index,
                    scan_timestamp=scan_timestamp,
                    descendant_signal_count=index.descendant_signal_count(node_id),
                    agg=aggregate,
                    cfg=cfg,
                )
            )

    return statuses
