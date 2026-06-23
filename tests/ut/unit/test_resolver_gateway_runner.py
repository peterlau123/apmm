"""Unit tests for resolver_gateway_runner.resolve_one + run_one_iteration.

Uses an in-memory FakeKanbanClient and a stub sync_module to keep tests fast
and independent of any t_ascend/t_h20 connectivity.

Spec: tasks/ut/docs/incidents/2026-06-23-l4-postmortem-and-fixes.md §4.6
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RGR_PATH = PROJECT_ROOT / "skills" / "ut" / "dependency-resolver" / "scripts" / "resolver_gateway_runner.py"


@pytest.fixture(scope="module")
def rgr():
    spec = importlib.util.spec_from_file_location("resolver_gateway_runner", RGR_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["resolver_gateway_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Stub sync_module — mimics two_stage_sync API surface ──────────────────────


@dataclass
class _StubResult:
    status: str
    model: str
    local_path: str | None = None
    reason: str | None = None
    detail: str | None = None


class _StubSync:
    """A drop-in replacement for the two_stage_sync module."""
    def __init__(self, status, **kw):
        self._status = status
        self._kw = kw

    def sync_model(self, model, **_):
        return _StubResult(status=self._status, model=model, **self._kw)


# ── FakeKanbanClient ──────────────────────────────────────────────────────────


class FakeKanban:
    def __init__(self, task=None):
        self._task = task
        self.released_ready = []
        self.released_ignored = []

    def claim_pending_delegate(self):
        t, self._task = self._task, None
        return t

    def release_ready(self, task_id, resolution):
        self.released_ready.append((task_id, resolution))

    def release_ignored(self, task_id, resolution, ignored_reason):
        self.released_ignored.append((task_id, resolution, ignored_reason))


def _model_task(dep_id="meta-llama/Llama-3.2-1B-Instruct"):
    return {
        "task_id": "t1",
        "test_node": "tests/test_a.py::test_x",
        "resolution": {
            "action": "delegate_to_dependency_resolver",
            "dependency_id": dep_id,
            "dependency_type": "model",
        },
    }


# ── resolve_one ───────────────────────────────────────────────────────────────


def test_resolve_one_resolved(rgr):
    sync = _StubSync(status="resolved", local_path="/gpfs/.../m")
    decision = rgr.resolve_one(_model_task(), sync_module=sync)
    assert decision.action == "release_ready"
    assert decision.resolution["status"] == "resolved"
    assert decision.resolution["local_path"] == "/gpfs/.../m"
    assert decision.ignored_reason is None


def test_resolve_one_failed_offline(rgr):
    sync = _StubSync(status="failed_offline",
                     reason="download_failed", detail="bad happened")
    decision = rgr.resolve_one(_model_task(), sync_module=sync)
    assert decision.action == "release_ignored"
    assert decision.resolution["status"] == "failed_offline"
    assert decision.resolution["failure_status"] == "failed_offline"
    assert "download_failed" in decision.ignored_reason
    assert decision.ignored_reason.startswith("offline_unfixable:")


def test_resolve_one_auth_failed(rgr):
    sync = _StubSync(status="auth_failed",
                     reason="hf_auth_failed", detail="401 gated")
    decision = rgr.resolve_one(_model_task(), sync_module=sync)
    assert decision.action == "release_ignored"
    assert "hf_auth_failed" in decision.ignored_reason


def test_resolve_one_timeout(rgr):
    sync = _StubSync(status="timeout",
                     reason="download budget 1800s exceeded")
    decision = rgr.resolve_one(_model_task(), sync_module=sync)
    assert decision.action == "release_ignored"
    assert "exceeded" in decision.ignored_reason or "timeout" in decision.ignored_reason


def test_resolve_one_missing_dep_id(rgr):
    """Malformed task — defend without invoking sync."""
    task = _model_task()
    task["resolution"]["dependency_id"] = None

    class _NoCall:
        def sync_model(self, *a, **kw): raise AssertionError("must not call sync")

    decision = rgr.resolve_one(task, sync_module=_NoCall())
    assert decision.action == "release_ignored"
    assert "missing dependency_id" in decision.ignored_reason


def test_resolve_one_unsupported_type(rgr):
    """Non-model types are deferred — out of scope for M2."""
    task = _model_task()
    task["resolution"]["dependency_type"] = "package"

    class _NoCall:
        def sync_model(self, *a, **kw): raise AssertionError("must not call sync for package")

    decision = rgr.resolve_one(task, sync_module=_NoCall())
    assert decision.action == "release_ignored"
    assert "dependency_type=package" in decision.ignored_reason


# ── run_one_iteration ─────────────────────────────────────────────────────────


def test_run_one_iteration_no_task(rgr):
    client = FakeKanban(task=None)
    out = rgr.run_one_iteration(client)
    assert out is None
    assert client.released_ready == []
    assert client.released_ignored == []


def test_run_one_iteration_releases_ready(rgr):
    client = FakeKanban(task=_model_task())
    sync = _StubSync(status="resolved", local_path="/gpfs/.../m")
    decision = rgr.run_one_iteration(client, sync_module=sync)
    assert decision is not None
    assert len(client.released_ready) == 1
    assert len(client.released_ignored) == 0
    task_id, resolution = client.released_ready[0]
    assert task_id == "t1"
    assert resolution["status"] == "resolved"


def test_run_one_iteration_releases_ignored(rgr):
    client = FakeKanban(task=_model_task())
    sync = _StubSync(status="auth_failed",
                     reason="hf_auth_failed", detail="401")
    rgr.run_one_iteration(client, sync_module=sync)
    assert len(client.released_ready) == 0
    assert len(client.released_ignored) == 1
    task_id, resolution, reason = client.released_ignored[0]
    assert task_id == "t1"
    assert "hf_auth_failed" in reason


def test_no_per_task_retry(rgr):
    """Contract: resolver does NOT bounce back to fixer; ignored is terminal."""
    client = FakeKanban(task=_model_task())
    sync = _StubSync(status="failed_offline", reason="x")
    rgr.run_one_iteration(client, sync_module=sync)
    assert rgr.run_one_iteration(client, sync_module=sync) is None
    assert client.released_ready == []
    assert len(client.released_ignored) == 1
