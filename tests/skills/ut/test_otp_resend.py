"""Task 1.1: OTP progressive resend schedule.

otp_resend_delay defines the backoff (minutes) for repeated OTP requests;
otp_should_at_user marks when to @-mention the user. Loaded by file path
(hyphenated skill dirs).
"""
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASTION_MANAGER = PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "bastion_manager.py"


def _load_bastion_manager():
    sys.path.insert(0, str(BASTION_MANAGER.parent))
    sys.path.insert(0, str(BASTION_MANAGER.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("bastion_manager", BASTION_MANAGER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load_bastion_manager()
otp_resend_delay = bm.otp_resend_delay
otp_should_at_user = bm.otp_should_at_user


def test_resend_schedule():
    assert [otp_resend_delay(i) for i in (1, 2, 3, 4, 5, 99)] == [5, 15, 30, 60, 60, 60]


def test_resend_at_user_marker():
    assert otp_should_at_user(3) is True
    assert otp_should_at_user(2) is False
