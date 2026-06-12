# Manifest 结构定义

> 本文档从 SKILL.md 移出，详细描述 Manifest 结构与合并流程

## Phase 1/2 Manifest 结构

```json
{
  "phase": 1,
  "test_list_file": "test_analysis/phase1_test_list.txt",
  "total_tests": 13165,
  "completed_tests": 4200,
  "batch_size": 50,
  "tests": {
    "tests/test_seed_behavior.py": {
      "status": "passed",
      "duration_ms": 1200,
      "executed_at": "2026-06-08T14:00:00+08:00"
    },
    "tests/distributed/test_pipeline_parallel.py": {
      "status": "failed",
      "error_category": "E",
      "error_type": "distributed_gpu_unavailable",
      "error_message": "ValueError: Error initializing distributed",
      "available_gpus": 1,
      "required_gpus": 2,
      "reported_to_supervisor": true,
      "supervisor_response": "pending"
    }
  },
  "summary": {
    "passed": 4000,
    "failed": 150,
    "error": 50,
    "skipped": 0
  }
}
```

---

## Phase 3 Manifest 结构

```json
{
  "phase": 3,
  "source_phases": [1, 2],
  "failed_tests_count": 200,
  "tests": {
    "tests/distributed/test_pipeline_parallel.py": {
      "status": "analyzing",
      "error_category": "E",
      "analysis_result": "等待 Supervisor 提供 GPU 环境",
      "fix_attempt": 0,
      "fix_status": "pending"
    },
    "tests/samplers/test_beam_search.py": {
      "status": "fixed",
      "error_category": "C",
      "fix_commit": "abc123",
      "fixed_at": "2026-06-08T15:00:00+08:00"
    }
  },
  "resolution_summary": {
    "fixed": 50,
    "skipped": 30,
    "pending": 120
  }
}
```

---

## 字段说明

| 字段 | Phase | 说明 |
|------|-------|------|
| `phase` | 1/2/3 | 当前 Phase 编号 |
| `tests.*.status` | 全部 | 测试状态（passed/failed/error/skipped/analyzing/fixed） |
| `error_category` | 失败测试 | 问题分类（C/E/D/P/M/S） |
| `reported_to_supervisor` | E/D/M 类 | 是否已汇报 Supervisor |
| `supervisor_response` | E/D/M 类 | Supervisor 响应状态 |
| `fix_commit` | Phase 3 | 修复提交 SHA |
| `fix_status` | Phase 3 | 修复状态（pending/success/failed） |

---

## Manifest 合并流程

**合并脚本**: `scripts/merge_manifests.py`

### 合并规则

| 规则 | 说明 |
|------|------|
| **求并集** | Phase1 + Phase2 所有测试项保留 |
| **状态一致性** | 同一测试项状态保持一致 |
| **passed 优先** | 在任意 passed 清单中 → `passed` |
| **failed 同步** | Phase1 failed → Phase2 也 failed |
| **无效过滤** | 排除非 pytest 格式的条目 |

### 输入文件

| 文件 | 路径 | 用途 |
|------|------|------|
| `phase1_manifest.json` | `test_analysis/` | Phase1 测试清单 |
| `phase2_manifest.json` | `test_analysis/` | Phase2 测试清单 |
| `ut_test_list_passed.txt` | `test_lists_marked/` | Phase1 passed 测试 |
| `ut_test_list_full_passed.txt` | `test_lists_marked/` | Phase2 passed 测试 |

### 输出文件

| 文件 | 路径 | 说明 |
|------|------|------|
| `manifest.json` | `test_analysis/` | 合并后完整清单 |
| `statistics.json` | `test_analysis/` | 统计信息 |
| `test_list.txt` | `test_analysis/` | 合并后测试列表 |

### 使用方法

```bash
# 预览合并结果（不保存文件）
python scripts/merge_manifests.py --dry-run

# 执行合并
python scripts/merge_manifests.py
```

---

## 合并后结构

```json
{
  "generated_at": "2026-06-08T...",
  "source_files": ["phase1_manifest.json", "phase2_manifest.json"],
  "total_tests": 31244,
  "statistics": {
    "passed": 6411,
    "failed": 1,
    "pending": 24832
  },
  "tests": [
    {
      "id": 1,
      "test_node": "tests/xxx/test_xxx.py::test_func",
      "status": "passed",
      "phase": "phase1+phase2",
      "..."
    }
  ]
}
```

---

## 批量更新单个测试状态

如需更新单个或批量测试状态，**必须同时更新 statistics**：

```bash
# 推荐：使用脚本更新
python scripts/update_test_status.py --test-node "tests/xxx::test_xxx" --status passed

# 批量更新
python scripts/update_test_status.py --batch-file passed_tests.txt --status passed
```

---

*创建日期: 2026-06-09*
*来源: skills/ut/unit-test-executor/SKILL.md*