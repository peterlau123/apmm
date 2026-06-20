"""Tests for Phase 5.2: filter retriable_error, resolve remote_log, [auto-fix] prefix."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ANALYZE = REPO_ROOT / "skills" / "ut" / "failure-handler" / "scripts" / "analyze_failures.py"
APPLY = REPO_ROOT / "skills" / "ut" / "failure-handler" / "scripts" / "apply_patch_remote.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


analyze = _load("ut_fh_analyze_v5", ANALYZE)
apply_patch = _load("ut_fh_apply_v5", APPLY)


def test_retriable_error_not_processed():
    out = analyze.filter_processable([
        {"test_id": "t1", "status": "retriable_error"},
        {"test_id": "t2", "status": "failed"},
        {"test_id": "t3", "status": "error"},
        {"test_id": "t4", "status": "passed"},
    ])
    ids = [t["test_id"] for t in out]
    assert "t1" not in ids
    assert "t2" in ids
    assert "t3" in ids
    assert "t4" not in ids


def test_resolve_remote_log_via_last_batch_id(tmp_path):
    runs_dir = tmp_path / "runs_dir"
    batch_dir = runs_dir / "b42"
    batch_dir.mkdir(parents=True)
    remote_log = {
        "raw_log_path": "/gpfs/gcsp/M2.7_verify/vllm/ut_logs/b42/raw.log",
        "summary_path": str(batch_dir / "summary.txt"),
    }
    (batch_dir / "batch_results.json").write_text(
        json.dumps({"batch_id": "b42", "remote_log": remote_log}),
        encoding="utf-8",
    )

    got = analyze.resolve_remote_log({"test_id": "t1", "last_batch_id": "b42"}, run_dir=runs_dir)
    assert got == remote_log


def test_resolve_remote_log_missing_returns_none(tmp_path):
    assert analyze.resolve_remote_log({"test_id": "t1"}, run_dir=tmp_path) is None
    assert (
        analyze.resolve_remote_log({"test_id": "t1", "last_batch_id": "nope"}, run_dir=tmp_path)
        is None
    )


def test_auto_fix_commit_prefix():
    assert apply_patch.build_commit_message("fix: x").startswith("[auto-fix]")
    assert apply_patch.build_commit_message("fix: x") == "[auto-fix] fix: x"
    # idempotent
    assert apply_patch.build_commit_message("[auto-fix] y") == "[auto-fix] y"


def test_entry_invokes_branch_check_and_filters(monkeypatch, tmp_path):
    calls = []

    def fake_ensure(expected, repo_path):
        calls.append((expected, repo_path))

    monkeypatch.setattr(analyze, "ensure_on_branch", fake_ensure)

    out = analyze.analyze_failed_tests_v5(
        [
            {"test_id": "t1", "status": "retriable_error"},
            {"test_id": "t2", "status": "failed"},
            {"test_id": "t3", "status": "error"},
        ],
        run_dir=tmp_path,
    )

    assert calls == [("2.5.1_ut_verify", "/gpfs/gcsp/M2.7_verify/vllm")]
    ids = [t["test_id"] for t in out]
    assert ids == ["t2", "t3"]


def test_entry_attaches_remote_log(monkeypatch, tmp_path):
    monkeypatch.setattr(analyze, "ensure_on_branch", lambda *a, **k: None)
    bdir = tmp_path / "b9"
    bdir.mkdir()
    (bdir / "batch_results.json").write_text(
        json.dumps({"remote_log": {"raw_log_path": "/r/x.log"}}), encoding="utf-8"
    )
    out = analyze.analyze_failed_tests_v5(
        [{"test_id": "t1", "status": "failed", "last_batch_id": "b9"}],
        run_dir=tmp_path,
    )
    assert out[0]["remote_log"] == {"raw_log_path": "/r/x.log"}


def test_entry_propagates_branch_check_error(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("vLLM HEAD on master, expected 2.5.1_ut_verify")

    monkeypatch.setattr(analyze, "ensure_on_branch", boom)
    with pytest.raises(RuntimeError, match="HEAD on master"):
        analyze.analyze_failed_tests_v5(
            [{"test_id": "t1", "status": "failed"}], run_dir=tmp_path
        )
