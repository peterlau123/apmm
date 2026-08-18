# tasks/ut/scripts — run 专用脚本索引

> 本目录存放 UT run 专用的可执行脚本（重试、批处理、清单维护、部署）。
> **通用库脚本已迁移至 [skills/ut/ut_common/scripts/](../../../skills/ut/ut_common/scripts/)**（2026-08-06 重组）。

---

## 📂 目录分组

### 🔄 重试脚本

| 脚本 | 用途 |
|------|------|
| `rerun_selective.py` | **通用选择性重跑器**（batch/ssh 双执行模式；`--run-dir --status --category --match-node --match-error --device-map --limit` 等，见下方用法） |
| `retry_timeout_batches.py` | 重跑 timeout batch（v5 单进程调度器 + 动态 GPU 切批；`--slow-only` 单跑慢测试） |

### 📦 批处理与清单

| 脚本 | 用途 |
|------|------|
| `auto_run_batches_two_phase.py` | Phase 1/2 批处理（生成 test_load → 执行 → 汇总） |
| `merge_batch_manifests.py` | 合并 batch 执行结果到 manifest |
| `completion_watcher.py` | run 完成通知（P3 飞书消息） |

### 🏗️ 部署与分级

| 脚本 | 用途 |
|------|------|
| `start_hermes_ut_runtime.py` | 启动 L4 测试环境（gateways + supervisor） |
| `deploy_tier.py` | 安装/验证 Hermes profiles（tier 部署） |
| `grade_tier.py` | tier verdict 编排（包装 check_expected） |
| `load_deployment_config.py` | 加载 workflow 部署配置 |
| `hf_env.sh` / `modelscope_env.sh` | HF / ModelScope 离线环境配置 |

### 📊 报告

| 脚本 | 用途 |
|------|------|
| `weekly_compat_report.py` | 每周兼容性问题检查报告（daily 检查 + weekly 汇总） |

---

## 🚀 rerun_selective.py 用法速查

```bash
# 重跑 ignored（默认排除兼容性 SKIP 类）
python3 rerun_selective.py --run-dir runs/ut-20260807-110322 --status ignored

# 重跑 flaky（ProcessRaisedException）
python3 rerun_selective.py --run-dir runs/ut-20260806-103121 --status failed \
    --match-error ProcessRaisedException

# 重跑 marlin 算子类
python3 rerun_selective.py --run-dir runs/ut-20260806-103121 --status failed \
    --match-error moe_wna16_marlin_gemm

# 补跑前 80 条 pending
python3 rerun_selective.py --run-dir runs/ut-20260806-103121 --status pending --limit 80

# kernel 串行 SSH 直跑（断点续跑自动: progress 文件 + 已跑 batch 目录跳过）
python3 rerun_selective.py --run-dir runs/ut-20260718-164107 --status ignored \
    --match-node tests/kernels/attention/ --executor ssh --tag kernel

# device-map（GPU1 坏卡规避: 运行层 cuda:1→cuda:0, 回写还原）
python3 rerun_selective.py --run-dir runs/xxx --status failed --device-map cuda:1=cuda:0
```

---

## 🧹 已迁移至 ut_common/scripts（通用库）

| 脚本 | 新位置 | 说明 |
|------|--------|------|
| `check_expected.py` | `skills/ut/ut_common/scripts/` | 通用 run-vs-expected 比较器（被 grade_tier/feishu_api 引用） |
| `generate_test_load.py` | `skills/ut/ut_common/scripts/` | 从 manifest 抽取 test_load（被 batch-selector/terminal-workflow 引用） |
| `check_hf_cache_refs.py` | `skills/ut/ut_common/scripts/` | HF 模型缓存预检 |

## 🗑️ 已整合/删除（2026-08-18 重构）

| 原脚本 | 去向 |
|------|------|
| `rerun_flaky.py` / `rerun_marlin.py` / `run_remaining_80.py` / `rerun_ignored_remaining.py` | 整合进 `rerun_selective.py`（--match-error/--status pending/--category/--limit 覆盖） |
| `retry_kernel_tests.py` | 整合进 `rerun_selective.py --executor ssh`（含断点续跑） |
| `build_marlin_ext.py` / `build_moe_c_full.py` / `build_c_marlin_extra.py` / `verify_*` / `stub_*` / `clean_marlin_build.sh` / `full_rebuild.sh` | 删除（8000 战役残留，算子已修复；git history 可找回） |
| `analyze_triton_amd.py` | 删除（一次性排障脚本，结论已落报告） |
| `regenerate_and_merge_manifest.py` | 删除（一次性重建工具；merge_batch_manifests 覆盖持续需求） |
| `migrate_manifest.py` | 已删除（旧副本，ut_common 已有新版，2026-08-06） |

---

## ⚠️ 引用更新提示

以下调用方指向的路径请勿改回：
- `grade_tier.py` → `_CHECK_EXPECTED = <repo>/skills/ut/ut_common/scripts/check_expected.py`
- `auto_run_batches_two_phase.py` → subprocess 调用 `ut_common/scripts/generate_test_load.py`
- 单元测试 `test_check_expected.py` / `test_scripts_reorg_migration.py` / `test_rerun_selective.py` 已同步

*更新时间: 2026-08-18*
