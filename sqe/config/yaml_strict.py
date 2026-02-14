"""Strict YAML loading helpers with duplicate-key detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, TextIO, Union

import yaml


class NoDuplicateSafeLoader(yaml.SafeLoader):
    """YAML SafeLoader variant that rejects duplicate mapping keys."""



def _construct_mapping_no_dupes(
    loader: NoDuplicateSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> Dict[str, Any]:
    loader.flatten_mapping(node)
    mapping: Dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            line = key_node.start_mark.line + 1
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key '{key}' at line {line}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


NoDuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_dupes,
)


PathOrStream = Union[Path, TextIO]


def load_yaml_no_dupes(path_or_stream: PathOrStream) -> Dict[str, Any]:
    """Load YAML into a mapping while rejecting duplicate keys."""
    if isinstance(path_or_stream, Path):
        with path_or_stream.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=NoDuplicateSafeLoader)
    else:
        data = yaml.load(path_or_stream, Loader=NoDuplicateSafeLoader)

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError("Top-level YAML must be a mapping")
    return data
