# Test Automation System Design

> **vLLM Unit Test Automation for APMM Project**
> **Auto-scheduling, parallel execution, progress tracking, and reporting**
> **Multi-phase incremental execution with disconnect recovery**

---

## Overview

### Problem Statement

Manual test execution for vLLM unit tests is:
- Slow (sequential execution, one-at-a-time)
- Interrupted by HF model timeouts (tests hang for hours)
- Manual progress tracking (PROGRESS.md manually updated)
- No resumption after network disconnects
- **NEW: Test list expanded from 13,165 to 31,372 after fixing import errors**

### Test List Evolution

| List | Tests | Source | Status |
|------|:-----:|--------|--------|
| ut_test_list.txt | 13,165 | Original filter (GOAL.md) | Partially executed |
| ut_test_list_full.txt | 31,372 | New filter (no "^tests" prefix) | Not executed |
| **Difference** | ~18,207 | Tests now executable after fixes | Need incremental execution |

### Solution

Extend existing scripts (`batch_test_runner.py`, `progress_tracker.py`) with:
- **Multi-phase execution strategy** (Phase 1 → Phase 2 → Phase 3)
- **Test list diff algorithm** (find remaining tests between lists)
- Parallel test execution (asyncio, N workers)
- Smart HF model handling (skip model-dependent tests)
- **Incremental resume state** (track phase + progress, survive disconnects)
- Auto-reconnect after network disconnects

---

## Multi-Phase Execution Strategy

### Execution Phases

```
┌─────────────────────────────────────────────────────────────┐
│                    THREE-PHASE EXECUTION                     │
│                                                             │
│  Phase 1: Complete ut_test_list.txt                         │
│  ├── Tests: 13,165                                          │
│  ├── Goal: Finish original test list                        │
│  ├── Priority: High (already partially executed)            │
│  └── Output: test_manifest_phase1.json                      │
│                                                             │
│  Phase 2: Execute remaining from ut_test_list_full.txt      │
│  ├── Tests: ~18,207 (diff: full - phase1)                   │
│  ├── Goal: Run new tests that became executable             │
│  ├── Priority: Medium                                       │
│  └── Output: test_manifest_phase2.json                      │
│                                                             │
│  Phase 3: Handle error cases & collection errors            │
│  ├── Tests: 34 collection errors + warnings                 │
│  ├── Goal: Fix/document remaining issues                    │
│  ├── Priority: Low (cleanup phase)                          │
│  └── Output: error_analysis.md                              │
└─────────────────────────────────────────────────────────────┘
```

### Test List Diff Algorithm

```python
def compute_remaining_tests(full_list, phase1_list):
    """
    Find tests in full_list that are NOT in phase1_list.
    
    Returns: List of test nodes to execute in Phase 2
    """
    phase1_set = set(phase1_list)  # 13,165 tests
    full_set = set(full_list)       # 31,372 tests
    
    remaining = full_set - phase1_set  # ~18,207 tests
    
    # Sort by test file for organized execution
    return sorted(remaining, key=lambda x: x.split('::')[0])
```

### Phase State Tracking

