"""Test minimi del setup logging (senza mutare il root logger globale)."""

from app import config, logging_setup


def test_log_path_under_config_dir():
    p = logging_setup.log_path()
    assert p.name == "sonora.log"
    assert p.parent == config.config_dir()
