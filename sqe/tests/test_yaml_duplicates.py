from pathlib import Path

import pytest

from sqe.config.loader import ConfigError, load_config, load_groups_config


def test_load_config_rejects_duplicate_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "dupe.yaml"
    cfg.write_text("engine:\n  scan_interval: 0.1\nengine:\n  auto_register: true\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(str(cfg))

    message = str(exc_info.value)
    assert "Invalid YAML" in message
    assert "found duplicate key 'engine'" in message


def test_load_groups_config_rejects_duplicate_keys(tmp_path: Path) -> None:
    groups = tmp_path / "groups.yaml"
    groups.write_text("group_a:\n  members: []\ngroup_a:\n  members: [s1]\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_groups_config(str(groups))

    message = str(exc_info.value)
    assert "Invalid YAML" in message
    assert "found duplicate key 'group_a'" in message


def test_repo_owned_yaml_loads_cleanly() -> None:
    config = load_config()
    assert isinstance(config, dict)

    vectors_dir = Path(__file__).resolve().parents[1] / "vectors"
    groups_cfg = load_groups_config(str(vectors_dir / "groups.yaml"))
    vectors_cfg = load_config(str(vectors_dir / "cfg.yaml"))

    assert isinstance(groups_cfg, dict)
    assert isinstance(vectors_cfg, dict)
