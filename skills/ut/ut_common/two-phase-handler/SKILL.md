---
name: two-phase-handler
description: "Phase 2 of the two-phase UT workflow: statistical analysis of failed test batches + agent-assisted retry (after human decision). Invoked by Supervisor after Phase 1 completes."
version: 2.0.0
when_to_use: "Called by Supervisor to run Phase 2 Stage 1 (statistics) and Stage 2 (retry execution)."
---

# Two-phase Handler (v2.0)

Implementation code extracted to `scripts/`. This SKILL.md contains only contracts, workflow overview, and usage reference.

## HARD CONTRACT (4 rules)

1. **Phase separation mandatory.** Stage 1 and Stage 2 are separate invocations. Never combine.
2. **Human decision checkpoint immutable.** Supervisor MUST wait for `user_decision.json` between stages. No auto-proceed.
3. **test_load is the working dataset.** All stats from test_load only. Never fabricate error_type.
4. **Retry follows test_load contract.** Each retry produces `batch_results.json` + incremental test_load update.

## Dependencies

- `skills/ut/unit-test-executor/scripts/execute_batch.py` — batch executor
- `skills/ut/shared/update_test_load_two_phase.py` — test_load update
- `skills/ut/shared/manifest_schema.json` — schema

## Usage

### Stage 1: Statistical Analysis

```bash
python scripts/phase2_stage1.py --run-dir <run_dir>
```

Outputs: `phase2_stage1_report.json` + `phase2_stage1_report.md`

### Human Decision Checkpoint

Create `user_decision.json` in run dir:

```json
{"decision_method": "retry_error_types", "retry_error_types": ["timeout"]}
```

| method | Description | Extra |
|--------|-------------|-------|
| `retry_error_types` | Retry by error type (recommended) | `retry_error_types: string[]` |
| `retry_specific_batches` | Retry specific batches | `retry_specific_batches: string[]` |
| `retry_all` | Retry ALL failed batches | `retry_all: true` |
| `skip_all` | End workflow without retry | (none) |

### Stage 2: Retry Execution

```bash
python scripts/phase2_stage2.py --run-dir <run_dir> --user-decision <run_dir>/user_decision.json
```

Outputs: `phase2_stage2_report.json`

## Error Type Classification

| Type | Priority | Strategy |
|------|----------|----------|
| `network`, `oom`, `timeout` | P0 | Retry / increase timeout / reduce model |
| `dependency`, `resource`, `download_error`, `version` | P1 | Check env, install deps, verify paths |
| `functional`, `assertion`, `collection`, `other` | P2 | Analyze logic, check test defs |

## Related

- [scripts/phase2_stage1.py](scripts/phase2_stage1.py)
- [scripts/phase2_stage2.py](scripts/phase2_stage2.py)
- [Two-phase Design](../../tasks/ut/docs/designs/2026-07-06-two-phase-strategy-design.md)
- [unit-test-executor/SKILL.md](../unit-test-executor/SKILL.md)

---

*Version: 2.0.0 — Extracted ~950 lines of inline code to scripts/. SKILL.md now 70 lines.*
