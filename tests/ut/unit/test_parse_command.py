"""Tests for parse_command Layer 1 regex set + Command dataclass.

Covers each of the 6 Layer-1 patterns plus edge cases that the v0 substring
matcher silently mishandled (e.g. "稍后结束这个" firing `stop`). Layer-2
LLM classification (P3) tests live in test_classify_intent.py.

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §4
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HR_PATH = PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "hermes_runner.py"


@pytest.fixture(scope="module")
def hr():
    spec = importlib.util.spec_from_file_location("hermes_runner", HR_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Command dataclass shape ────────────────────────────────────────────────


def test_command_dataclass_fields(hr):
    cmd = hr.parse_command("结束")
    assert isinstance(cmd, hr.Command)
    assert cmd.intent == "stop"
    assert cmd.confidence == 1.0
    assert cmd.args == {}
    assert cmd.source == "regex"
    assert cmd.raw_text == "结束"


def test_raw_text_preserves_original_whitespace(hr):
    cmd = hr.parse_command("   123456   ")
    assert cmd.intent == "otp"
    assert cmd.raw_text == "   123456   "
    assert cmd.args["code"] == "123456"


# ── Stop / Pause / Resume — anchored, case-insensitive ─────────────────────


@pytest.mark.parametrize("text,intent", [
    ("结束", "stop"),
    ("取消", "stop"),
    ("终止", "stop"),
    ("停止", "stop"),
    ("stop", "stop"),
    ("STOP", "stop"),
    ("Stop", "stop"),
    ("  stop  ", "stop"),
    ("暂停", "pause"),
    ("pause", "pause"),
    ("PAUSE", "pause"),
    ("继续", "resume"),
    ("恢复", "resume"),
    ("resume", "resume"),
    ("RESUME", "resume"),
])
def test_atomic_command_matches(hr, text, intent):
    cmd = hr.parse_command(text)
    assert cmd is not None, f"expected hit for {text!r}"
    assert cmd.intent == intent
    assert cmd.confidence == 1.0
    assert cmd.source == "regex"


@pytest.mark.parametrize("text", [
    "稍后结束这个",            # v0 bug: substring "结束" used to fire stop
    "请暂停一下吧",             # substring "暂停"
    "继续往下走",               # substring "继续"
    "我想要结束训练并查看结果",  # multi-word containing 结束
    "stop me here",            # substring "stop"
    "结束了吗？",                # punctuated — should not be exact match
])
def test_atomic_command_no_substring_match(hr, text):
    """Strict anchoring: containing a keyword in a longer message must NOT fire."""
    cmd = hr.parse_command(text)
    assert cmd is None, f"{text!r} must not match Layer 1 (got {cmd!r})"


# ── OTP — 6 digits, with optional request-id prefix ────────────────────────


def test_otp_six_digits(hr):
    cmd = hr.parse_command("123456")
    assert cmd.intent == "otp"
    assert cmd.args == {"code": "123456"}


def test_otp_with_whitespace_padding(hr):
    cmd = hr.parse_command(" 654321 ")
    assert cmd.intent == "otp"
    assert cmd.args["code"] == "654321"


def test_otp_with_request_id(hr):
    cmd = hr.parse_command("OTP req_abc123 654321")
    assert cmd.intent == "otp_with_id"
    assert cmd.args == {"request_id": "req_abc123", "code": "654321"}


def test_otp_with_id_case_insensitive(hr):
    cmd = hr.parse_command("otp REQ1 999888")
    assert cmd.intent == "otp_with_id"
    assert cmd.args["request_id"] == "REQ1"


@pytest.mark.parametrize("text", [
    "12345",        # 5 digits — too short
    "1234567",      # 7 digits — too long
    "12345a",       # not all digits
    "abc123def",    # digits embedded
    "123 456",      # split by space
    "I sent 123456 to you",  # 6 digits inside prose
])
def test_otp_strict_six_digits(hr, text):
    """OTP must be exactly 6 digits, anchored, optional surrounding whitespace."""
    cmd = hr.parse_command(text)
    assert cmd is None or cmd.intent != "otp", f"{text!r} should not parse as plain OTP"


# ── change_config ──────────────────────────────────────────────────────────


def test_change_config_single_key(hr):
    cmd = hr.parse_command("改 batch_size=4")
    assert cmd.intent == "change_config"
    assert cmd.args == {"batch_size": "4"}


def test_change_config_multiple_keys(hr):
    cmd = hr.parse_command("改 batch_size=8 max_retry_per_test=5 timeout=300")
    assert cmd.intent == "change_config"
    assert cmd.args == {"batch_size": "8", "max_retry_per_test": "5", "timeout": "300"}


def test_change_config_whitelist_drops_unknown(hr):
    cmd = hr.parse_command("改 batch_size=4 unknown_key=9 also_unknown=hello")
    assert cmd.intent == "change_config"
    assert "unknown_key" not in cmd.args
    assert "also_unknown" not in cmd.args
    assert cmd.args["batch_size"] == "4"


def test_change_config_empty_payload_when_no_whitelisted_keys(hr):
    """The '改' prefix triggers change_config even if all keys are non-whitelisted."""
    cmd = hr.parse_command("改 some_random_key=1")
    assert cmd.intent == "change_config"
    assert cmd.args == {}


def test_change_config_requires_leading_marker(hr):
    """'改' alone (no following kv) — still parsed as change_config with empty args."""
    cmd = hr.parse_command("改")
    assert cmd.intent == "change_config"
    assert cmd.args == {}


# ── None / empty / whitespace ──────────────────────────────────────────────


@pytest.mark.parametrize("text", ["", "   ", "\n", "\t  \t"])
def test_empty_input_returns_none(hr, text):
    assert hr.parse_command(text) is None


def test_none_input_returns_none(hr):
    assert hr.parse_command(None) is None


def test_unrecognized_free_text_returns_none(hr):
    """Free-text falls through to Layer 2 — Layer 1 must NOT classify it."""
    for text in ("跑 L4", "正式开跑", "全量", "随便说点啥"):
        assert hr.parse_command(text) is None, f"Layer 1 should not match {text!r}"


# ── parse_command_as_dict — back-compat adapter ────────────────────────────


def test_adapter_returns_legacy_shape_for_stop(hr):
    assert hr.parse_command_as_dict("结束") == {"type": "stop", "payload": {}}


def test_adapter_returns_legacy_shape_for_otp(hr):
    assert hr.parse_command_as_dict("123456") == {
        "type": "otp", "payload": {"code": "123456"}
    }


def test_adapter_returns_legacy_shape_for_otp_with_id(hr):
    """otp_with_id (new intent) maps to legacy 'otp' type for back-compat."""
    d = hr.parse_command_as_dict("OTP req1 123456")
    assert d["type"] == "otp"
    assert d["payload"]["code"] == "123456"
    assert d["payload"]["request_id"] == "req1"


def test_adapter_returns_none_on_no_match(hr):
    assert hr.parse_command_as_dict("跑 L4") is None
    assert hr.parse_command_as_dict("") is None


def test_adapter_returns_independent_payload_dict(hr):
    """Mutating the returned payload must not affect the underlying Command."""
    d = hr.parse_command_as_dict("123456")
    d["payload"]["code"] = "999999"
    # re-parse and check args are still pristine
    fresh = hr.parse_command("123456")
    assert fresh.args["code"] == "123456"
