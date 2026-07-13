"""Contract test placeholders for workflow-loop-core (Phase 6, v5).

loop_core is currently SKILL.md-only — concrete Python wiring lands in the
channel SKILLs (ut/workflow supervisor, hermes-workflow) and in ut_runner.
These placeholders document the contract; remove the skips once the wiring
exists.
"""
import pytest


@pytest.mark.skip(reason="loop_core SKILL-only; wiring lands with channel implementations")
def test_supervisor_must_provide_handle_checkpoint():
    """The linear-mode supervisor (ut/workflow) MUST inject handle_checkpoint.

    Without it, loop_core has no way to emit progress (Feishu card / log /
    kanban update). loop_core should refuse to start when the callback is
    missing rather than silently swallow progress events.
    """


@pytest.mark.skip(reason="loop_core SKILL-only; wiring lands with channel implementations")
def test_terminal_pending_zero_returns_completed():
    """When manifest_stats.pending == 0 and running == 0, check_terminal_conditions
    must return (True, 'completed', reason). loop_core then finalizes state and
    exits. This is the only happy-path exit.
    """
