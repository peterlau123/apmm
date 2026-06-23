"""Tests for the dependency-stall classifier (Stage 4 timeout dispatcher).

Design: tasks/ut/docs/designs/2026-06-23-pytest-timeout-redesign.md §5.

Coverage:
  - HF download fixture       → dep_stall + dep_hint
  - pip install fixture       → dep_stall (pkg name in evidence)
  - pytest deadlock fixture   → not_dep_stall (no ignored_reason)
  - LLM JSON malformed        → unknown fallback
  - LLM JSON schema mismatch  → unknown fallback (bad enum / missing field)
  - LLM None / non-str        → unknown fallback
  - ignored_reason wording    → matches design §5.4 templates verbatim
  - _handle_timeout_test wiring → emits resolution.dependency_classification
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDLER_DIR = REPO_ROOT / "skills" / "ut" / "failure-handler" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dep_stall = _load(
    "ut_classify_dep_stall_test", HANDLER_DIR / "classify_dependency_stall.py"
)
gen_handled = _load(
    "ut_generate_handled_test", HANDLER_DIR / "generate_handled_manifest.py"
)


# ── classify(): happy path — dep_stall (HF download) ────────────────────────

def test_classify_dep_stall_hf_download():
    log_tail = (
        "tests/test_load.py::test_llama_3_2_1b "
        "Downloading model.safetensors: 12% [00:42<06:11, 12MB/s]\n"
        "__WATCHDOG__: idle_exceeded 121s (no log activity)\n"
    )
    llm_json = json.dumps({
        "classification": "dep_stall",
        "evidence": "Downloading model.safetensors: 12% [00:42<06:11, 12MB/s]",
        "dependency_hint": "meta-llama/Llama-3.2-1B-Instruct",
    })
    out = dep_stall.classify(log_tail, llm_json)
    assert out["classification"] == "dep_stall"
    assert out["dependency_hint"] == "meta-llama/Llama-3.2-1B-Instruct"
    assert "Downloading model.safetensors" in out["evidence"]
    assert "_fallback_reason" not in out


def test_classify_dep_stall_pip_install():
    log_tail = (
        "Collecting mteb==1.0.0\n"
        "  Downloading mteb-1.0.0-py3-none-any.whl (302 kB)\n"
        "__WATCHDOG__: idle_exceeded 121s (no log activity)\n"
    )
    llm_json = json.dumps({
        "classification": "dep_stall",
        "evidence": "Collecting mteb==1.0.0",
        "dependency_hint": "mteb",
    })
    out = dep_stall.classify(log_tail, llm_json)
    assert out["classification"] == "dep_stall"
    assert out["dependency_hint"] == "mteb"


# ── classify(): not_dep_stall path (deadlock / GPU OOM / SSH drop) ──────────

def test_classify_not_dep_stall_deadlock():
    log_tail = (
        "tests/test_inference.py::test_batched_decode\n"
        "[INFO] waiting on lock acquire at decoder.py:421\n"
        "__WATCHDOG__: idle_exceeded 121s (no log activity)\n"
    )
    llm_json = json.dumps({
        "classification": "not_dep_stall",
        "evidence": "[INFO] waiting on lock acquire at decoder.py:421",
        "dependency_hint": None,
    })
    out = dep_stall.classify(log_tail, llm_json)
    assert out["classification"] == "not_dep_stall"
    assert out["dependency_hint"] is None


# ── classify(): unknown fallback paths ──────────────────────────────────────

def test_classify_unknown_when_llm_is_none():
    log_tail = "tests/test_x.py PASSED [50%]\n"
    out = dep_stall.classify(log_tail, None)
    assert out["classification"] == "unknown"
    assert out["dependency_hint"] is None
    assert "PASSED" in out["evidence"]  # falls back to last non-empty line
    assert out["_fallback_reason"].startswith("llm_output_none")


def test_classify_unknown_when_llm_is_not_str():
    out = dep_stall.classify("foo\n", llm_output=42)  # type: ignore[arg-type]
    assert out["classification"] == "unknown"
    assert out["_fallback_reason"].startswith("llm_output_not_str")


def test_classify_unknown_on_malformed_json():
    out = dep_stall.classify("foo\n", "this is not json {{{")
    assert out["classification"] == "unknown"
    assert out["_fallback_reason"].startswith("json_decode")


def test_classify_unknown_on_bad_enum():
    """classification not in {dep_stall, not_dep_stall, unknown}."""
    bad = json.dumps({
        "classification": "definitely_dep_stall",  # not in enum
        "evidence": "Downloading foo",
        "dependency_hint": None,
    })
    out = dep_stall.classify("Downloading foo\n", bad)
    assert out["classification"] == "unknown"
    assert "schema:" in out["_fallback_reason"]


def test_classify_unknown_on_missing_evidence():
    bad = json.dumps({"classification": "dep_stall"})  # no evidence
    out = dep_stall.classify("end of log\n", bad)
    assert out["classification"] == "unknown"
    assert "schema:" in out["_fallback_reason"]


def test_classify_unknown_on_empty_evidence():
    bad = json.dumps({
        "classification": "dep_stall",
        "evidence": "",
        "dependency_hint": "foo",
    })
    out = dep_stall.classify("end of log\n", bad)
    assert out["classification"] == "unknown"
    assert "schema:" in out["_fallback_reason"]


def test_classify_strips_markdown_fence():
    fenced = "```json\n" + json.dumps({
        "classification": "not_dep_stall",
        "evidence": "AssertionError: 1==2",
        "dependency_hint": None,
    }) + "\n```"
    out = dep_stall.classify("AssertionError: 1==2\n", fenced)
    assert out["classification"] == "not_dep_stall"


def test_classify_normalizes_dep_hint_when_not_dep_stall():
    """Schema permits non-null dep_hint on any classification, but the design
    says it must be null when classification != 'dep_stall'. Verify we
    overwrite a stray hint defensively."""
    payload = json.dumps({
        "classification": "not_dep_stall",
        "evidence": "AssertionError",
        "dependency_hint": "torch",  # stray non-null
    })
    out = dep_stall.classify("AssertionError\n", payload)
    assert out["classification"] == "not_dep_stall"
    assert out["dependency_hint"] is None


# ── ignored_reason_for(): wording per design §5.4 ───────────────────────────

def test_ignored_reason_for_dep_stall_with_hint():
    reason = dep_stall.ignored_reason_for({
        "classification": "dep_stall",
        "evidence": "Downloading model.safetensors: 12%",
        "dependency_hint": "meta-llama/Llama-3.2-1B-Instruct",
    })
    assert reason == "依赖未就绪需人工处理: meta-llama/Llama-3.2-1B-Instruct"


def test_ignored_reason_for_dep_stall_without_hint_uses_evidence():
    reason = dep_stall.ignored_reason_for({
        "classification": "dep_stall",
        "evidence": "Fetching huggingface.co/foo",
        "dependency_hint": None,
    })
    assert reason == "依赖未就绪需人工处理: Fetching huggingface.co/foo"


def test_ignored_reason_for_unknown():
    reason = dep_stall.ignored_reason_for({
        "classification": "unknown",
        "evidence": "tests/test_x.py PASSED [99%]",
        "dependency_hint": None,
    })
    assert reason == (
        "分类不明 (LLM 未识别 / schema mismatch); 末尾日志: "
        "tests/test_x.py PASSED [99%]"
    )


def test_ignored_reason_for_not_dep_stall_returns_none():
    """not_dep_stall keeps the test in retry path → no ignored_reason."""
    reason = dep_stall.ignored_reason_for({
        "classification": "not_dep_stall",
        "evidence": "AssertionError",
        "dependency_hint": None,
    })
    assert reason is None


# ── strip_internal_fields: removes _fallback_reason debug helper ────────────

def test_strip_internal_fields_drops_underscore_keys():
    raw = {
        "classification": "unknown",
        "evidence": "foo",
        "dependency_hint": None,
        "_fallback_reason": "json_decode:bad",
    }
    cleaned = dep_stall.strip_internal_fields(raw)
    assert cleaned == {
        "classification": "unknown",
        "evidence": "foo",
        "dependency_hint": None,
    }


# ── render_prompt: contains the固化 instructions and log content ─────────────

def test_render_prompt_embeds_log_tail():
    prompt = dep_stall.render_prompt(
        "Downloading model.safetensors: 12% [00:42<06:11, 12MB/s]"
    )
    assert "dep_stall" in prompt
    assert "not_dep_stall" in prompt
    assert "unknown" in prompt
    assert "Downloading model.safetensors" in prompt
    # Must not contain Python f-string braces unresolved
    assert "{log_tail}" not in prompt


# ── _handle_timeout_test: end-to-end fixer wiring ───────────────────────────

def test_handle_timeout_test_dep_stall_emits_resolution(tmp_path):
    # Prepare a batch_dir with a summary.txt that the helper reads from.
    batch_dir = tmp_path
    (batch_dir / "summary.txt").write_text(
        "Downloading model.safetensors: 12% [00:42<06:11, 12MB/s]\n"
        "__WATCHDOG__: idle_exceeded 121s (no log activity)\n",
        encoding="utf-8",
    )

    def fake_llm(prompt: str) -> str:
        assert "Downloading model.safetensors" in prompt
        return json.dumps({
            "classification": "dep_stall",
            "evidence": "Downloading model.safetensors: 12%",
            "dependency_hint": "meta-llama/Llama-3.2-1B-Instruct",
        })

    test = {
        "test_node": "tests/test_load.py::test_llama_3_2_1b",
        "status": "retriable_error",
        "error_type": "timeout",
        "error_message": "",
    }
    entry = gen_handled._handle_timeout_test(
        test, batch_dir, llm_invoker=fake_llm
    )
    assert entry is not None
    assert entry["final_status"] == "ignored"
    assert entry["error_type"] == "timeout"
    assert entry["ignored_reason"] == (
        "依赖未就绪需人工处理: meta-llama/Llama-3.2-1B-Instruct"
    )
    dc = entry["resolution"]["dependency_classification"]
    assert dc["classification"] == "dep_stall"
    assert dc["dependency_hint"] == "meta-llama/Llama-3.2-1B-Instruct"
    # _fallback_reason must NOT leak into the persisted resolution.
    assert "_fallback_reason" not in dc


def test_handle_timeout_test_unknown_falls_through_to_ignored(tmp_path):
    batch_dir = tmp_path
    (batch_dir / "summary.txt").write_text(
        "tests/test_x.py PASSED [99%]\n"
        "__WATCHDOG__: idle_exceeded 121s (no log activity)\n",
        encoding="utf-8",
    )
    # llm_invoker returns garbage → unknown fallback path.
    entry = gen_handled._handle_timeout_test(
        {"test_node": "tests/test_x.py::test_y", "status": "retriable_error",
         "error_type": "timeout", "error_message": ""},
        batch_dir,
        llm_invoker=lambda p: "not json at all",
    )
    assert entry is not None
    assert entry["final_status"] == "ignored"
    assert entry["ignored_reason"].startswith("分类不明")
    assert (
        entry["resolution"]["dependency_classification"]["classification"]
        == "unknown"
    )


def test_handle_timeout_test_not_dep_stall_returns_none(tmp_path):
    """not_dep_stall means Stage 2 retries; fixer must not emit an entry."""
    batch_dir = tmp_path
    (batch_dir / "summary.txt").write_text(
        "AssertionError: shape mismatch\n", encoding="utf-8"
    )

    def fake_llm(prompt: str) -> str:
        return json.dumps({
            "classification": "not_dep_stall",
            "evidence": "AssertionError: shape mismatch",
            "dependency_hint": None,
        })

    entry = gen_handled._handle_timeout_test(
        {"test_node": "t::x", "status": "retriable_error",
         "error_type": "timeout", "error_message": ""},
        batch_dir,
        llm_invoker=fake_llm,
    )
    assert entry is None


def test_handle_timeout_test_llm_raises_yields_unknown(tmp_path):
    """An exception from llm_invoker must not bubble — falls back to unknown."""
    batch_dir = tmp_path
    (batch_dir / "summary.txt").write_text("idle log line\n", encoding="utf-8")

    def boom(prompt: str) -> str:
        raise RuntimeError("LLM down")

    entry = gen_handled._handle_timeout_test(
        {"test_node": "t::x", "status": "retriable_error",
         "error_type": "timeout", "error_message": ""},
        batch_dir,
        llm_invoker=boom,
    )
    assert entry is not None
    assert entry["final_status"] == "ignored"
    assert (
        entry["resolution"]["dependency_classification"]["classification"]
        == "unknown"
    )
