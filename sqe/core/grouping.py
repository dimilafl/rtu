"""Signal grouping configuration and resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class GroupDefinition:
    group_id: str
    signal_ids: List[str]


@dataclass(frozen=True)
class GroupingConfig:
    mode: str
    prefix_delimiter: str = "_"
    prefix_depth: int = 2
    explicit_groups: List[GroupDefinition] = field(default_factory=list)
    min_members_for_group_incident: int = 2
    min_fraction_for_group_incident: float = 0.5
    persistence_scans: int = 2
    resolve_persistence_scans: int = 2


class GroupResolver:
    """Resolve group identifiers from signal ids."""

    def __init__(self, cfg: GroupingConfig) -> None:
        self.cfg = cfg
        self._membership: Dict[str, str] = {}
        if cfg.mode == "explicit":
            for group in cfg.explicit_groups:
                for signal_id in group.signal_ids:
                    if signal_id not in self._membership:
                        self._membership[signal_id] = group.group_id

    def resolve_group_id(
        self,
        signal_id: str,
        cfg: Optional[GroupingConfig] = None,
    ) -> Optional[str]:
        active_cfg = cfg or self.cfg
        if active_cfg.mode == "prefix":
            tokens = signal_id.split(active_cfg.prefix_delimiter)
            if len(tokens) < active_cfg.prefix_depth:
                return None
            return active_cfg.prefix_delimiter.join(tokens[: active_cfg.prefix_depth])
        if active_cfg.mode == "explicit":
            return self._membership.get(signal_id)
        return None
