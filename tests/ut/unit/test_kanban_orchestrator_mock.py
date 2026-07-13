"""Tests for Kanban orchestrator_round with mocked gateway/board.

Task 2.3: Mock gateway/board responses using unittest.mock.
Tests multi-round reconcile + select scenarios:
  - Round 1: select tests, dispatch to gateways
  - Round 2: reconcile completed work, select remaining
  - Test dependency chain handling
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ORCH_PATH = PROJECT_ROOT / "skills" / "ut" / "hermes-workflow" / "scripts" / "orchestrator_round.py"
UPDATE_STATUS = PROJECT_ROOT / "skills" / "ut" / "manifest-updater" / "scripts" / "update_status.py"
BATCH_SELECTOR = PROJECT_ROOT / "skills" / "ut" / "batch-selector" / "scripts" / "generate_batch.py"


@pytest.fixture(scope="module")
def orch():
    """Import ut_runner.py by file path."""
    sys.path.insert(0, str(ORCH_PATH.parent))
    sys.path.insert(0, str(ORCH_PATH.parent.parent.parent))
    spec = importlib.util.spec_from_file_location("orchestrator_round", ORCH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_manifest(tests):
    """Create a minimal manifest dict."""
    return {"version": "2.0", "tests": tests, "statistics": {}}


def _make_test(test_id, status="pending", retry_count=0, max_retry=3, deps=None):
    """Create a minimal test entry."""
    t = {"test_id": test_id, "status": status, "retry_count": retry_count, "max_retry": max_retry, "last_batch_id": None}
    if deps:
        t["dependencies"] = deps
    return t


class TestOrchestratorRoundMultiRound:
    """Test multi-round orchestrator behavior with mocked workers."""

    def test_round1_select_tests_no_prev_batch(self, hr, tmp_path):
        """Round 1: No prev batch → select pending tests."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending"),
            _make_test("t3", status="passed"),
        ])))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=None,
            batch_size=8,
        )

        assert result["completed"] is False
        assert result["next_batch"]["selected_count"] == 2
        assert len(list(run_dir.glob("batch_*"))) == 1

    def test_round2_reconcile_prev_batch_results(self, hr, tmp_path):
        """Round 2: Reconcile prev batch results → update manifest → select remaining."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending"),
        ])))

        prev_batch_dir = run_dir / "batch_0001"
        prev_batch_dir.mkdir()
        (prev_batch_dir / "batch_results.json").write_text(json.dumps({
            "batch_id": "batch_0001",
            "tests": [{"test_id": "t1", "status": "passed"}],
        }))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=prev_batch_dir,
            batch_size=8,
        )

        manifest = json.loads(manifest_path.read_text())
        t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
        assert t1["status"] == "passed"
        assert result["completed"] is False
        assert result["next_batch"]["selected_count"] == 1
        assert result["next_batch"]["tests"][0]["test_id"] == "t2"

    def test_round3_completed_when_nothing_pending(self, hr, tmp_path):
        """Round 3: All tests passed → completed=True, next_batch=None."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="passed"),
            _make_test("t2", status="passed"),
        ])))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=None,
            batch_size=8,
        )

        assert result["completed"] is True
        assert result["next_batch"] is None

    def test_reconcile_with_retriable_error(self, hr, tmp_path):
        """Reconcile retriable error → increment retry_count, status stays retriable_error."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending", retry_count=0, max_retry=3),
        ])))

        prev_batch_dir = run_dir / "batch_0001"
        prev_batch_dir.mkdir()
        (prev_batch_dir / "batch_results.json").write_text(json.dumps({
            "batch_id": "batch_0001",
            "tests": [{"test_id": "t1", "status": "retriable_error", "error_type": "oom"}],
        }))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=prev_batch_dir,
            batch_size=8,
        )

        manifest = json.loads(manifest_path.read_text())
        t1 = manifest["tests"][0]
        assert t1["status"] == "retriable_error"
        assert t1["retry_count"] == 1
        assert t1["error_type"] == "oom"
        assert result["completed"] is False
        assert result["next_batch"]["selected_count"] == 1


class TestOrchestratorRoundDependencyChains:
    """Test dependency chain handling with mocked batch selector."""

    def test_dependency_not_checked_by_selector(self, hr, tmp_path):
        """Batch selector does NOT check dependencies - both tests selected."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending", deps=["t1"]),
        ])))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=None,
            batch_size=8,
        )

        assert result["next_batch"]["selected_count"] == 2

    def test_dependency_resolved_after_reconcile(self, hr, tmp_path):
        """After t1 passes, t2 becomes selectable."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending", deps=["t1"]),
        ])))

        prev_batch_dir = run_dir / "batch_0001"
        prev_batch_dir.mkdir()
        (prev_batch_dir / "batch_results.json").write_text(json.dumps({
            "batch_id": "batch_0001",
            "tests": [{"test_id": "t1", "status": "passed"}],
        }))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=prev_batch_dir,
            batch_size=8,
        )

        manifest = json.loads(manifest_path.read_text())
        t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
        assert t1["status"] == "passed"
        assert result["next_batch"]["selected_count"] == 1
        assert result["next_batch"]["tests"][0]["test_id"] == "t2"

    def test_handled_tests_applies_status_override(self, hr, tmp_path):
        """Handled tests should apply status override from handled_tests.json."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending"),
        ])))

        prev_batch_dir = run_dir / "batch_0001"
        prev_batch_dir.mkdir()
        (prev_batch_dir / "batch_results.json").write_text(json.dumps({
            "batch_id": "batch_0001",
            "tests": [{"test_id": "t1", "status": "failed"}],
        }))
        (prev_batch_dir / "handled_tests.json").write_text(json.dumps({
            "tests": [{"test_id": "t1", "status": "ignored", "ignore_reason": "manually ignored"}],
        }))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=prev_batch_dir,
            batch_size=8,
        )

        manifest = json.loads(manifest_path.read_text())
        t1 = next(t for t in manifest["tests"] if t["test_id"] == "t1")
        assert t1["status"] == "ignored"
        assert t1["ignore_reason"] == "manually ignored"
        assert result["next_batch"]["selected_count"] == 1
        assert result["next_batch"]["tests"][0]["test_id"] == "t2"


