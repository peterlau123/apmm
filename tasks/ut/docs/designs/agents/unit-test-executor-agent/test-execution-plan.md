# Test Execution Plan Design

> **vLLM Unit Test Execution Strategy**
> **Multi-round Layered Execution with Model-Free Priority**
> **Created: 2026-06-05**

---

## Overview

### Problem Statement

Current test progress shows significant pending work:
- Phase 1: 12,900 tests pending (13,165 total)
- Phase 2: 18,782 tests pending (from diff)
- High failure rate due to HF model dependency

### Solution

Layered progressive execution:
1. Round 1: Model-free tests (fast, high pass rate)
2. Round 2: Model tests with key models downloaded
3. Round 3: Edge cases requiring special handling

---

## Execution Phases

### Phase 1 Execution Flow

```
Round 1: Model-Free Tests
├── Target: ~60% (~7,740 tests)
├── Strategy: Auto-detect HF dependency, skip model tests
├── Parallel: 3 workers (GPU 0/2/4 priority idle cards)
├── Estimated time: ~2-3 hours

Round 2: Model Tests (Key Models)
├── Target: ~30% (~3,870 tests)
├── Pre-condition: Download 5 high-frequency models
│   ├── opt-125m, gpt2 (already cached)
│   ├── Qwen/Qwen2.5-1.5B-Instruct
│   ├── meta-llama/Llama-3.2-1B-Instruct
├── Parallel: 3 workers
├── Estimated time: ~4-6 hours

Round 3: Remaining Edge Cases
├── Target: ~10% (~1,290 tests)
├── Handling: Tests requiring special models/environment
├── Strategy: Manual analysis before execution
```

### Phase 2 Execution Flow

```
Phase 2: 18,782 Tests (Diff from full list)
├── Round 1: Model-Free (~60%)
├── Round 2: Model Tests (~30%)
├── Round 3: Edge Cases (~10%)
├── Estimated total time: ~8-12 hours
```

---

## GPU Allocation

### Worker Configuration

```
H20-3e GPU Topology (8 cards):
┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐
│ GPU0│ GPU1│ GPU2│ GPU3│ GPU4│ GPU5│ GPU6│ GPU7│
│ ✓   │ ✓   │ ✓   │ ✓   │ ✓   │ ✓   │ ✓   │ ✓   │ All idle
└─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘

Worker Allocation:
├── Worker 1: GPU 0-1 (CUDA_VISIBLE_DEVICES=0,1)
├── Worker 2: GPU 2-3 (CUDA_VISIBLE_DEVICES=2,3)
├── Worker 3: GPU 4-5 (CUDA_VISIBLE_DEVICES=4,5)
└── GPU 6-7: Reserved (model download/special tests)

Worker Settings:
├── Each worker: Independent pytest process
├── Batch size: 10 tests/batch
├── Timeout: 120s (model-free), 300s (model-dependent)
└── Log: Independent log files
```

### Execution Command Template

```bash
# Worker 1 (GPU 0-1)
CUDA_VISIBLE_DEVICES=0,1 nohup pytest <tests> \
  --tb=short --timeout=120 \
  > ut_logs/phase1/batch_20260605_worker1.log 2>&1 &

# Worker 2 (GPU 2-3)
CUDA_VISIBLE_DEVICES=2,3 nohup pytest <tests> \
  --tb=short --timeout=120 \
  > ut_logs/phase1/batch_20260605_worker2.log 2>&1 &

# Worker 3 (GPU 4-5)
CUDA_VISIBLE_DEVICES=4,5 nohup pytest <tests> \
  --tb=short --timeout=120 \
  > ut_logs/phase1/batch_20260605_worker3.log 2>&1 &
```

---

## HF Model Dependency Detection

### Classification Rules