```
┌─────────────────────────────────────────────────────────────┐
│                 RESUME STATE FILE (NEW)                      │
│                                                             │
│  File: execution_state.json                                 │
│                                                             │
│  {                                                          │
│    "current_phase": 1,          # 1, 2, or 3                │
│    "phase1_status": {                                      │
│      "total": 13165,                                       │
│      "completed": 4200,                                    │
│      "last_test_id": 4200                                  │
│    },                                                      │
│    "phase2_status": {                                      │
│      "total": 18207,                                       │
│      "completed": 0,                                       │
│      "remaining_tests": [...]  # Diff result               │
│    },                                                      │
│    "phase3_status": {                                      │
│      "errors_fixed": 0,                                    │
│      "errors_pending": 34                                  │
│    },                                                      │
│    "last_update": "2026-06-05T10:30:00",                   │
│    "disconnect_count": 2                                   │
│  }                                                          │
│                                                             │
│  Key: Survives disconnects, allows quick resume             │
└─────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     LOCAL HOST (Windows)                     │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │ test_scheduler  │───▶│ progress_tracker│                │
│  │ .py (NEW)       │    │ .py (EXISTING)  │                │
│  └─────────────────┘    └─────────────────┘                │
│         │                       │                          │
│         │ JSON commands          │ Manifest updates         │
│         ▼                       ▼                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              agent.py (EXISTING DAEMON)              │   │
│  │  - TCP socket on localhost:19922                    │   │
│  │  - Holds SSH session to bastion → t_h20             │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                 │
└──────────────────────────│─────────────────────────────────┘
                           │ SSH over bastion
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    REMOTE HOST (t_h20)                       │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │              Docker Container                          │ │
│  │  v0.13.0_torch2.5.1_compile                           │ │
│  │                                                        │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐ │ │
│  │  │ pytest #1   │   │ pytest #2   │   │ pytest #3   │ │ │
│  │  │ (GPU 0-1)   │   │ (GPU 2-3)   │   │ (GPU 4-5)   │ │ │
│  │  └─────────────┘   └─────────────┘   ┌─────────────┐ │ │
│  │  Parallel execution via asyncio                       │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  /gpfs/gcsp/M2.7_verify/vllm/                              │
│  ├── ut_logs/              # Test output logs              │
│  ├── test_manifest.json    # Progress tracking             │
│  └── hf_hub/               # Pre-downloaded models         │
└─────────────────────────────────────────────────────────────┘
```

---

## Components

### 2.1 test_scheduler.py (NEW - Main Controller)

```
test_scheduler.py
├── Scheduler class
│   ├── load_manifest()         # Read test_manifest.json via agent.py
│   ├── get_pending_tests()     # Filter pending tests by category
│   ├── schedule_batch()        # Select N tests to run in parallel
│   ├── execute_parallel()      # Run tests concurrently via asyncio
│   ├── handle_results()        # Parse pytest output, update manifest
│   └── auto_reconnect()        # Check agent.py health, reconnect if needed
│
├── PhaseManager (NEW)
│   ├── load_state()            # Read execution_state.json
│   ├── save_state()            # Persist state after each batch
│   ├── get_current_phase()     # Return 1, 2, or 3
│   ├── compute_remaining()     # Diff full_list - phase1_list
│   ├── advance_phase()         # Move to next phase when complete
│   └── resume_from_state()     # Quick recovery after disconnect
│
├── HF Detector
│   ├── check_model_cache()     # Check if model exists in hf_hub/
│   ├── classify_test()         # Mark test as model-dependent or not
│   └── skip_model_tests()      # Option to skip HF-dependent tests
│
└── Config
    ├── parallel_count: 3       # Number of concurrent pytest processes
    ├── timeout_per_test: 120s  # Per-test timeout
    ├── hf_cache_path: /gpfs/.../hf_hub
    ├── reconnect_interval: 30s # Check agent.py health
    ├── phase1_list: ut_test_list.txt
    ├── phase2_list: ut_test_list_full.txt
    └── state_file: execution_state.json
```

### 2.2 batch_test_runner.py (ENHANCED)

```
batch_test_runner.py (modified)
├── Keep existing functions
│   ├── run_test_on_remote()    # Single test execution
│   ├── update_manifest_status()
│   └── record_error_in_progress()
│
├── NEW additions
│   ├── run_tests_parallel()    # asyncio version of run_batch
│   ├── detect_hf_dependency()  # Check if test needs HF model
│   └── smart_timeout()         # Adjust timeout based on test type
```

### 2.3 progress_tracker.py (ENHANCED)

```
progress_tracker.py (modified)
├── Keep existing functions
│   ├── show_progress()
│   ├── generate_report()
│
├── NEW additions
│   ├── auto_update_progress_md()  # Sync PROGRESS.md every N tests
│   ├── generate_summary_section() # Add summary to PROGRESS.md
│   └── detect_stalled_tests()     # Alert if tests running > 10min
```

---

## Data Flow & Execution Sequence

### 3.1 Startup Sequence (with Phase Support)

