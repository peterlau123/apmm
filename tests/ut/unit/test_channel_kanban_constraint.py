"""Channel × kanban interlock — `validate_required_config(cfg, channel=...)`.

Rules (locked in 2026-06-23):
  - channel="linear"  + kanban.enabled=true  → reject
  - channel="linear"  + kanban.enabled=false → accept
  - channel="hermes"  + kanban.enabled=true  → accept
  - channel="hermes"  + kanban.enabled=false → accept
  - default (omitted) → behaves as channel="hermes" (backward compat)
"""
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UT_RUNNER_PATH = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "ut_runner.py"


def _load_hr():
    sys.path.insert(0, str(UT_RUNNER_PATH.parent))
    sys.path.insert(0, str(UT_RUNNER_PATH.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("ut_runner", UT_RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hr = _load_hr()


def _good_base(kanban_enabled):
    return {
        "input_filter": {"test_list_path": "tests/foo.txt"},
        "config": {"remote_server": "t_h20"},
        "kanban": {"enabled": kanban_enabled},
    }


def test_linear_with_kanban_on_rejected():
    cfg = _good_base(True)
    ok, missing = hr.validate_required_config(cfg, channel="linear")
    assert ok is False
    assert any("kanban.enabled=true" in m for m in missing)


def test_linear_with_kanban_off_accepted():
    cfg = _good_base(False)
    ok, missing = hr.validate_required_config(cfg, channel="linear")
    assert ok is True
    assert missing == []


def test_hermes_with_kanban_on_accepted():
    cfg = _good_base(True)
    ok, missing = hr.validate_required_config(cfg, channel="hermes")
    assert ok is True
    assert missing == []


def test_hermes_with_kanban_off_accepted():
    cfg = _good_base(False)
    ok, missing = hr.validate_required_config(cfg, channel="hermes")
    assert ok is True
    assert missing == []


def test_default_channel_is_hermes_backward_compat():
    """旧 callers 不传 channel kwarg → 应表现为 hermes (允许 kanban=true)."""
    cfg = _good_base(True)
    ok, missing = hr.validate_required_config(cfg)
    assert ok is True
    assert missing == []


def test_linear_missing_other_fields_still_flags_kanban():
    """互锁错误与其他 missing 共存，互不掩盖。"""
    cfg = {"kanban": {"enabled": True}}  # 同时缺 input_filter + remote_server
    ok, missing = hr.validate_required_config(cfg, channel="linear")
    assert ok is False
    assert any("input_filter" in m for m in missing)
    assert any("remote_server" in m for m in missing)
    assert any("kanban.enabled=true" in m for m in missing)