```
Path Pattern Detection (High Priority):
├── tests/models/*         → MODEL_DEPENDENT
├── tests/lora/*           → MODEL_DEPENDENT
├── tests/tokenizers_/*    → MODEL_DEPENDENT
├── tests/entrypoints/*    → MODEL_DEPENDENT
├── tests/evals/*          → MODEL_DEPENDENT
└── tests/kernels/*        → MODEL_FREE (usually no model dependency)

Test Function Name Detection:
├── test_*_model*          → MODEL_DEPENDENT
├── test_*_generation*     → MODEL_DEPENDENT
└── test_*_download*       → MODEL_DEPENDENT

Cache Status Detection:
├── Model exists in hf_hub/ → MODEL_CACHED (executable)
├── Model missing           → MODEL_MISSING (skip Round 1)

Classification Result:
├── MODEL_FREE: Round 1 immediate execution
├── MODEL_CACHED: Round 1 executable (model exists)
├── MODEL_MISSING: Round 2 execution (need download)
```

### Cached Models

```
hf_hub/ Existing Models:
├── facebook/opt-125m        ✅ Round 1 available
├── gpt2                     ✅ Round 1 available
├── Qwen/Qwen2.5-1.5B        ✅ Round 1 available (config.json)
└── Others...                ⚠️ Round 2 need download
```

### Round 2 Key Models to Download

| Model | Usage | Priority | Size |
|-------|-------|:--------:|:----:|
| meta-llama/Llama-3.2-1B-Instruct | Multi-test usage | P0 | ~1.5GB |
| EleutherAI/gpt-j-6b | Generation tests | P1 | ~12GB |
| mistralai/Mistral-7B-v0.1 | General tests | P1 | ~14GB |
| bigscience/bloom-560m | Tokenizer tests | P2 | ~1GB |
| tiiuae/falcon-7b | Special tests | P2 | ~14GB |

---

## Error Handling

### Consecutive Error Threshold

```
Threshold Settings:
├── Consecutive error threshold: 5 tests
├── Single test timeout: 120s (model-free) / 300s (model)
└── Log rotation: >10MB truncate

Handling Flow:

Test Execution → Result
   │
   ├── PASSED → Record success, clear consecutive count
   │
   ├── FAILED →
   │   ├── Classify error type (C/E/D/P/M/S)
   │   ├── Record to issues.json
   │   ├── Append to PROGRESS.md
   │   └── Consecutive count +1
   │
   ├── ERROR →
   │   ├── Record error details
   │   ├── Consecutive count +1
   │   └── Check threshold
   │
   └── TIMEOUT →
   │   ├── Kill process
   │   ├── Record timeout
   │   └ Consecutive count +1

Threshold Reached (5 consecutive errors):
├── Record skip information:
│   ├── Current test file
│   ├── Consecutive error types
│   ├── Recommended handling
├── Skip remaining tests in current file
├── Clear consecutive count
└── Continue to next test file
```

### Skip Record Format

```markdown
### 2026-06-05 XX:XX:XX - Skip Record

**Trigger Reason**: 5 consecutive errors
**Test File**: tests/quantization/test_marlin.py
**Error Type**: D-依赖缺失 (wrap_triton)
**Tests Skipped**: 42
**Recommended Handling**: Add wrap_triton shim or skip quantization directory

**Error Details**:
| Test ID | Error Message |
|---------|---------------|
| 1234 | ImportError: wrap_triton |
| 1235 | ImportError: wrap_triton |
| ... | ... |
```

### issues.json Update

```json
{
  "id": "D-4",
  "category": "D-依赖缺失",
  "description": "wrap_triton 缺失导致 quantization 测试失败",
  "affected_tests": 512,
  "status": "open",
  "first_seen": "2026-06-05",
  "notes": "自动跳过记录，需添加 shim"
}
```

---

## Progress Tracking

### PROGRESS.md Append Mode

```
Record Timing:
├── After each batch (10 tests)
├── When threshold skip triggered
├── When each Round completes
├── When Phase switches
└── When disconnect recovery

Append Format:

### 2026-06-05 10:30:15 - Batch Execution
- Tests: #100-#109 (batch_size=10)
- Result: 8 passed, 1 failed, 1 error
- Duration: 45.2s
- Worker: 1 (GPU 0-1)
- Log: ut_logs/phase1/batch_20260605_1030_w1.log

### 2026-06-05 10:35:22 - Round 1 Complete
- Round 1 stats: 7740 passed, 580 failed, 420 error
- Coverage: 60% of Phase 1
- Preparing Round 2: Model download queue

Overview Table Update:
├── Every 100 tests update top statistics
├── Never modify historical records
└── Keep timestamps
```