```
User runs: python test_scheduler.py --parallel 3

1. Load execution_state.json (or create if not exists)
2. Determine current phase from state:
   - Phase 1: Load ut_test_list.txt manifest
   - Phase 2: Compute diff, load remaining tests
   - Phase 3: Load error cases
3. Find last completed test ID in current phase
4. Get pending tests starting from that ID
5. Classify tests: model-dependent vs model-free
6. Start N parallel pytest workers
```

### 3.2 Phase-Based Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    Phase-Based Main Loop                      │
│                                                              │
│  Load execution_state.json                                   │
│  current_phase = state.current_phase                         │
│                                                              │
│  PHASE 1 LOOP (ut_test_list.txt):                            │
│      while phase1_pending > 0:                               │
│          ├── Select batch, execute parallel                  │
│          ├── Update test_manifest_phase1.json                │
│          ├── Update execution_state.json                     │
│          └── Check agent.py health (reconnect if needed)     │
│                                                              │
│      # Phase 1 complete                                      │
│      state.current_phase = 2                                 │
│      compute_remaining_tests()                               │
│      save_state()                                            │
│                                                              │
│  PHASE 2 LOOP (remaining tests):                             │
│      while phase2_pending > 0:                               │
│          ├── Select batch, execute parallel                  │
│          ├── Update test_manifest_phase2.json                │
│          ├── Update execution_state.json                     │
│          └── Check agent.py health (reconnect if needed)     │
│                                                              │
│      # Phase 2 complete                                      │
│      state.current_phase = 3                                 │
│      save_state()                                            │
│                                                              │
│  PHASE 3 (error handling):                                   │
│      ├── Review 34 collection errors                         │
│      ├── Attempt to fix/document each                        │
│      └── Generate error_analysis.md                          │
│                                                              │
│  DONE: All phases complete                                   │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Disconnect Recovery Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    Quick Resume After Disconnect              │
│                                                              │
│  On reconnect (user runs scheduler again):                   │
│      │                                                       │
│      ├── Load execution_state.json                           │
│      │   ├── current_phase: Know which phase to continue     │
│      │   ├── last_test_id: Know where to resume              │
│      │   └── disconnect_count: Track stability               │
│      │                                                       │
│      ├── Quick status display:                               │
│      │   "Resuming Phase 1, test #4200, 8945 remaining"      │
│      │                                                       │
│      ├── Check agent.py daemon                               │
│      │   if not running: prompt user to start                │
│      │                                                       │
│      └── Resume execution immediately                        │
│          (< 30s recovery time)                               │
│                                                              │
│  Key: All state persisted to file, no data lost              │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Auto-Reconnect Flow (During Execution)

```
┌──────────────────────────────────────────────────────────────┐
│                    Reconnect Handler                          │
│                                                              │
│  every 30 seconds:                                           │
│      │                                                       │
│      ├── Ping agent.py daemon                                │
│      │   (python agent.py ping)                              │
│      │                                                       │
│      ├── If ping fails:                                      │
│      │   ├── Stop running workers                            │
│      │   ├── Wait for agent.py to restart                    │
│      │   ├── Resume from last completed test ID              │
│      │   └── Restart parallel execution                      │
│      │                                                       │
│      └── If ping succeeds:                                   │
│          └── Continue execution                              │
└──────────────────────────────────────────────────────────────┘
```

---

## HF Model Handling

### 4.1 Model Dependency Detection

```
┌──────────────────────────────────────────────────────────────┐
│                    HF Dependency Classifier                   │
│                                                              │
│  Heuristics to detect model-dependent tests:                 │
│                                                              │
│  1. Test file path patterns:                                 │
│     ├── tests/models/*         → model-dependent             │
│     ├── tests/lora/*           → model-dependent             │
│     ├── tests/tokenizers_/*    → model-dependent             │
│     ├── tests/evals/*          → model-dependent             │
│     └── tests/kernels/*        → usually model-free          │
│                                                              │
│  2. Import analysis (optional):                              │
│     ├── from transformers import ...                         │
│     ├── from huggingface_hub import ...                      │
│                                                              │
│  3. Test function names:                                     │
│     ├── test_*_model*         → model-dependent              │
│     ├── test_*_generation*    → model-dependent              │
│                                                              │
│  Classification result:                                      │
│  ├── MODEL_FREE: Can run immediately                         │
│  ├── MODEL_CACHED: Model exists in hf_hub/                   │
│  ├── MODEL_MISSING: Need to download or skip                 │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Execution Priority

```
Priority order for test execution:

