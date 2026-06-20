## UT Orchestrator (Stage 2 + Stage 5)

Each round, when claimed by Gateway:
1. Read previous batch's batch_results.json + handled_tests.json
2. Run manifest-updater logic → update manifest.json (Stage 5)
3. Check pending_count; if zero → mark workflow complete
4. Otherwise run batch-selector (Stage 2) → create:
   - new batch task (assignee=ut-executor)
   - fix task (assignee=ut-fixer, depends_on=executor)
   - next orchestrator task (depends_on=fixer)

Loads SKILLs: batch-selector + manifest-updater.
Uses hermes_runner.orchestrator_round() for reconcile+select.
