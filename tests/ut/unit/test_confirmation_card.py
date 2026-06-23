"""Tests for FeishuAPI.send_confirmation_card (P4a — intent confirmation gate).

Mocks the HTTP layer; verifies card payload shape (title, template, body
emphasis for production vs tier, reply instruction).

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §4.5
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FEISHU_API = PROJECT_ROOT / "skills" / "ut" / "workflow" / "scripts" / "feishu_api.py"


@pytest.fixture(scope="module")
def fa_module():
    sys.path.insert(0, str(FEISHU_API.parent))
    spec = importlib.util.spec_from_file_location("feishu_api", FEISHU_API)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def api(fa_module, tmp_path):
    """Build a FeishuAPI with a stub config; HTTP calls are patched per test."""
    cfg = {"app_id": "x", "app_secret": "y", "chat_id": "oc_test"}
    cfg_path = tmp_path / "feishu.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    inst = fa_module.FeishuAPI(str(cfg_path))
    # Bypass auth roundtrip
    inst._token = "stub-token"
    inst._token_expire_time = 10**12
    return inst


def _capture_card(api_inst):
    """Run send_confirmation_card with a patched HTTP layer; return captured
    card payload."""
    results = {}

    def _post(url, headers=None, json=None, timeout=None):
        import json as _json_mod
        inner = _json_mod.loads(json["content"]) if isinstance(json.get("content"), str) else {}
        results["card"] = inner
        results["receive_id"] = json.get("receive_id")
        results["msg_type"] = json.get("msg_type")
        return MagicMock(json=lambda: {"code": 0})

    return _post, results


def test_tier_l4_card_shape(api):
    sender, captured = _capture_card(api)
    with patch("feishu_api.requests.post", side_effect=sender):
        ok = api.send_confirmation_card(
            intent="start_l4",
            yaml_path="tests/ut/integration/fixtures/workflow.l4.yaml",
            test_list_path="tests/ut/integration/fixtures/l3_retry_subset.txt",
            mode="kanban",
            eta="~60 分钟",
        )
    assert ok is True
    assert captured["msg_type"] == "interactive"
    card = captured["card"]
    assert card["header"]["template"] == "blue"        # tiers are blue
    assert "L4 Kanban distributed 测试" in card["header"]["title"]["content"]
    body = card["elements"][0]["text"]["content"]
    assert "workflow.l4.yaml" in body
    assert "l3_retry_subset.txt" in body
    assert "kanban" in body
    assert "~60 分钟" in body
    assert "确认" in body and "取消" in body
    # No production-only emphasis on tier cards.
    assert "这是生产全量运行" not in body


def test_production_card_has_warning_and_orange_template(api):
    sender, captured = _capture_card(api)
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_confirmation_card(
            intent="start_production",
            yaml_path=".agents/workflow.yaml",
            test_list_path="tests/ut_test_list.txt",
            mode="kanban",
            eta="hours–days",
        )
    card = captured["card"]
    assert card["header"]["template"] == "orange"
    body = card["elements"][0]["text"]["content"]
    assert "生产 全量 UT 测试" in body
    assert "⚠️" in body
    assert "这是生产全量运行" in body
    assert "hours–days" in body


def test_default_timeout_displayed(api):
    sender, captured = _capture_card(api)
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_confirmation_card(
            intent="start_l1",
            yaml_path="x.yaml", test_list_path="x.txt",
            mode="linear", eta="< 1 min",
        )
    body = captured["card"]["elements"][0]["text"]["content"]
    assert "10s" in body


def test_custom_timeout_displayed(api):
    sender, captured = _capture_card(api)
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_confirmation_card(
            intent="start_l1",
            yaml_path="x.yaml", test_list_path="x.txt",
            mode="linear", eta="< 1 min",
            timeout_seconds=30,
        )
    body = captured["card"]["elements"][0]["text"]["content"]
    assert "30s" in body


@pytest.mark.parametrize("intent,label", [
    ("start_l1", "L1 烟囱测试"),
    ("start_l2", "L2 mini 测试"),
    ("start_l3", "L3 fast subset 测试"),
    ("start_l4", "L4 Kanban distributed 测试"),
])
def test_tier_label_per_intent(api, intent, label):
    sender, captured = _capture_card(api)
    with patch("feishu_api.requests.post", side_effect=sender):
        api.send_confirmation_card(
            intent=intent, yaml_path="x", test_list_path="x",
            mode="linear", eta="x",
        )
    body = captured["card"]["elements"][0]["text"]["content"]
    assert label in body


def test_send_failure_returns_false(api):
    """API returns code != 0 → False (matches send_card contract)."""
    def _fail_post(*a, **k):
        return MagicMock(json=lambda: {"code": 99, "msg": "rate limited"})
    with patch("feishu_api.requests.post", side_effect=_fail_post):
        ok = api.send_confirmation_card(
            intent="start_l1", yaml_path="x", test_list_path="x",
            mode="linear", eta="x",
        )
    assert ok is False