### Real-time Query Response

```
User asks: "进度怎么样?"

System Response:
├── Phase: Phase 1 Round 1
├── Completed: 4,200 / 7,740 tests (54.3%)
├── Remaining: 3,540 tests
├── Rate: ~50 tests/min (3 workers)
├── Estimated remaining: ~1.2 hours
├── Current batch: batch_20260605_1030
├── Worker status:
│   ├── W1: Running (GPU 0-1)
│   ├── W2: Running (GPU 2-3)
│   └── W3: Running (GPU 4-5)
└── Latest stats: passed=2845, failed=312, error=156
```

### Feishu Notification (Optional)

| Event | Notification |
|-------|--------------|
| Round complete | "Phase 1 Round 1 完成，7740 tests executed" |
| Phase switch | "进入 Phase 2，剩余 18782 tests" |
| Error threshold | "连续错误触发，跳过 test_marlin.py" |
| All complete | "全部测试执行完成，最终统计..." |

---

## Disconnect Recovery

### Background Execution Architecture

```
Local (Windows):
├── test_scheduler.py (scheduler)
├── Monitor process status
├── Periodic progress sync
└── Can disconnect, remote execution unaffected

Remote (t_h20):
├── 3 nohup pytest processes
├── Logs written to ut_logs/
├── PIDs recorded in .pid files
└── Processes run independently, unaffected by local disconnect

SSH Channel:
├── Local → agent.py → bastion → t_h20
├── Command execution: SSH direct execution
├── Log reading: SSH cat command
├── No bastion file storage
```

### Disconnect Recovery Flow

```
Disconnect Detection:
├── agent.py ping fails
├── Record disconnect time to execution_state.json
└── Local monitoring paused

Remote Continues Execution:
├── pytest processes running in background on t_h20
├── Logs continue writing
├── No progress lost

Reconnection Recovery:
├── Read execution_state.json
├── Check remote PID status:
│   ├── ps -p <pid>
│   ├── Parse logs for completed tests
│   └── Update manifest
├── Sync progress to local
├── Append to PROGRESS.md:
│   ### 2026-06-05 XX:XX - Disconnect Recovery
│   - Disconnect time: ...
│   - Remote completed: XX tests
├── Continue scheduling remaining tests

Recovery Time Target: < 30s
```

### execution_state.json Tracking

```json
{
  "current_phase": 1,
  "phase1_status": {
    "total": 13165,
    "completed": 4200,
    "last_test_id": 4200
  },
  "remote_processes": [
    {
      "batch_id": "batch_20260605_1030_w1",
      "pid": 12345,
      "worker": 1,
      "gpu": "0,1",
      "started_at": "2026-06-05T10:30:00",
      "log_file": "ut_logs/phase1/batch_20260605_1030_w1.log",
      "status": "running"
    }
  ],
  "disconnect_count": 2,
  "last_update": "2026-06-05T10:35:00"
}
```

---

## Success Criteria

| Criteria | Target |
|----------|:------:|
| Phase 1 Round 1 completion | ~7,740 tests executed |
| Phase 1 Round 2 completion | ~3,870 tests executed |
| Phase 1 total coverage | 95%+ |
| Phase 2 total coverage | 95%+ |
| Disconnect recovery time | < 30s |
| Progress sync accuracy | 100% |

---

## Estimated Timeline

| Phase | Round | Tests | Duration |
|-------|-------|:------:|:--------:|
| Phase 1 | Round 1 | ~7,740 | 2-3 hours |
| Phase 1 | Round 2 | ~3,870 | 4-6 hours |
| Phase 1 | Round 3 | ~1,290 | 1-2 hours |
| Phase 2 | Round 1 | ~11,269 | 3-4 hours |
| Phase 2 | Round 2 | ~5,635 | 6-8 hours |
| Phase 2 | Round 3 | ~1,878 | 1-2 hours |
| **Total** | - | **31,947** | **18-27 hours** |

---

*Created: 2026-06-05*
*Status: Draft - Pending Approval*