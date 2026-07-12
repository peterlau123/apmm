---
name: unit-test-collector
description: Stage 1 - generate manifest.json from test_list.txt (skipped if manifest already provided)
version: 2.2.0
when_to_use: Supervisor calls when input is test_list.txt. Skipped when user provides manifest.json directly.
---

# UT Test Collector (v2.2)

## When to run / when to skip

| User input | This skill | Reason |
|------------|-----------|--------|
| test_list.txt | **Run** | Parse list, generate manifest.json |
| manifest.json (existing) | **Skip** | User already has manifest, copy to run_dir directly |

The decision is made in init_workflow_state.py:
- manifest_path already exists -> skip, read existing manifest
- manifest_path not exists + 	est_list_path provided -> run collect

## Input / Output

`
Input:  test_list.txt    (one test node per line, # for comments)
Output: manifest.json    (schema-validated, all tests status=pending)
`

## Script

skills/ut/terminal-workflow/scripts/init_workflow_state.py
- Function: create_manifest_from_test_list(test_list_path, manifest_path)
- Schema: skills/ut/shared/manifest_schema.json
- Validation: skills/ut/shared/validate_schema.py::validate_and_write

> scripts/collect.py is deprecated (early local pytest collect impl, not used).

## Logic

1. Read test_list.txt (skip # comments and empty lines)
2. Parse each line: 	ests/file.py::test_name -> test_file + test_name
3. Create test entries (id, test_node, test_file, test_name, status="pending")
4. Build manifest: version="2.0", source="test_list_file", tests[], statistics{total, pending}
5. Validate against manifest_schema.json, write to manifest_path

## Return format (unified)

`json
{
  "stats": { "passed": 0, "failed": 0, "ignored": 0, "error": 0, "pending": 13165 },
  "next_action": "continue",
  "error": null,
  "blocked_reason": null
}
`

## Prohibited

- Do not run pytest --collect-only (test_list.txt is the source)
- Do not connect to remote servers (local operation)
- Do not modify workflow_state.json (init handles this)

---

*Updated: 2026-07-12*
*Version: 2.2.0*
