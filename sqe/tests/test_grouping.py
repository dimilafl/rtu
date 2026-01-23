"""Tests for grouping configuration and resolver."""

from sqe.core.grouping import GroupDefinition, GroupResolver, GroupingConfig


def test_prefix_grouping_resolves_with_depth():
    config = GroupingConfig(mode="prefix", prefix_delimiter="_", prefix_depth=2)
    resolver = GroupResolver(config)

    assert resolver.resolve_group_id("STATION_01_AI_001") == "STATION_01"
    config_three = GroupingConfig(mode="prefix", prefix_delimiter="_", prefix_depth=3)
    resolver_three = GroupResolver(config_three)

    assert resolver_three.resolve_group_id("STATION_01_AI_001") == "STATION_01_AI"


def test_explicit_grouping_membership_is_deterministic():
    config = GroupingConfig(
        mode="explicit",
        explicit_groups=[
            GroupDefinition(group_id="station_a", signal_ids=["A1", "A2"]),
            GroupDefinition(group_id="station_b", signal_ids=["B1"]),
        ],
    )
    resolver = GroupResolver(config)

    assert resolver.resolve_group_id("A1") == "station_a"
    assert resolver.resolve_group_id("A2") == "station_a"
    assert resolver.resolve_group_id("B1") == "station_b"
    assert resolver.resolve_group_id("C1") is None
