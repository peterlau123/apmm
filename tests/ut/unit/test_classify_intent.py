"""Tests for classify_intent_llm (Layer 2 — LLM intent classification).

Tests the Python parsing/validation/fallback logic only; the LLM invoker
is mocked. Coverage includes:
  - Successful classification for each valid intent
  - Confidence clamping
  - JSON fence stripping (```json … ```)
  - Non-JSON / malformed responses → unknown
  - Intent not in vocabulary → unknown
  - None/empty input → unknown
  - Invoker raises → unknown
  - args field handling

Spec: tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md §4
"""
from __future__ import annotations

import importlib.util
import json
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


# ── helpers ───────────────────────────────────────────────────────────────────


def _llm_json(intent, confidence=0.95, args=None):
    """Build a valid LLM response as JSON string."""
    obj = {"intent": intent, "confidence": confidence}
    if args:
        obj["args"] = args
    return json.dumps(obj, ensure_ascii=False)


def _invoker(response):
    """Factory for an llm_invoker callable that always returns *response*."""
    return lambda text: response


def _raise_invoker(exc=RuntimeError("LLM failed")):
    """Factory for an llm_invoker callable that always raises."""
    def fn(text):
        raise exc
    return fn


# ── Valid intents ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("intent", [
    "start_l1", "start_l2", "start_l3", "start_l4",
    "start_production", "change_config",
])
def test_valid_intents(hr, intent):
    inv = _invoker(_llm_json(intent))
    cmd = hr.classify_intent_llm("跑 L4", llm_invoker=inv)
    assert cmd.intent == intent
    assert cmd.confidence == 0.95
    assert cmd.source == "llm"
    assert cmd.raw_text == "跑 L4"


def test_unknown_intent_through_llm(hr):
    """LLM outputs 'unknown' → classified as unknown, not dropped."""
    inv = _invoker(_llm_json("unknown", 0.3))
    cmd = hr.classify_intent_llm("跑下测试", llm_invoker=inv)
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.3
    assert cmd.source == "llm"


# ── Confidence clamping ────────────────────────────────────────────────────────


@pytest.mark.parametrize("input_c, expected", [
    (0.5, 0.5),
    (0.0, 0.0),
    (1.0, 1.0),
    (999.0, 1.0),           # out of range high
    (-0.5, 0.0),            # out of range low
])
def test_confidence_handling(hr, input_c, expected):
    inv = _invoker(_llm_json("start_l4", input_c))
    cmd = hr.classify_intent_llm("L4", llm_invoker=inv)
    assert cmd.intent == "start_l4"
    assert cmd.confidence == expected


def test_string_confidence_rejected(hr):
    """SOUL.md specifies numeric confidence; a string is malformed → unknown."""
    inv = _invoker(_llm_json("start_l4", "0.85"))
    cmd = hr.classify_intent_llm("L4", llm_invoker=inv)
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


# ── JSON fence stripping ───────────────────────────────────────────────────────


def test_bare_json_fence(hr):
    inv = _invoker("```\n" + _llm_json("start_l1") + "\n```")
    cmd = hr.classify_intent_llm("L1", llm_invoker=inv)
    assert cmd.intent == "start_l1"
    assert cmd.confidence == 0.95


def test_json_json_fence(hr):
    inv = _invoker("```json\n" + _llm_json("start_l3", 0.9) + "\n```")
    cmd = hr.classify_intent_llm("跑 L3", llm_invoker=inv)
    assert cmd.intent == "start_l3"
    assert cmd.confidence == 0.9


# ── Malformed / fallback paths ──────────────────────────────────────────────────


def test_no_invoker_returns_unknown(hr):
    """llm_invoker=None → unknown with confidence 0.0, no error raised."""
    cmd = hr.classify_intent_llm("跑 L4")
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0
    assert cmd.source == "llm"
    assert cmd.raw_text == "跑 L4"


def test_invoker_raises_returns_unknown(hr):
    cmd = hr.classify_intent_llm("跑 L4", llm_invoker=_raise_invoker())
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


def test_non_string_llm_response(hr):
    inv = _invoker(42)          # not a string
    cmd = hr.classify_intent_llm("hi", llm_invoker=inv)
    assert cmd.intent == "unknown"


def test_non_json_response(hr):
    inv = _invoker("I think the user wants to run L4")  # prose
    cmd = hr.classify_intent_llm("my thoughts", llm_invoker=inv)
    assert cmd.intent == "unknown"


def test_garbage_json_that_is_not_a_dict(hr):
    inv = _invoker(json.dumps(["start_l4", 0.9]))  # list, not dict
    cmd = hr.classify_intent_llm("hi", llm_invoker=inv)
    assert cmd.intent == "unknown"


def test_json_missing_intent_key(hr):
    inv = _invoker(json.dumps({"something_else": "start_l4"}))
    cmd = hr.classify_intent_llm("hi", llm_invoker=inv)
    assert cmd.intent == "unknown"


def test_json_missing_confidence_key(hr):
    inv = _invoker(json.dumps({"intent": "start_l4"}))  # no confidence
    cmd = hr.classify_intent_llm("hi", llm_invoker=inv)
    assert cmd.intent == "unknown"


def test_json_non_numeric_confidence(hr):
    inv = _invoker(json.dumps({"intent": "start_l4", "confidence": "high"}))
    cmd = hr.classify_intent_llm("hi", llm_invoker=inv)
    assert cmd.intent == "unknown"


def test_intent_not_in_vocabulary(hr):
    """LLM outputs a start label that doesn't exist (e.g. start_l5) → unknown."""
    inv = _invoker(_llm_json("start_l5", 0.9))
    cmd = hr.classify_intent_llm("run L5", llm_invoker=inv)
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


def test_intent_is_not_channel_supervisor_start_l1(hr):
    """start_l1 (valid) must be accepted — regression guard."""
    inv = _invoker(_llm_json("start_l1", 0.92))
    cmd = hr.classify_intent_llm("L1", llm_invoker=inv)
    assert cmd.intent == "start_l1"


# ── args handling ──────────────────────────────────────────────────────────────


def test_classify_change_config_with_args(hr):
    inv = _invoker(json.dumps({
        "intent": "change_config",
        "confidence": 0.85,
        "args": {"key": "batch_size", "value": "10"},
    }))
    cmd = hr.classify_intent_llm("改 batch_size 为 10", llm_invoker=inv)
    assert cmd.intent == "change_config"
    assert cmd.confidence == 0.85
    assert cmd.args == {"key": "batch_size", "value": "10"}


def test_args_defaults_to_empty_dict_when_missing(hr):
    inv = _invoker(json.dumps({"intent": "start_l4", "confidence": 0.95}))
    cmd = hr.classify_intent_llm("L4", llm_invoker=inv)
    assert cmd.args == {}


def test_args_defaults_to_empty_dict_when_not_a_dict(hr):
    inv = _invoker(json.dumps({
        "intent": "start_l4", "confidence": 0.95, "args": "not-a-dict"
    }))
    cmd = hr.classify_intent_llm("L4", llm_invoker=inv)
    assert cmd.args == {}


# ── None / empty input ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [None, "", "   ", "\n"])
def test_empty_input_returns_unknown(hr, text):
    inv = _invoker(_llm_json("start_l4"))
    cmd = hr.classify_intent_llm(text, llm_invoker=inv)
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