1. MODEL_FREE tests (highest priority)
   └── Run immediately, no waiting for HF
   
2. MODEL_CACHED tests (medium priority)
   └── Model exists in hf_hub/, can run
   
3. MODEL_MISSING tests (lowest priority)
   └── Options:
       ├── SKIP: Don't run, mark as skipped in manifest
       ├── DOWNLOAD: Queue for download on t_ascend
       └── TIMEOUT: Try with short timeout, skip if fails
```

### 4.3 HF Environment Setup

```bash
# In Docker container before running pytest
export HF_HOME=/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub
export HF_DATASETS_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# This forces HF to use only cached models
# Tests that need missing models will fail quickly (not hang)
```

---

## Command Interface

### 5.1 CLI Commands

```bash
# Main scheduler command
python test_scheduler.py [options]

Options:
  --parallel N        Number of parallel workers (default: 3)
  --phase N           Start specific phase (1, 2, or 3)
  --resume            Resume from last state (phase + test ID)
  --start-id ID       Start from specific test ID (within phase)
  --skip-model-tests  Skip all model-dependent tests
  --timeout SECONDS   Per-test timeout (default: 120)
  --dry-run           Show what would run, don't execute
  --stop-on-error N   Stop after N consecutive errors

# Phase management
python test_scheduler.py --status
python test_scheduler.py --reset-phase 1  # Reset to phase 1
python test_scheduler.py --compute-diff   # Show remaining tests for phase 2

# Progress check
python progress_tracker.py --manifest test_manifest.json --report

# Quick status
python progress_tracker.py --manifest test_manifest.json --status
```

### 5.2 Output Format

```
# Console output during execution

[Scheduler] Loading execution_state.json...
[Scheduler] Current Phase: 1 (ut_test_list.txt)
[Scheduler] Phase 1 Progress: 4200/13165 (31.9%)
[Scheduler] Starting parallel execution with 3 workers

[Worker 1] Running test_id=4200: tests/kernels/test_cache.py::test_basic
[Worker 2] Running test_id=4201: tests/kernels/test_cache.py::test_advanced
[Worker 3] Running test_id=4202: tests/kernels/test_cache.py::test_edge

[Worker 1] ✓ PASSED (2.3s)
[Worker 2] ✗ FAILED (1.8s) - assertion error
[Worker 3] ⚠ ERROR (0.5s) - ImportError: wrap_triton

Phase 1 Progress: 4203/13165 (31.9%) | Passed: 2845 | Failed: 312 | Error: 156
─────────────────────────────────────────────────────────────────────

# Phase transition

[Scheduler] Phase 1 Complete! 13165 tests executed.
[Scheduler] Computing remaining tests for Phase 2...
[Scheduler] Phase 2: 18207 new tests found
[Scheduler] Transitioning to Phase 2...

[Worker 1] Running phase2_test_id=1: tests/basic_correctness/test_basic_correctness.py::test_vllm_gc_ed
...
```

### 5.3 Disconnect Recovery Output

```
# On reconnect after disconnect

