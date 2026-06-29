"""Tests for merge_batch_manifests auto-discovery"""
import pytest
import json
from pathlib import Path
from tasks.ut.scripts.merge_batch_manifests import discover_run_files


def test_discover_success(tmp_path):
    """Test successful discovery of manifest and batches."""
    run_dir = tmp_path / "ut-test"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"tests": []}))
    batches_dir = run_dir / "batches"
    batches_dir.mkdir()
    batch_dir = batches_dir / "batch_p1"
    batch_dir.mkdir()
    (batch_dir / "batch_results.json").write_text(json.dumps({"batch_id": "p1"}))

    manifest_path, batch_dirs = discover_run_files(run_dir)
    assert manifest_path.name == "manifest.json"
    assert len(batch_dirs) == 1
    assert batch_dirs[0].name == "batch_p1"


def test_discover_multiple_batches(tmp_path):
    """Test discovery of multiple batch directories."""
    run_dir = tmp_path / "ut-test"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"tests": []}))
    batches_dir = run_dir / "batches"
    batches_dir.mkdir()

    # Create 3 batches
    for i in range(1, 4):
        batch_dir = batches_dir / f"batch_p{i}"
        batch_dir.mkdir()
        (batch_dir / "batch_results.json").write_text(json.dumps({"batch_id": f"p{i}"}))

    manifest_path, batch_dirs = discover_run_files(run_dir)
    assert len(batch_dirs) == 3
    # Should be sorted
    assert [b.name for b in batch_dirs] == ["batch_p1", "batch_p2", "batch_p3"]


def test_discover_missing_manifest(tmp_path):
    """Test discovery raises FileNotFoundError when manifest missing."""
    run_dir = tmp_path / "ut-test"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError) as exc_info:
        discover_run_files(run_dir)

    assert "manifest.json not found" in str(exc_info.value)


def test_discover_missing_batches_dir(tmp_path):
    """Test discovery raises FileNotFoundError when batches/ missing."""
    run_dir = tmp_path / "ut-test"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"tests": []}))

    with pytest.raises(FileNotFoundError) as exc_info:
        discover_run_files(run_dir)

    assert "batches/ not found" in str(exc_info.value)


def test_discover_empty_batches(tmp_path):
    """Test discovery raises FileNotFoundError when no batch_results.json found."""
    run_dir = tmp_path / "ut-test"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"tests": []}))
    batches_dir = run_dir / "batches"
    batches_dir.mkdir()
    # Empty batch dir without batch_results.json
    batch_dir = batches_dir / "batch_p1"
    batch_dir.mkdir()

    with pytest.raises(FileNotFoundError) as exc_info:
        discover_run_files(run_dir)

    assert "No batch_results.json found" in str(exc_info.value)


def test_discover_skips_dirs_without_results(tmp_path):
    """Test discovery skips directories without batch_results.json."""
    run_dir = tmp_path / "ut-test"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"tests": []}))
    batches_dir = run_dir / "batches"
    batches_dir.mkdir()

    # Valid batch
    valid_batch = batches_dir / "batch_p1"
    valid_batch.mkdir()
    (valid_batch / "batch_results.json").write_text(json.dumps({"batch_id": "p1"}))

    # Invalid batch (no results file)
    invalid_batch = batches_dir / "batch_p2"
    invalid_batch.mkdir()

    manifest_path, batch_dirs = discover_run_files(run_dir)
    assert len(batch_dirs) == 1
    assert batch_dirs[0].name == "batch_p1"