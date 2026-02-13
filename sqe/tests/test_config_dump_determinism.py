from sqe.config.loader import load_config
from sqe.tools.dump_config_map import render_flattened_config


def test_render_flattened_config_is_deterministic() -> None:
    config = load_config()
    output_one = render_flattened_config(config)
    output_two = render_flattened_config(config)

    assert output_one == output_two