[Scheduler] === QUICK RESUME ===
[Scheduler] Last session: 2026-06-05T10:30:00
[Scheduler] Disconnect detected: 2 times today
[Scheduler] Current Phase: 1
[Scheduler] Resuming from test_id=4200
[Scheduler] Phase 1 remaining: 8945 tests
[Scheduler] Checking agent.py daemon...
[Scheduler] ✓ agent.py is running
[Scheduler] Resuming execution in 5 seconds...
```

---

## Error Handling

### 6.1 Error Classification (From GOAL.md)

| Category | Detection Pattern | Action |
|----------|-------------------|--------|
| **C-代码Bug** | AssertionError, TypeError in vLLM code | Mark as failed, log for review |
| **E-环境问题** | OSError, FileNotFoundError, quota errors | Mark as error, may be retryable |
| **D-依赖缺失** | ImportError, ModuleNotFoundError | Mark as error, log dependency name |
| **P-平台兼容** | "wrap_triton", "fp32_precision", ABI errors | Mark as error, known compatibility |
| **M-模型缺失** | HF LocalEntryNotFoundError, config.json missing | Mark as skipped (model-dependent) |
| **S-跳过问题** | pytest.skip(), SkipTest | Mark as skipped |

### 6.2 Recovery Strategies

| Error Type | Recovery Action |
|------------|-----------------|
| Network disconnect | Wait 30s, ping agent.py, reconnect |
| GPU OOM | Clear GPU cache, retry with fewer GPUs |
| HF model missing | Skip test, mark as "model-dependent" |
| Triton compile | Skip test, mark as "P-平台兼容" |
| Unknown error | Log full traceback, mark as error |
| Timeout | Kill pytest process, mark as timeout |

### 6.3 Stalled Test Detection

```python
def detect_stalled_tests():
    for worker in workers:
        if worker.running_time > 600s:  # 10 minutes
            if worker.output_lines == worker.last_output_lines:
                # No new output, likely stalled
                kill_worker(worker)
                mark_as_timeout(worker.test_id)
                log_warning("Stalled test detected")
```

---

## Implementation Plan

### 7.1 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `test_scheduler.py` | **CREATE** | Main scheduler with parallel execution + PhaseManager |
| `execution_state.json` | **CREATE** | Resume state tracking (phase + progress) |
| `batch_test_runner.py` | **MODIFY** | Add asyncio parallel execution |
| `progress_tracker.py` | **MODIFY** | Add auto-update, stalled detection |
| `docs/guides/automation.md` | **CREATE** | User guide for automation |

### 7.2 Implementation Order

1. **execution_state.json (NEW)**
   - Define state schema
   - Create state file management functions

2. **test_scheduler.py (NEW)**
   - PhaseManager class (phase tracking + diff algorithm)
   - Basic scheduler framework
   - asyncio parallel execution
   - Agent health check + reconnect
   - HF classification
   - CLI interface

3. **batch_test_runner.py (Enhancements)**
   - asyncio version of run_batch
   - Better error parsing
   - Smart timeout

4. **progress_tracker.py (Enhancements)**
   - Auto-update PROGRESS.md
   - Stalled test detection
   - Summary generation

5. **Testing & Validation**
   - Unit tests
   - Integration tests (disconnect simulation)
   - Full deployment

### 7.3 Testing Strategy

**Phase 1: Unit Tests (Local)**
- Test scheduler logic with mock agent.py
- Test HF classification heuristics
- Test parallel execution simulation
- Test manifest update logic
- **Test PhaseManager: diff algorithm, state persistence**
- **Test disconnect recovery: simulate reconnect**

**Phase 2: Integration Tests (Remote)**
- Run 10 tests sequentially first
- Run 10 tests in parallel (2 workers)
- Test reconnect by killing agent.py daemon
- Test stalled test detection
- **Test phase transition: Phase 1 → Phase 2**
- **Test resume after forced disconnect**

**Phase 3: Full Deployment**
- Run on subset of tests (100 tests)
- Monitor for 1 hour, verify stability
- **Verify disconnect recovery works in real scenario**
- Run full test suite

---

## Success Criteria

| Criteria | Target |
|----------|--------|
| Parallel execution | 3 concurrent pytest workers |
| Resume after disconnect | < 30s recovery time |
| HF model handling | Skip model-dependent tests within 10s |
| Progress tracking | Auto-update every 100 tests |
| Stalled detection | Kill tests stuck > 10 minutes |
| **Phase 1 completion** | 13,165 tests executed, results recorded |
| **Phase 2 diff** | ~18,207 remaining tests identified correctly |
| **Phase 2 completion** | All remaining tests executed |
| **Phase 3 documentation** | 34 collection errors analyzed |
| **State persistence** | execution_state.json survives any disconnect |

---

## Dependencies

- Python 3.10+ (asyncio support)
- agent.py daemon running
- HF models cached at `/gpfs/.../hf_hub/`
- test_manifest.json on remote

---

*Created: 2026-06-05*
*Status: Approved*