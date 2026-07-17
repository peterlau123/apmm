"""M3 (postmortem 2026-06-23 issue #2) — Bastion OTP bring-up unit tests.

Covers the four contract points the postmortem locks down:
  1. ensure_connected → daemon先死后活 → bringup 整链路走通
  2. OTP_PATTERN 正则提取 6 位码 (含 request_id 绑定 + 反例)
  3. request_otp 超时 → 返回 None (不抛)
  4. start_daemon 在 Windows 使用 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP

OTP 永不落盘约束 (memory regression) 见 test_no_otp_persisted_to_run_dir.py。
"""
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASTION_MANAGER = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "bastion_manager.py"


def _load_bastion_manager():
    sys.path.insert(0, str(BASTION_MANAGER.parent))
    sys.path.insert(0, str(BASTION_MANAGER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("bastion_manager", BASTION_MANAGER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load_bastion_manager()


# ── 1. ensure_connected: daemon 先死后活 ─────────────────────────────────────

def test_ensure_connected_daemon_dead_then_alive(tmp_path):
    """daemon initially dead → request_otp returns code → restart → ping recovers."""
    mgr = bm.BastionManager(
        workspace=str(tmp_path),
        profile="t_h20",
        feishu_config_path=None,
        workflow_state_path=None,
    )

    # First ping fails (daemon dead); subsequent pings succeed (after restart).
    ping_calls = {"n": 0}

    def fake_ping():
        ping_calls["n"] += 1
        return ping_calls["n"] >= 2

    with patch.object(mgr, "ping", side_effect=fake_ping), \
         patch.object(mgr, "request_otp", return_value="123456") as mock_otp, \
         patch.object(mgr, "restart_daemon") as mock_restart, \
         patch("time.sleep"):
        ok = mgr.ensure_connected(reason="startup", stage="select_batch", batch_id=None)

    assert ok is True
    mock_otp.assert_called_once()
    mock_restart.assert_called_once_with("123456")


def test_ensure_connected_returns_true_when_already_alive(tmp_path):
    """daemon healthy at first ping → skip OTP, no restart."""
    mgr = bm.BastionManager(workspace=str(tmp_path), profile="t_h20")
    with patch.object(mgr, "ping", return_value=True), \
         patch.object(mgr, "request_otp") as mock_otp, \
         patch.object(mgr, "restart_daemon") as mock_restart:
        ok = mgr.ensure_connected()
    assert ok is True
    mock_otp.assert_not_called()
    mock_restart.assert_not_called()


# ── 2. OTP_PATTERN regex ─────────────────────────────────────────────────────

def test_otp_pattern_extracts_6_digit_code():
    """正则提取 6 位数字 + request_id 绑定。"""
    m = bm.OTP_PATTERN.search("OTP otp-20260623-abc123 562741")
    assert m is not None
    assert m.group(1) == "otp-20260623-abc123"
    assert m.group(2) == "562741"


def test_otp_pattern_rejects_bare_6_digits():
    """裸 6 位码 (无 OTP 前缀 + request_id) 不许匹配，防误触。"""
    assert bm.OTP_PATTERN.search("562741") is None
    assert bm.OTP_PATTERN.search("the code is 562741") is None


def test_otp_pattern_rejects_wrong_length():
    """5 位明确拒绝。7 位会匹配前 6 位（宽松匹配；用户多打的尾字符不阻断），
    这条记录现状以防未来意外收紧锚定行为。"""
    assert bm.OTP_PATTERN.search("OTP otp-20260623-abc123 12345") is None
    m = bm.OTP_PATTERN.search("OTP otp-20260623-abc123 1234567")
    assert m is not None and m.group(2) == "123456"


# ── 3. request_otp 超时 ──────────────────────────────────────────────────────

def test_request_otp_returns_none_on_timeout(tmp_path):
    """timeout 内无回复 → 返回 None，不抛。"""
    mgr = bm.BastionManager(workspace=str(tmp_path), profile="t_h20")

    with patch.object(mgr, "_send_otp_card"), \
         patch.object(mgr, "_find_otp_reply", return_value=None), \
         patch.object(mgr, "_update_bastion_state"), \
         patch("time.sleep"):
        otp = mgr.request_otp(reason="test", timeout=1)

    assert otp is None


# ── 4. start_daemon Windows detached flags ──────────────────────────────────

def test_start_daemon_uses_detached_process_on_windows(tmp_path):
    """Windows: Popen kwargs 必含 CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS。"""
    if os.name != "nt":
        # On POSIX the equivalent guarantee is preexec_fn=os.setpgrp; covered below.
        return

    import subprocess as sp
    mgr = bm.BastionManager(workspace=str(tmp_path), profile="t_h20")
    with patch("subprocess.Popen") as mock_popen:
        mgr.start_daemon("123456")
        _, kwargs = mock_popen.call_args
        flags = kwargs.get("creationflags", 0)
        expected = sp.CREATE_NEW_PROCESS_GROUP | sp.DETACHED_PROCESS
        assert flags == expected, f"expected {expected:#x}, got {flags:#x}"


def test_start_daemon_uses_setpgrp_on_posix(tmp_path):
    """POSIX: kwargs 必含 preexec_fn (会话隔离的等价物)。"""
    if os.name == "nt":
        return
    mgr = bm.BastionManager(workspace=str(tmp_path), profile="t_h20")
    with patch("subprocess.Popen") as mock_popen:
        mgr.start_daemon("123456")
        _, kwargs = mock_popen.call_args
        assert "preexec_fn" in kwargs
