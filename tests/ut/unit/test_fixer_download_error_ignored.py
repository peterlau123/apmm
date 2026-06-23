"""Tests for generate_handled_manifest dependency/download_error handling.

Per L4 postmortem §4 (resolution: user-chosen Option E):
  Tests that fail with dependency / download_error must be marked
  `final_status=ignored` with `ignored_reason="模型需要下载需要人工处理: <dep>"` —
  NOT pending (which would hang the workflow waiting for a non-existent resolver).

Spec: tasks/ut/docs/incidents/2026-06-23-l4-postmortem-and-fixes.md §4
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GHM_PATH = PROJECT_ROOT / "skills" / "ut" / "failure-handler" / "scripts" / "generate_handled_manifest.py"


@pytest.fixture(scope="module")
def ghm():
    spec = importlib.util.spec_from_file_location("generate_handled_manifest", GHM_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_handled_manifest"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_input(tmp_path, tests):
    data = {"batch_id": "batch_20260623_120000", "tests": tests}
    p = tmp_path / "batch_results.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _call(ghm, inp):
    """Call without batch_dir to skip schema-validated file write."""
    return ghm.generate_handled_manifest(
        batch_id="batch_20260623_120000",
        batch_results_path=inp,
    )


# ── Regression: model_missing must produce ignored, not pending ───────────────


def test_download_error_marks_ignored_not_pending(ghm, tmp_path):
    """The exact regression from L4 run ut-20260623-105441."""
    inp = _write_input(tmp_path, [{
        "test_node": "tests/foo.py::test_bar",
        "status": "error",
        "error_type": "download_error",
        "error_message": "Model meta-llama/Llama-3.2-1B-Instruct not found in HF cache",
    }])
    out = _call(ghm, inp)
    test = out["tests"][0]
    assert test["final_status"] == "ignored", \
        f"download_error must NOT produce pending (would hang workflow); got {test['final_status']}"
    assert "模型需要下载需要人工处理" in test["ignored_reason"]
    assert "meta-llama/Llama-3.2-1B-Instruct" in test["ignored_reason"]
    assert out["stats"]["pending"] == 0
    assert out["stats"]["ignored"] == 1


def test_dependency_error_marks_ignored(ghm, tmp_path):
    inp = _write_input(tmp_path, [{
        "test_node": "tests/foo.py::test_baz",
        "status": "failed",
        "error_type": "dependency",
        "error_message": "ModuleNotFoundError: No module named 'transformers'",
    }])
    out = _call(ghm, inp)
    test = out["tests"][0]
    assert test["final_status"] == "ignored"
    assert "模型需要下载需要人工处理" in test["ignored_reason"]
    assert out["stats"]["pending"] == 0


def test_no_action_dependency_resolver_in_output(ghm, tmp_path):
    """The 'action: dependency_resolver' tag must be gone — no consumer exists."""
    inp = _write_input(tmp_path, [{
        "test_node": "tests/x.py::test_y",
        "status": "error",
        "error_type": "download_error",
        "error_message": "Model X not found",
    }])
    out = _call(ghm, inp)
    assert out["tests"][0].get("action") != "dependency_resolver", \
        "action=dependency_resolver tag must be removed (no runner consumes it)"


# ── Other branches unaffected — sanity ────────────────────────────────────────


def test_network_still_ignored(ghm, tmp_path):
    inp = _write_input(tmp_path, [{
        "test_node": "tests/n.py::test_t",
        "status": "failed",
        "error_type": "network",
        "error_message": "timeout",
    }])
    out = _call(ghm, inp)
    assert out["tests"][0]["final_status"] == "ignored"
    assert out["tests"][0]["ignored_reason"] == "network timeout"


def test_functional_still_failed(ghm, tmp_path):
    inp = _write_input(tmp_path, [{
        "test_node": "tests/f.py::test_g",
        "status": "failed",
        "error_type": "functional",
        "error_message": "AssertionError",
    }])
    out = _call(ghm, inp)
    assert out["tests"][0]["final_status"] == "failed"