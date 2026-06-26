"""Tests for classify_intent_llm (Layer 2 — parse & validate Agent JSON output).

The ut-supervisor Agent IS the LLM; it reads SOUL.md §Intent classification
and produces a JSON string. classify_intent_llm() only parses & validates
that string — no callback / no invoker. Tests pass JSON strings directly.

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §4
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HR_PATH = PROJECT_ROOT / "skills" / "ut" / "terminal-workflow" / "scripts" / "hermes_runner.py"


@pytest.fixture(scope="module")
def hr():
    spec = importlib.util.spec_from_file_location("hermes_runner", HR_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def _llm_json(intent, confidence=0.95, args=None):
    obj = {"intent": intent, "confidence": confidence}
    if args:
        obj["args"] = args
    return json.dumps(obj, ensure_ascii=False)


# ── Valid intents ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("intent", [
    "start_l1", "start_l2", "start_l3", "start_l4",
    "start_production", "change_config",
])
def test_valid_intents(hr, intent):
    cmd = hr.classify_intent_llm("跑 L4", _llm_json(intent))
    assert cmd.intent == intent
    assert cmd.confidence == 0.95
    assert cmd.source == "llm"
    assert cmd.raw_text == "跑 L4"


def test_unknown_intent_through_llm(hr):
    """LLM outputs 'unknown' → classified as unknown, not dropped."""
    cmd = hr.classify_intent_llm("跑下测试", _llm_json("unknown", 0.3))
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.3
    assert cmd.source == "llm"


# ── Confidence clamping ────────────────────────────────────────────────────────


@pytest.mark.parametrize("input_c, expected", [
    (0.5, 0.5),
    (0.0, 0.0),
    (1.0, 1.0),
    (999.0, 1.0),
    (-0.5, 0.0),
])
def test_confidence_handling(hr, input_c, expected):
    cmd = hr.classify_intent_llm("L4", _llm_json("start_l4", input_c))
    assert cmd.intent == "start_l4"
    assert cmd.confidence == expected


def test_string_confidence_rejected(hr):
    """SOUL.md specifies numeric confidence; a string is malformed → unknown."""
    cmd = hr.classify_intent_llm("L4", _llm_json("start_l4", "0.85"))
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


# ── JSON fence stripping ───────────────────────────────────────────────────────


def test_bare_json_fence(hr):
    cmd = hr.classify_intent_llm("L1", "```\n" + _llm_json("start_l1") + "\n```")
    assert cmd.intent == "start_l1"


def test_json_json_fence(hr):
    cmd = hr.classify_intent_llm("跑 L3", "```json\n" + _llm_json("start_l3", 0.9) + "\n```")
    assert cmd.intent == "start_l3"
    assert cmd.confidence == 0.9


# ── Malformed / fallback paths ──────────────────────────────────────────────────


def test_non_string_llm_response(hr):
    cmd = hr.classify_intent_llm("hi", 42)              # not a string
    assert cmd.intent == "unknown"


def test_non_json_response(hr):
    cmd = hr.classify_intent_llm("my thoughts", "I think the user wants L4")
    assert cmd.intent == "unknown"


def test_garbage_json_that_is_not_a_dict(hr):
    cmd = hr.classify_intent_llm("hi", json.dumps(["start_l4", 0.9]))
    assert cmd.intent == "unknown"


def test_json_missing_intent_key(hr):
    cmd = hr.classify_intent_llm("hi", json.dumps({"something_else": "start_l4"}))
    assert cmd.intent == "unknown"


def test_json_missing_confidence_key(hr):
    cmd = hr.classify_intent_llm("hi", json.dumps({"intent": "start_l4"}))
    assert cmd.intent == "unknown"


def test_json_non_numeric_confidence(hr):
    cmd = hr.classify_intent_llm("hi", json.dumps({"intent": "start_l4", "confidence": "high"}))
    assert cmd.intent == "unknown"


def test_intent_not_in_vocabulary(hr):
    """LLM outputs a start label that doesn't exist (e.g. start_l5) → unknown."""
    cmd = hr.classify_intent_llm("run L5", _llm_json("start_l5", 0.9))
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


def test_intent_is_not_channel_supervisor_start_l1(hr):
    """start_l1 (valid) must be accepted — regression guard."""
    cmd = hr.classify_intent_llm("L1", _llm_json("start_l1", 0.92))
    assert cmd.intent == "start_l1"


# ── args handling ──────────────────────────────────────────────────────────────


def test_classify_change_config_with_args(hr):
    cmd = hr.classify_intent_llm("改 batch_size 为 10", json.dumps({
        "intent": "change_config",
        "confidence": 0.85,
        "args": {"key": "batch_size", "value": "10"},
    }))
    assert cmd.intent == "change_config"
    assert cmd.confidence == 0.85
    assert cmd.args == {"key": "batch_size", "value": "10"}


def test_args_defaults_to_empty_dict_when_missing(hr):
    cmd = hr.classify_intent_llm("L4", json.dumps({"intent": "start_l4", "confidence": 0.95}))
    assert cmd.args == {}


def test_args_defaults_to_empty_dict_when_not_a_dict(hr):
    cmd = hr.classify_intent_llm("L4", json.dumps({
        "intent": "start_l4", "confidence": 0.95, "args": "not-a-dict"
    }))
    assert cmd.args == {}


# ── None / empty input ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [None, "", "   ", "\n"])
def test_empty_input_returns_unknown(hr, text):
    cmd = hr.classify_intent_llm(text, _llm_json("start_l4"))
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0
    assert cmd.source == "llm"


# ── _strip_json_fence — direct unit test ────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ('```{"intent":"start_l1","confidence":0.9}```', '{"intent":"start_l1","confidence":0.9}'),
    ('```json\n{"intent":"start_l1"}\n```', '{"intent":"start_l1"}'),
    ('   {"intent":"start_l1"}   ', '{"intent":"start_l1"}'),
    ('{"intent":"start_l1"}', '{"intent":"start_l1"}'),
    ('', ''),
])
def test_strip_json_fence(hr, raw, expected):
    assert hr._strip_json_fence(raw) == expected