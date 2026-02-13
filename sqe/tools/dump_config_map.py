"""Dump deterministic flattened configuration keys and values."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqe.config.loader import load_config, load_groups_config


def _flatten(config: Dict[str, Any], prefix: str = "") -> List[Tuple[str, Any]]:
    items: List[Tuple[str, Any]] = []
    for key in sorted(config.keys()):
        value = config[key]
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.extend(_flatten(value, dotted))
        else:
            items.append((dotted, value))
    return items


def _format_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def render_flattened_config(
    main_config: Dict[str, Any],
    groups_config: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = ["[main]"]
    lines.extend(f"{key}={_format_value(value)}" for key, value in _flatten(main_config))

    if groups_config is not None:
        lines.append("")
        lines.append("[groups]")
        lines.extend(
            f"{key}={_format_value(value)}" for key, value in _flatten(groups_config)
        )

    return "\n".join(lines) + "\n"


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump flattened config keys and values in deterministic order."
    )
    parser.add_argument(
        "--config",
        help="Optional main config override path (merged with defaults)",
    )
    parser.add_argument(
        "--groups-config",
        help="Optional groups config path loaded via load_groups_config",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    main_config = load_config(args.config)
    groups_config = load_groups_config(args.groups_config) if args.groups_config else None
    print(render_flattened_config(main_config, groups_config), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
