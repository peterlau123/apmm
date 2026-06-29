"""Tests for load_deployment_config.py"""
import pytest
from pathlib import Path
from tasks.ut.scripts.load_deployment_config import load_deployment_config, PROJECT_ROOT


def test_load_production_config():
    result = load_deployment_config(env="production")
    expected = PROJECT_ROOT / "tasks/ut/deployment/production/config/workflow.yaml"
    assert result == expected
    assert result.exists()


def test_load_test_config_l2():
    result = load_deployment_config(env="test", level=2)
    expected = PROJECT_ROOT / "tests/ut/integration/fixtures/workflow.l2.yaml"
    assert result == expected
    assert result.exists()


def test_load_test_config_invalid_level():
    with pytest.raises(ValueError) as exc_info:
        load_deployment_config(env="test", level=5)
    assert "level 1-4" in str(exc_info.value)


def test_load_invalid_env():
    with pytest.raises(ValueError) as exc_info:
        load_deployment_config(env="staging")
    assert "Invalid env" in str(exc_info.value)