# About Agents Architecture and Workflow Design

**Date**: 2026-06-09
**Discussion**: UT Test Workflow Architecture and workflow.yaml Design
**历史文档注：** `.agents/workflow.yaml` 已废弃（2026-06-29），配置迁移至 `tasks/ut/deployment/production/config/` + `runs/ut-{timestamp}/`副本机制。

---

## Key Decisions

### 1. Agent Solution: Single Agent + Workflow

**Conclusion**: Supervisor Agent executes workflow in single session

**Reasons**:
- Workflow is inherently **sequential + stateful + loop**
- Single Agent maintains state naturally
- No cross-Agent communication overhead
- Lowest complexity and cost

**Architecture**:
```
Supervisor Session (Single Agent):
    ├── Read workflow.yaml
    ├── Execute stages sequentially
    ├── Loop: stages 2-5 until stop_condition
    ├── Update workflow_state.json
    └── Sync Kanban + Send Feishu
```

---

### 2. Workflow Stages: 5 Stages

| Order | Stage | Skill | Loop |
|-------|-------|-------|------|
| 1 | Collect test list | ut-test-collector | No |
| 2 | Select batch | batch-selector | Yes |
| 3 | Execute pytest | unit-test-looper | Yes |
| 4 | Handle failures | failure-handler | Yes |
| 5 | Update manifest | manifest-updater | Yes |

**Loop Structure**: [Stage 2, 3, 4, 5]

**Stop Condition**: `pending_count == 0`

---

### 3. dependency-resolver: NOT a Separate Stage

**Role**: Helper scripts called by failure-handler

**Trigger**: When `error_type == "dependency_missing"` detected

**Why NOT a stage**:
- Conditional trigger (only when dependency missing)
- Part of failure-handler's error handling logic
- Most failures are NOT dependency_missing
- Avoids conditional branching in workflow

---

### 4. Skills Role: Reusable Guides

**Each Skill SKILL.md preserved for reusability**:
- Can be loaded independently for debugging
- Defines behavior guidelines for Agent
- Scripts organized under skill directory

**Skills Structure**:
```
skills/ut/
├── supervisor/           # Workflow executor + monitor
├── ut-test-collector/    # Stage 1
├── batch-selector/       # Stage 2
├── unit-test-looper/     # Stage 3
├── failure-handler/      # Stage 4 (calls dependency-resolver internally)
├── manifest-updater/     # Stage 5
└── dependency-resolver/  # Helper scripts (NOT a stage)
```

---

### 5. Kanban Integration: Script-based

**Integration**: Scripts call `kanban_sync.py` as side effect

**Flow**: `manifest.json → Kanban` sync

**Lanes**: Default mapping (status → lane)
- pending (unassigned) → Backlog
- pending (assigned) → Pending
- running → Running
- passed → Passed
- failed → Failed
- ignored → Ignored

---

## workflow.yaml Design

### Core Structure

```yaml
workflow:
  name: UT Test Workflow
  version: 1.0
  
  config:
    workspace: D:/workspace/apmm
    remote_server: t_h20
    docker_container: v0.13.0_torch2.5.1_compile
    
    # Core paths (using {workspace} reference)
    manifest_path: {workspace}/tasks/ut/test_analysis/manifest.json
    state_dir: {workspace}/.agents  # Internal state files
    
  stages:
    - id: collect
      enabled: true
      skill: ut-test-collector
      params: {...}
      input: {...}
      output: {...}
      skip_condition: "file_exists(manifest_path)"
      
    - id: select_batch
      enabled: true
      skill: batch-selector
      params: {batch_size: 50}
      input: {manifest_path: ...}
      output: {batch_config_path: ..., batch_id: ...}
      
    - id: execute
      enabled: true
      skill: unit-test-looper
      params: {pytest_args: "-q --tb=long"}
      input: {batch_config_path: ...}
      output: {batch_results_path: ...}
      timeout: 3600
      
    - id: handle_failures
      enabled: true
      skill: failure-handler
      params: {auto_resolve_dependencies: true}
      input: {batch_results_path: ...}
      output: {failure_handled_path: ...}
      
    - id: update_status
      enabled: true
      skill: manifest-updater
      params: {generate_report: true}
      input: {batch_results_path: ..., failure_handled_path: ...}
      output: {manifest_path: ..., report_path: ...}
        
  loop:
    stages: [select_batch, execute, handle_failures, update_status]
    stop_condition: "pending_count == 0"
    break_conditions:
      - condition: "failure_rate > 0.5"
        action: pause
        
  output:
    workflow_state_path: {state_dir}/workflow_state.json
    
    kanban:
      enabled: true
      board_name: UT Test Progress
      update_condition: "manifest_updated"
      
    feishu:
      enabled: true
      chat_id: oc_2e75db818ac1792237a704b4d32d3
      notify_on:
        - condition: "batch_completed"
          message: "Batch {batch_id} completed: {passed_count}/{total_count} passed"
        - condition: "workflow_completed"
          message: "Workflow completed: {passed_count}/{total_count} passed"
        - condition: "failure_rate > 0.5"
          message: "Warning: Failure rate exceeded 50%"
```

