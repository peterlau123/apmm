"""Unit tests for two_stage_sync.sync_model.

All external calls (agent.py subprocesses, download_model) are monkeypatched.
Tests assert the SyncResult contract from postmortem §4.3.2.

Spec: tasks/ut/docs/incidents/2026-06-23-l4-postmortem-and-fixes.md §4.6
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TSS_PATH = PROJECT_ROOT / "skills" / "ut" / "dependency-resolver" / "scripts" / "two_stage_sync.py"


@pytest.fixture(scope="module")
def tss():
    spec = importlib.util.spec_from_file_location("two_stage_sync", TSS_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["two_stage_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ok():
    class R:
        returncode = 0
        stdout = "OK"
        stderr = ""
    return R()


def _fail():
    class R:
        returncode = 1
        stdout = "MISSING"
        stderr = "boom"
    return R()


# ── Happy path ────────────────────────────────────────────────────────────────


def test_sync_resolved(tss, monkeypatch):
    monkeypatch.setattr(tss, "_run_agent", lambda profile, cmd, t: _ok())
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "success", "model": model,
                                          "path": "/gpfs/.../model"})
    res = tss.sync_model("meta-llama/Llama-3.2-1B-Instruct")
    assert res.status == "resolved"
    assert res.local_path == "/gpfs/.../model"
    assert res.reason is None


# ── Failure paths ─────────────────────────────────────────────────────────────


def test_t_ascend_unreachable(tss, monkeypatch):
    monkeypatch.setattr(tss, "_run_agent",
                        lambda profile, cmd, t: _fail())
    def _no_call(*a, **kw):
        raise AssertionError("download should not be called when t_ascend unreachable")
    monkeypatch.setattr(tss, "_download_on_t_ascend", _no_call)
    res = tss.sync_model("any/model")
    assert res.status == "network_unreachable"
    assert "t_ascend" in res.reason


def test_download_timeout(tss, monkeypatch):
    monkeypatch.setattr(tss, "_run_agent", lambda profile, cmd, t: _ok())
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "timeout", "model": model,
                                          "error": "Download timeout after 1800s"})
    res = tss.sync_model("big/model", budget_seconds=1800)
    assert res.status == "timeout"
    assert "1800" in res.reason or "timeout" in res.reason.lower()


def test_auth_gated_model(tss, monkeypatch):
    monkeypatch.setattr(tss, "_run_agent", lambda profile, cmd, t: _ok())
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "error", "model": model,
                                          "error": "HTTP 401 - gated model"})
    res = tss.sync_model("meta-llama/secret")
    assert res.status == "auth_failed"
    assert res.reason == "hf_auth_failed"


def test_disk_full(tss, monkeypatch):
    monkeypatch.setattr(tss, "_run_agent", lambda profile, cmd, t: _ok())
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "error", "model": model,
                                          "error": "No space left on device"})
    res = tss.sync_model("big/model")
    assert res.status == "disk_full"


def test_download_succeeds_but_t_h20_cannot_see(tss, monkeypatch):
    """GPFS mount glitch — download OK on ascend, invisible on h20."""
    call_log = []

    def _agent(profile, cmd, t):
        call_log.append(profile)
        if profile == "t_h20":
            return _fail()
        return _ok()

    monkeypatch.setattr(tss, "_run_agent", _agent)
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "success", "model": model,
                                          "path": "/gpfs/.../model"})
    res = tss.sync_model("any/model")
    assert res.status == "failed_offline"
    assert "t_h20" in res.reason
    assert call_log == ["t_ascend", "t_h20"]


def test_generic_download_error(tss, monkeypatch):
    monkeypatch.setattr(tss, "_run_agent", lambda profile, cmd, t: _ok())
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "error", "model": model,
                                          "error": "transient network glitch"})
    res = tss.sync_model("any/model")
    assert res.status == "failed_offline"
    assert res.reason == "download_failed"


# ── Result serialization ──────────────────────────────────────────────────────


def test_sync_result_json_contract(tss):
    r = tss.SyncResult(status="resolved", model="x/y", local_path="/p")
    d = r.to_json()
    assert set(d) == {"status", "model", "local_path", "reason", "detail"}
    assert d["status"] == "resolved"
    assert d["reason"] is None
    assert d["detail"] is None


def test_detail_truncated_to_300(tss, monkeypatch):
    """Regression guard — detail must not echo unbounded upstream errors."""
    monkeypatch.setattr(tss, "_run_agent", lambda profile, cmd, t: _ok())
    monkeypatch.setattr(tss, "_download_on_t_ascend",
                        lambda model, b: {"status": "error", "model": model,
                                          "error": "x" * 500})
    res = tss.sync_model("any/model")
    assert res.detail is not None and len(res.detail) <= 300
