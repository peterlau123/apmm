"""Tests for Phase 5.1: pre-flight vLLM branch check."""
import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "check_vllm_branch.py"


def _load():
    spec = importlib.util.spec_from_file_location("ut_check_vllm_branch", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cvb = _load()


def test_ensure_on_branch_match_does_not_raise():
    fake = mock.Mock(return_value={"exit_code": 0, "stdout": "2.5.1_ut_verify\n", "stderr": ""})
    with mock.patch.object(cvb, "run_remote", fake):
        cvb.ensure_on_branch("2.5.1_ut_verify", "/gpfs/gcsp/M2.7_verify/vllm")
    fake.assert_called_once()
    cmd = fake.call_args[0][0]
    assert "git rev-parse --abbrev-ref HEAD" in cmd
    assert "/gpfs/gcsp/M2.7_verify/vllm" in cmd


def test_ensure_on_branch_mismatch_raises():
    fake = mock.Mock(return_value={"exit_code": 0, "stdout": "master\n", "stderr": ""})
    with mock.patch.object(cvb, "run_remote", fake):
        with pytest.raises(RuntimeError, match="HEAD on master"):
            cvb.ensure_on_branch("2.5.1_ut_verify", "/gpfs/gcsp/M2.7_verify/vllm")


def test_ensure_on_branch_nonzero_rc_raises():
    fake = mock.Mock(return_value={"exit_code": 128, "stdout": "", "stderr": "fatal: not a git repo"})
    with mock.patch.object(cvb, "run_remote", fake):
        with pytest.raises(RuntimeError, match="Failed to read vLLM HEAD"):
            cvb.ensure_on_branch("2.5.1_ut_verify", "/gpfs/gcsp/M2.7_verify/vllm")