---

## Key Design Principles

### 1. Minimal Required Fields

**Stage fields**: id, enabled, skill, params, input, output

**Removed**: name, description, depends_on, retry, on_failure

**Why**: Reduce complexity, skill SKILL.md has name/description

---

### 2. Workspace Reference

**All paths use `{workspace}` reference**:

```yaml
manifest_path: {workspace}/tasks/ut/test_analysis/manifest.json
state_dir: {workspace}/.agents
```

**Benefits**:
- Portable (change workspace, all paths update)
- Clear relationship (explicit reference)
- Flexible (can also use absolute path)

---

### 3. All Stages Have input/params/output

**Why**:
- Clear data flow
- Input validation (check files exist)
- Output verification (check files created)
- Dependency inference (input/output → implicit depends_on)

---

### 4. Expression Syntax

**skip_condition**: Python expression

Examples:
```yaml
skip_condition: "file_exists(manifest_path)"
skip_condition: "pending_count == 0"
skip_condition: "failure_rate > 0.5"
```

**Safe context variables**:
- `manifest`: Load manifest.json
- `pending_count`: manifest.statistics.pending_count
- `failure_rate`: manifest.statistics.failure_rate
- `file_exists(path)`: Check file existence

---

### 5. Loop Configuration

**max_iterations**: Optional (safety limit)

**break_conditions**: Trigger pause/stop/notify

```yaml
break_conditions:
  - condition: "failure_rate > 0.5"
    action: pause
    notify: true
```

---

### 6. Output Conditions

**kanban.update_condition**: When to sync

**feishu.notify_on**: When to send notification

```yaml
feishu:
  notify_on:
    - condition: "batch_completed"
      message: "Batch {batch_id} completed: ..."
```

---

## Implementation Files

### New Files to Create

| File | Purpose |
|------|---------|
| `.agents/workflow.yaml` | Workflow configuration |
| `.agents/workflow_state.json` | Execution state tracking |
| `supervisor/scripts/workflow_executor.py` | Execute workflow from config |
| `shared/scripts/kanban_sync.py` | Kanban sync script |

### Files to Update

| File | Update |
|------|--------|
| `supervisor/SKILL.md` | Add workflow execution logic |
| `failure-handler/SKILL.md` | Add dependency-resolver calling logic |

---

## Execution Modes

| Mode | Command | Description |
|------|---------|-------------|
| **Full Workflow** | `workflow run` | All enabled stages + loop |
| **Single Stage** | `workflow run --stage collect` | Only specified stage |
| **Range** | `workflow run --from select_batch --to update_status` | Stages X to Y |
| **Resume** | `workflow run --resume` | Resume from workflow_state.json |

---

## Benefits Summary

| Benefit | Value |
|---------|-------|
| Simple workflow | 5 stages, clear loop |
| Customizable | workflow.yaml enable/disable |
| Reusable | All SKILL.md preserved |
| Kanban-ready | Script-based sync |
| Low complexity | Single Agent |
| Low cost | 1 Agent token |
| Portable | {workspace} reference |
| Resume capability | workflow_state.json |

---

## Next Steps

1. Create workflow.yaml configuration file
2. Update supervisor SKILL.md with workflow execution logic
3. Create workflow_executor.py script
4. Create kanban_sync.py script
5. Update failure-handler to call dependency-resolver internally
6. Test workflow execution

---

## Discussion History

1. Started with Skills analysis report (input/output clarity)
2. Brainstormed Agent solutions (1 vs 2 vs 7 Agents)
3. Discussed Workflow + Loop structure
4. Concluded: Single Agent + Workflow (sequential + stateful)
5. Brainstormed Kanban integration
6. Brainstormed workflow.yaml design
7. Refined workflow.yaml based on user comments:
   - Use {workspace} reference for paths
   - Rename agents_dir → state_dir
   - All stages have input/params/output
   - max_iterations is optional
   - Add trigger conditions for kanban/feishu

---

## References

- AGENTS.md - Project guide
- skills/ut/*/SKILL.md - Skill definitions
- tasks/ut/README.md - Task module documentation