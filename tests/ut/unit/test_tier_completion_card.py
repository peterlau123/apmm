"""Tests for FeishuAPI.send_tier_completion_card (P5b — tier PASS/FAIL card).

Mocks the HTTP layer; verifies card payload shape for both PASS and FAIL
verdicts, hard-assertion summary, cap at 8 failed entries.

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §5 P5b
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FEISHU_API = PROJECT_ROOT / "skills" / "ut" / "ut_common" / "scripts" / "feishu_api.py"


@pytest.fixture(scope="module")
def fa_module():
    sys.path.insert(0, str(FEISHU_API.parent))
    spec = importlib.util.spec_from_file_location("feishu_api", FEISHU_API)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def api(fa_module, tmp_path):
    cfg = {"app_id": "x", "app_secret": "y", "chat_id": "oc_test"}
    cfg_path = tmp_path / "feishu.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    inst = fa_module.FeishuAPI(str(cfg_path))
    inst._token = "stub-token"
    inst._token_expire_time = 10**12
    return inst


def _capture(api_inst):
    results = {}

    def _post(url, headers=None, json=None, timeout=None):
        import json as _json_mod
        inner = _json_mod.loads(json["content"]) if isinstance(json.get("content"), str) else {}
        results["card"] = inner
        return MagicMock(json=lambda: {"code": 0})

    return _post, results


def test_pass_verdict_renders_green(api):
    sender, captured = _capture(api)
    verdict = {
        "overall": "PASS",
        "assertions": [
            {"id": "TSD", "result": "PASS", "severity": "hard"},
            {"id": "AF-1", "result": "PASS", "severity": "hard"},
            {"id": "AF-2", "result": "PASS", "severity": "hard"},
        ],
        "summary": "3 PASS / 0 FAIL / 0 SKIP",
    }
    with patch("feishu_api.requests.post", side_effect=sender):
        ok = api.send_tier_completion_card(verdict, "L4", "runs/ut-20260622-1234")
    assert ok is True
    card = captured["card"]
    assert card["header"]["template"] == "green"
    assert "L4 PASS" in card["header"]["title"]["content"]
    body = card["elements"][0]["text"]["content"]
    assert "✅" in body
    assert "runs/ut-20260622-1234" in body
    assert "3 PASS" in body


def test_fail_verdict_renders_red_with_hard_assertions(api):
    sender, captured = _capture(api)
    verdict = {
        "overall": "FAIL",
        "assertions": [
            {"id": "TSD", "result": "PASS", "severity": "hard"},
            {"id": "AF-1", "result": "FAIL", "severity": "hard",
             "detail": "log_file null for test_foo"},
            {"id": "STG-2", "result": "FAIL", "severity": "hard",
             "detail": "test_bar retry_count=4 exceeds max_retry+1=3"},
        ],
        "summary": "1 PASS / 2 FAIL / 0 SKIP",
    }
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_tier_completion_card(verdict, "L4", "runs/ut-20260622-1234")
    card = captured["card"]
    assert card["header"]["template"] == "red"
    assert "L4 FAIL" in card["header"]["title"]["content"]
    body = card["elements"][0]["text"]["content"]
    assert "❌" in body
    assert "AF-1" in body and "log_file null" in body
    assert "STG-2" in body and "retry_count=4" in body


def test_soft_failures_not_in_hard_list(api):
    sender, captured = _capture(api)
    verdict = {
        "overall": "FAIL",
        "assertions": [
            {"id": "AF-1", "result": "FAIL", "severity": "hard",
             "detail": "hard fail"},
            {"id": "per_test", "result": "FAIL", "severity": "soft",
             "detail": "soft only"},
        ],
        "summary": "0 PASS / 2 FAIL / 0 SKIP",
    }
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_tier_completion_card(verdict, "L4", "runs/x")
    body = captured["card"]["elements"][0]["text"]["content"]
    assert "hard fail" in body
    assert "soft only" not in body          # soft failures suppressed from hard list


def test_caps_failed_hard_list_at_8(api):
    sender, captured = _capture(api)
    many = [
        {"id": f"AF-{i}", "result": "FAIL", "severity": "hard",
         "detail": f"detail {i}"}
        for i in range(12)
    ]
    verdict = {"overall": "FAIL", "assertions": many, "summary": "0/12/0"}
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_tier_completion_card(verdict, "L4", "runs/x")
    body = captured["card"]["elements"][0]["text"]["content"]
    assert "AF-0" in body and "AF-7" in body          # first 8 shown
    assert "AF-8" not in body and "AF-11" not in body  # rest suppressed
    assert "and 4 more" in body


def test_default_summary_when_missing(api):
    sender, captured = _capture(api)
    verdict = {
        "overall": "PASS",
        "assertions": [
            {"id": "TSD", "result": "PASS", "severity": "hard"},
            {"id": "AF-3", "result": "SKIP", "severity": "hard"},
        ],
    }
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_tier_completion_card(verdict, "L1", "runs/x")
    body = captured["card"]["elements"][0]["text"]["content"]
    # Default summary should be derived from counts
    assert "1 PASS" in body
    assert "1 SKIP" in body


@pytest.mark.parametrize("tier", ["L1", "L2", "L3", "L4"])
def test_tier_label_each(api, tier):
    sender, captured = _capture(api)
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_tier_completion_card({"overall": "PASS"}, tier, "runs/x")
    assert tier in captured["card"]["header"]["title"]["content"]


def test_send_failure_returns_false(api):
    def _fail_post(*a, **k):
        return MagicMock(json=lambda: {"code": 99})
    with patch("feishu_api.requests.post", side_effect=_fail_post):
        ok = api.send_tier_completion_card({"overall": "PASS"}, "L4", "runs/x")
    assert ok is False