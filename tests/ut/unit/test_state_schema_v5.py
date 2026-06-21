"""Tests for v5 workflow_state schema additions.

- pending_config (top-level object, additionalProperties: true) is allowed.
- status enum no longer accepts 'reconnecting' anywhere (workflow.status
  was rewritten to v5 enum; bastion.status had reconnecting removed).
"""
import pytest
from jsonschema import ValidationError

from skills.ut.shared.validate_schema import validate_state


def _minimal_state(**overrides):
    """Build a minimally valid workflow_state per workflow_state_schema.json."""
    base = {
        "workflow": {
            "name": "ut",
            "version": "5.0",
            "test_name": "ut",
            "started_at": "2026-06-20T00:00:00Z",
            "status": "running",
        },
        "current_stage": "select_batch",
        "iteration": 0,
        "paths": {
            "run_dir": "/runs/ut-x",
            "workflow_yaml": ".agents/workflow.yaml",
            "manifest": "/runs/ut-x/manifest.json",
            "batches_dir": "/runs/ut-x/batches",
            "workflow_state": "/runs/ut-x/workflow_state.json",
        },
        "stats": {
            "total_tests": 0, "passed": 0, "failed": 0,
            "error": 0, "ignored": 0, "pending": 0,
        },
        "current_batch": {"batch_id": None, "size": 0, "started_at": None},
        "flags": {},
        "last_update": "2026-06-20T00:00:00Z",
    }
    base.update(overrides)
    return base


# --- Task 9.2 ---

def test_pending_config_top_level_allowed():
    state = _minimal_state(pending_config={"batch_size": 16, "anything": "ok"})
    validate_state(state)  # should not raise


def test_pending_config_empty_object_allowed():
    state = _minimal_state(pending_config={})
    validate_state(state)


def test_workflow_status_reconnecting_rejected():
    """v5 removed 'reconnecting' from the workflow.status enum."""
    state = _minimal_state()
    state["workflow"]["status"] = "reconnecting"
    with pytest.raises(ValidationError):
        validate_state(state)


def test_workflow_status_initialized_rejected():
    """v5 dropped 'initialized' from workflow.status enum."""
    state = _minimal_state()
    state["workflow"]["status"] = "initialized"
    with pytest.raises(ValidationError):
        validate_state(state)


def test_workflow_status_v5_values_accepted():
    for value in ("running", "paused", "waiting_otp", "completed", "stopped", "failed"):
        state = _minimal_state()
        state["workflow"]["status"] = value
        validate_state(state)


def test_bastion_status_reconnecting_rejected():
    """v5 removed 'reconnecting' from bastion.status enum too."""
    state = _minimal_state(bastion={
        "status": "reconnecting",
        "profile": "t_h20",
    })
    with pytest.raises(ValidationError):
        validate_state(state)
