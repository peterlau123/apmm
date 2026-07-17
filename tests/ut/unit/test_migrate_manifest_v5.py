"""Tests for v5 manifest migration: backfill max_retry and last_batch_id."""
from skills.ut.ut_common.migrate_manifest import migrate_manifest


def test_old_manifest_gets_max_retry_default():
    old = {"version": "2.0", "tests": [{"test_id": "t1", "status": "pending", "retry_count": 0}], "statistics": {}}
    migrated = migrate_manifest(old, default_max_retry=3)
    assert migrated["tests"][0]["max_retry"] == 3
    assert migrated["tests"][0]["last_batch_id"] is None


def test_existing_max_retry_not_overwritten():
    existing = {"version": "2.0", "tests": [{"test_id": "t1", "status": "pending",
                "retry_count": 0, "max_retry": 5}], "statistics": {}}
    migrated = migrate_manifest(existing, default_max_retry=3)
    assert migrated["tests"][0]["max_retry"] == 5
