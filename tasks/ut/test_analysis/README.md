# test_analysis 目录说明

测试数据统计与分析相关文件汇总。

---

## 目录结构（2026-06-08 合并后）

```
test_analysis/
├── test_list.txt               # ★ 统一测试清单（17,391 tests + 错误信息）
├── manifest.json               # ★ 统一测试状态（JSON格式，含statistics）
│
├── archive/                    # 原始文件备份
│   ├── phase1_manifest_*.json
│   ├── phase1_test_list_*.txt
│   ├── phase2_manifest_*.json
│   └── phase2_test_list_*.txt
│
├── scripts/                    # 分析脚本
│   ├── merge_phases.py         # ★ 合并脚本（生成test_list.txt和manifest.json）
│   ├── generate_manifest.py    # JSON清单生成
│   ├── parse_results.py        # 结果解析
│   ├── merge_manifests.py      # 旧合并脚本（已弃用）
│   └ run_collect.sh            # pytest collect脚本
│
├── test_lists_marked/          # 标记后的测试清单（历史数据）
│   ├── marked_summary.json     # 标记汇总
│   ├── ut_test_list_passed.txt
│   ├── ut_test_list_to_run.txt
│   ├── ut_test_list_full_passed.txt
│   └── ut_test_list_full_to_run.txt
│
├── remote_log_summary/         # 远程日志摘要
│   ├── passed_ut_cases-20260606.txt
│   ├── failed_ut_cases-20260606.txt
│   ├── error_ut_cases-20260606.txt
│   └── README.md
│
├── passed_cases_unique.txt     # 通过测试汇总（唯一）
├── failed_cases_unique.txt     # 失败测试汇总（唯一）
├── error_cases_unique.txt      # 错误测试汇总（唯一）
├── error_statistics_latest.json # 错误统计
│
└── README.md                   # 本文件
```

---

## 文件来源说明

### 核心文件

| 文件 | 来源 | 生成方式 |
|------|------|----------|
| `test_list.txt` | Phase1 + Phase2 合并 | `scripts/merge_phases.py` 执行合并 |
| `manifest.json` | Phase1 + Phase2 合并 | `scripts/merge_phases.py` 执行合并 |

### 原始文件（已备份到 archive/）

| 原文件 | 来源 | 说明 |
|--------|------|------|
| `phase1_test_list.txt` | 远程 pytest collect | 第一次收集（13,165 tests），因import error数量较少 |
| `phase2_test_list.txt` | 远程 pytest collect | 解决依赖后重新收集（32,253 tests），仍有收集错误 |
| `phase1_manifest.json` | `generate_manifest.py` | 从 phase1_test_list.txt 生成的JSON清单 |
| `phase2_manifest.json` | `generate_manifest.py` | 从 phase2_test_list.txt 生成的JSON清单 |

### 标记清单（test_lists_marked/）

| 文件 | 来源 | 生成方式 |
|------|------|----------|
| `ut_test_list_passed.txt` | 日志回溯分析 | 从历史ut_logs提取已通过的测试（6,293个） |
| `ut_test_list_to_run.txt` | 清单减去passed | `ut_test_list.txt - ut_test_list_passed.txt` |
| `ut_test_list_full_passed.txt` | 日志回溯分析 | Phase2已通过测试（6,411个） |
| `ut_test_list_full_to_run.txt` | 清单减去passed | `ut_test_list_full.txt - ut_test_list_full_passed.txt` |
| `marked_summary.json` | 脚本汇总 | 记录passed/to_run的数量统计 |

### 日志摘要（remote_log_summary/）

| 文件 | 来源 | 生成方式 |
|------|------|----------|
| `passed_ut_cases-*.txt` | 远程服务器 | 从 `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/` grep提取 |
| `failed_ut_cases-*.txt` | 远程服务器 | 同上，grep "FAILED" |
| `error_ut_cases-*.txt` | 远程服务器 | 同上，grep "ERROR" |

### 汇总文件

| 文件 | 来源 | 生成方式 |
|------|------|----------|
| `passed_cases_unique.txt` | 日志摘要 | 多个passed文件去重合并 |
| `failed_cases_unique.txt` | 日志摘要 | 多个failed文件去重合并 |
| `error_cases_unique.txt` | 日志摘要 | 多个error文件去重合并 |
| `error_statistics_latest.json` | 远程日志 | 统计各类错误的出现次数 |

---

## 合并脚本说明

`scripts/merge_phases.py` 执行以下操作：

1. **合并 test_list**
   - 解析 Phase1 和 Phase2 的测试节点（`tests/xxx.py::test_func` 格式）
   - 求并集，去重后按文件路径排序
   - 保留 Phase2 的错误/警告信息（pytest collect output）

2. **合并 manifest.json**
   - 以 `test_node` 为唯一标识
   - 状态同步规则：
     - Phase1 `failed` → 合并后 `failed`（最高优先级）
     - 任一 `passed` → 合并后 `passed`
     - 都 `pending` → 合并后 `pending`

3. **重新计算 statistics**
   - 根据合并后的 tests 数组统计各状态数量

4. **备份原始文件**
   - 备份到 `archive/` 目录，文件名带时间戳

---

## 执行命令记录

```bash
# 生成 Phase1 清单（远程服务器）
cd /gpfs/gcsp/M2.7_verify/vllm
pytest --collect-only -q 2>&1 | tee ut_test_list.txt

# 生成 Phase2 清单（解决依赖后）
pytest --collect-only -q --ignore-glob="tests/**/*rocm*" ... 2>&1 | tee ut_test_list_full.txt

# 本地合并
python scripts/merge_phases.py
```

---

## 注意事项

- **test_list.txt** 包含 pytest collect 的完整输出，末尾有 ERROR/Warning 信息
- **manifest.json** 是状态管理的主文件，后续测试执行应更新此文件
- **archive/** 保留原始文件，可用于追溯或重新合并
- 实时进度见 `tasks/ut/PROGRESS.md`