class TestOrchestratorRoundBatchSizing:
    """Test batch size handling."""

    def test_batch_size_respected(self, hr, tmp_path):
        """Batch size limit should be respected."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending"),
            _make_test("t3", status="pending"),
            _make_test("t4", status="pending"),
        ])))

        result = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=None,
            batch_size=2,
        )

        assert result["next_batch"]["selected_count"] == 2

    def test_small_batch_multiple_rounds(self, hr, tmp_path):
        """Small batch size requires multiple rounds to complete all tests."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(_make_manifest([
            _make_test("t1", status="pending"),
            _make_test("t2", status="pending"),
            _make_test("t3", status="pending"),
        ])))

        result1 = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=None,
            batch_size=1,
        )
        assert result1["next_batch"]["selected_count"] == 1

        batch_dir = run_dir / "batch_0001"
        (batch_dir / "batch_results.json").write_text(json.dumps({
            "batch_id": "batch_0001",
            "tests": [{"test_id": result1["next_batch"]["tests"][0]["test_id"], "status": "passed"}],
        }))

        manifest = json.loads(manifest_path.read_text())
        for t in manifest["tests"]:
            if t["test_id"] == result1["next_batch"]["tests"][0]["test_id"]:
                t["status"] = "passed"
        manifest_path.write_text(json.dumps(manifest))

        result2 = orch.orchestrator_round(
            run_dir=run_dir,
            manifest_path=manifest_path,
            prev_batch_dir=batch_dir,
            batch_size=1,
        )
        assert result2["completed"] is False
        assert result2["next_batch"]["selected_count"] == 1