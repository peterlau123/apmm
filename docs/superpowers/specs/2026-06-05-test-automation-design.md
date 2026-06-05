# Test Automation System Design

> **vLLM Unit Test Automation for APMM Project**
> **Auto-scheduling, parallel execution, progress tracking, and reporting**

---

## Overview

### Problem Statement

Manual test execution for vLLM unit tests is:
- Slow (sequential execution, one-at-a-time)
- Interrupted by HF model timeouts (tests hang for hours)
- Manual progress tracking (PROGRESS.md manually updated)
- No resumption after network disconnects

### Solution

Extend existing scripts (`batch_test_runner.py`, `progress_tracker.py`) with:
- Parallel test execution (asyncio, N workers)
- Smart HF model handling (skip model-dependent tests)
- Auto-reconnect after network disconnects
- Automatic progress tracking and reporting

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

### 3.1 Startup Sequence

```
User runs: python test_scheduler.py --parallel 3 --resume

1. Load test_manifest.json from remote (via agent.py download)
2. Find last completed test ID (resume mode)
3. Get pending tests starting from that ID
4. Classify tests: model-dependent vs model-free
5. Start N parallel pytest workers
```

### 3.2 Parallel Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    Scheduler Main Loop                        │
│                                                              │
│  while pending_tests > 0:                                    │
│      │                                                       │
│      ├── Select batch of N tests                             │
│      │   (prefer model-free tests first)                     │
│      │                                                       │
│      ├── Check agent.py daemon health                        │
│      │   if disconnected: reconnect()                        │
│      │                                                       │
│      ├── Execute N tests in parallel (asyncio)               │
│      │   │                                                    │
│      │   ├── pytest worker 1 ──▶ GPU 0-1                     │
│      │   ├── pytest worker 2 ──▶ GPU 2-3                     │
│      │   ├── pytest worker 3 ──▶ GPU 4-5                     │
│      │   │                                                    │
│      │   └── Each worker:                                     │
│      │       ├── Set CUDA_VISIBLE_DEVICES                    │
│      │       ├── Run pytest with timeout                     │
│      │       ├── Capture output to ut_logs/                  │
│      │       └── Parse result (pass/fail/error/skip)         │
│      │                                                       │
│      ├── Collect results from all workers                    │
│      │                                                       │
│      ├── Update test_manifest.json                           │
│      │   (upload to remote)                                  │
│      │                                                       │
│      ├── Update PROGRESS.md (every 100 tests)                │
│      │                                                       │
│      └── Print progress to console                           │
│                                                              │
│  Loop ends when: pending_tests == 0 OR user stops            │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Auto-Reconnect Flow

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
  --resume            Resume from last completed test ID
  --start-id ID       Start from specific test ID
  --skip-model-tests  Skip all model-dependent tests
  --timeout SECONDS   Per-test timeout (default: 120)
  --dry-run           Show what would run, don't execute
  --stop-on-error N   Stop after N consecutive errors

# Progress check
python progress_tracker.py --manifest test_manifest.json --report

# Quick status
python progress_tracker.py --manifest test_manifest.json --status
```

### 5.2 Output Format

```
# Console output during execution

[Scheduler] Starting parallel execution with 3 workers
[Scheduler] Loaded 13165 tests from manifest, 8405 pending
[Scheduler] Resuming from test ID 4200

[Worker 1] Running test_id=4200: tests/kernels/test_cache.py::test_basic
[Worker 2] Running test_id=4201: tests/kernels/test_cache.py::test_advanced
[Worker 3] Running test_id=4202: tests/kernels/test_cache.py::test_edge

[Worker 1] ✓ PASSED (2.3s)
[Worker 2] ✗ FAILED (1.8s) - assertion error
[Worker 3] ⚠ ERROR (0.5s) - ImportError: wrap_triton

Progress: 4203/13165 (31.9%) | Passed: 2845 | Failed: 312 | Error: 156
─────────────────────────────────────────────────────────────────────

[Worker 1] Running test_id=4203: tests/kernels/test_cache.py::test_large
...
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
| `test_scheduler.py` | **CREATE** | Main scheduler with parallel execution |
| `batch_test_runner.py` | **MODIFY** | Add asyncio parallel execution |
| `progress_tracker.py` | **MODIFY** | Add auto-update, stalled detection |
| `docs/guides/automation.md` | **CREATE** | User guide for automation |

### 7.2 Implementation Order

1. **test_scheduler.py (NEW)**
   - Basic scheduler framework
   - asyncio parallel execution
   - Agent health check + reconnect
   - HF classification
   - CLI interface

2. **batch_test_runner.py (Enhancements)**
   - asyncio version of run_batch
   - Better error parsing
   - Smart timeout

3. **progress_tracker.py (Enhancements)**
   - Auto-update PROGRESS.md
   - Stalled test detection
   - Summary generation

4. **Testing & Validation**
   - Unit tests
   - Integration tests
   - Full deployment

### 7.3 Testing Strategy

**Phase 1: Unit Tests (Local)**
- Test scheduler logic with mock agent.py
- Test HF classification heuristics
- Test parallel execution simulation
- Test manifest update logic

**Phase 2: Integration Tests (Remote)**
- Run 10 tests sequentially first
- Run 10 tests in parallel (2 workers)
- Test reconnect by killing agent.py daemon
- Test stalled test detection

**Phase 3: Full Deployment**
- Run on subset of tests (100 tests)
- Monitor for 1 hour, verify stability
- Run full test suite

---

## Success Criteria

| Criteria | Target |
|----------|--------|
| Parallel execution | 3 concurrent pytest workers |
| Resume after disconnect | < 60s recovery time |
| HF model handling | Skip model-dependent tests within 10s |
| Progress tracking | Auto-update every 100 tests |
| Stalled detection | Kill tests stuck > 10 minutes |

---

## Dependencies

- Python 3.10+ (asyncio support)
- agent.py daemon running
- HF models cached at `/gpfs/.../hf_hub/`
- test_manifest.json on remote

---

*Created: 2026-06-05*
*Status: Approved*