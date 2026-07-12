---
name: unit-test-collector
description: Worker Agent - test_list.txt to manifest.json (schema-validated)
version: 2.2.0
when_to_use: Supervisor calls at Stage 1 to generate manifest.json from test_list.txt
---

# UT Test Collector (Worker Agent v2.2)

## Role

Parse test_list.txt, generate manifest.json conforming to manifest_schema.json.
This is a one-time step (not in the loop).

`
Input:  test_list.txt (one test node per line)
Output: manifest.json (schema-validated, all tests status=pending)
`

## Script

skills/ut/terminal-workflow/scripts/init_workflow_state.py
- Function: create_manifest_from_test_list(test_list_path, manifest_path)
- Called by: init_workflow_state.py during run initialization
- Schema: skills/ut/shared/manifest_schema.json
- Validation: skills/ut/shared/validate_schema.py::validate_and_write

> **Note**: scripts/collect.py is deprecated. It was an early implementation
> using local pytest --collect-only, which is not used in the workflow.
> Manifest generation is handled by init_workflow_state.py from test_list.txt.

## Input

| Field | Source | Description |
|-------|--------|-------------|
| test_list_path | workflow.yaml input_filter.test_list_path | test_list.txt path |
| manifest_path | workflow_state.json paths.manifest | Output manifest.json path |

### test_list.txt format

`
# Comments start with #
tests/test_load.py::test_llama
tests/test_config.py::test_default_dtype
tests/distributed/test_pipeline_parallel.py::test_pp_basic
`

One test node per line. Lines starting with # are skipped. Empty lines are skipped.

## Output

### manifest.json (per manifest_schema.json)

Required top-level fields:
- ersion: "2.0"
- generated_at: ISO 8601 timestamp
- source: "test_list_file"
- 	ests: array of test objects
- statistics: { total, pending }

Required per-test fields (schema-enforced):
- id: integer (1-based sequence)
- 	est_node: string (e.g. "tests/test_load.py::test_llama")
- 	est_file: string (e.g. "tests/test_load.py")
- 	est_name: string (e.g. "test_llama")
- status: "pending" (all tests start as pending)

Optional per-test fields (schema has defaults):
- priority: "P2" (default)
- 
etry_count: 0 (default)
- max_retry: 3 (default, from workflow.yaml config.max_retry_per_test)
- errors[]: empty array
- ailures[]: empty array
- All other fields: null/false (default)

### Return format (unified)

`json
{
  "stats": { "passed": 0, "failed": 0, "ignored": 0, "error": 0, "pending": 13165 },
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
`

## Logic

`python
from pathlib import Path
from datetime import datetime, timezone
from skills.ut.shared import validate_and_write

def create_manifest_from_test_list(test_list_path: Path, manifest_path: Path) -> int:
    # 1. Read test_list.txt (skip comments and empty lines)
    lines = [
        l.strip()
        for l in test_list_path.read_text(encoding='utf-8').splitlines()
        if l.strip() and not l.startswith("#")
    ]

    # 2. Create test entries (all status=pending)
    tests = []
    for i, node in enumerate(lines, 1):
        parts = node.split("::")
        tests.append({
            "id": i,
            "test_node": node,
            "test_file": parts[0] if len(parts) >= 1 else node,
            "test_name": parts[1] if len(parts) >= 2 else "",
            "status": "pending",
        })

    # 3. Build manifest with statistics
    manifest = {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "test_list_file",
        "tests": tests,
        "statistics": {"total": len(tests), "pending": len(tests)},
    }

    # 4. Validate against schema and write
    is_valid, errors = validate_and_write(manifest, "manifest", manifest_path)
    if not is_valid:
        raise ValueError(f"Schema validation failed: {errors}")

    return len(tests)
`

## Pre/Post conditions

| Type | Condition | Description |
|------|-----------|-------------|
| **Pre** | test_list.txt exists | Path from workflow.yaml |
| **Pre** | run_dir created | By init_workflow_state.py |
| **Post** | manifest.json written | Schema-validated |
| **Post** | Supervisor continues | Stage 2 (generate_test_load) |

## Prohibited

- Do not run pytest --collect-only (not needed; test_list.txt is the source)
- Do not connect to remote servers (manifest is generated locally)
- Do not modify workflow_state.json (init_workflow_state.py handles this)
- Do not send notifications (Supervisor handles)

## Related Documents

- [manifest_schema.json](../../shared/manifest_schema.json) - Output schema
- [init_workflow_state.py](../terminal-workflow/scripts/init_workflow_state.py) - Implementation
- [workflow.yaml](../../deployment/production/config/workflow.yaml) - Config source

---

*Created: 2026-06-09*
*Updated: 2026-07-12*
*Version: 2.2.0*
