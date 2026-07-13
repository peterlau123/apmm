---

name: batch-selector

description: Stage 2 - select tests from test_load, generate batch_config.json

version: 2.3.0

when_to_use: Supervisor calls to select next batch from test_load (working dataset)

---



# Batch Selector (v2.3)



## Input / Output



```

Input:  test_load_xxx.json  (working dataset, via workflow_state.json paths.test_load)

        batch_size           (from workflow.yaml config.batch_size)

Output: batch_config.json    (schema-validated, written to {batches_dir}/{batch_id}/)

        workflow_state.json  (updated: batch status -> generated)

```



## Script



skills/ut/batch-selector/scripts/generate_batch.py



CLI entry point:

`ash

python skills/ut/batch-selector/scripts/generate_batch.py \

    --workflow-state <run_dir>/workflow_state.json \

    --batch-size 8

```



## Selection Logic (v5)



### select_batch(test_load, batch_size)



1. **Filter** by selectability (_is_selectable):



| status | selectable? | condition |

|--------|-------------|-----------|

| pending | yes | always |

| fixed_pending_verify | yes | always |

| retriable_error | yes | retry_count < max_retry (default 3) |

| failed | yes | retry_count < max_retry |

| error | no | routed to Stage 4 failure-handler |

| running / passed / ignored | no | terminal |



2. **Sort** by priority (lower = runs first):



```

pending=1, fixed_pending_verify=2, retriable_error=3, failed=4




3. **Take** first atch_size tests. Each test gets a selected_reason field.



### generate_batch() additional steps



After select_batch(), generate_batch() also:

- Separates distributed tests (标记 distributed_count, 不加入 batch)

- Groups normal tests by test_file (减少 pytest 启动开销)

- Validates output via alidate_and_write(batch_config, "batch_config", path)

- Updates workflow_state.json via update_batch_generated()



## batch_config.json structure



```json

{

  "batch_id": "batch_20260712_143000",

  "tests": [

    { "id": 1, "test_node": "tests/test_load.py::test_llama", "status": "pending", "selected_reason": "pending", ... }

  ],

  "distributed_count": 0,

  "requires_multi_gpu": false,

  "generated_at": "2026-07-12T14:30:00"

}

```



Schema: skills/ut/batch-selector/batch_config_schema.json



## Return format (unified)



```json

{

  "stats": { "passed": 0, "failed": 0, "error": 0, "ignored": 0, "pending": 12491 },

  "next_action": "continue",

  "error": null,

  "blocked_reason": null

}

```



## Pre/Post conditions



| Type | Condition |

|------|-----------|

| **Pre** | test_load exists in workflow_state.json paths.test_load |

| **Pre** | test_load has selectable tests (pending/fixed_pending_verify/retriable_error/failed) |

| **Post** | batch_config.json written (schema-validated) |

| **Post** | workflow_state.json updated (batch status = generated) |

| **Post** | Supervisor continues to Stage 3 (execute_batch) |



## Prohibited



- Do not modify test_load (read-only)

- Do not check GPU (moved to Stage 3)

- Do not send notifications (Supervisor handles)

- Do not return test details (only stats)



## Related



- [batch_config_schema.json](batch_config_schema.json) - Output schema

- [generate_batch.py](scripts/generate_batch.py) - Implementation

- [terminal-workflow/SKILL.md](../terminal-workflow/SKILL.md) - Linear channel

- [hermes-workflow/SKILL.md](../hermes-workflow/SKILL.md) - Kanban channel



---



*Updated: 2026-07-13*

*Version: 2.3.0*

