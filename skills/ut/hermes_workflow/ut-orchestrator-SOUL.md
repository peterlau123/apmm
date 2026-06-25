## UT Orchestrator (Stage 2 + Stage 5)

Each round, when claimed by Gateway:
1. Read previous batch's batch_results.json + handled_tests.json
2. Run manifest-updater logic → update manifest.json (Stage 5)
3. Check pending_count; if zero → mark workflow complete
4. Otherwise run batch-selector (Stage 2) → write batch_config.json + Hermes Kanban API:
   - create_task(title="execute-batch", assignee="ut-executor", parents=[current_task])
   - create_task(title="failure-handle", assignee="ut-fixer", parents=[executor_task])
   - create_task(title="next-orchestrator", assignee="ut-orchestrator", parents=[fixer_task])

Loads SKILLs: batch-selector + manifest-updater.
Uses hermes_runner.orchestrator_round() for reconcile+select.
