# tasks/ut/scripts — run 专用脚本索引

> 本目录存放 UT run 专用的可执行脚本（重试、批处理、清单维护、部署）。
> **通用库脚本已迁移至 [skills/ut/ut_common/scripts/](../../../skills/ut/ut_common/scripts/)**（2026-08-06 重组）。

---

## 📂 目录分组

### 🔄 重试脚本（Phase 2 重跑）

| 脚本 | 用途 |
|------|------|
| `retry_timeout_batches.py` | 重跑 timeout batch（v5 单进程调度器 + 动态 GPU 切批；`--slow-only` 单跑慢测试） |
| `retry_kernel_tests.py` | kernel 测试串行重跑（`--device-map` 映射异常卡，断点续跑） |

### 📦 批处理与清单

| 脚本 | 用途 |
|------|------|
| `auto_run_batches_two_phase.py` | Phase 1/2 批处理（生成 test_load → 执行 → 汇总） |
| `merge_batch_manifests.py` | 合并 batch 执行结果到 manifest |
| `regenerate_and_merge_manifest.py` | 重新生成并合并 manifest |
| `completion_watcher.py` | run 完成通知（P3 飞书消息） |

### 🏗️ 部署与分级

| 脚本 | 用途 |
|------|------|
| `start_hermes_ut_runtime.py` | 启动 L4 测试环境（gateways + supervisor） |
| `deploy_tier.py` | 安装/验证 Hermes profiles（tier 部署） |
| `grade_tier.py` | tier verdict 编排（包装 check_expected） |
| `hf_env.sh` / `modelscope_env.sh` | HF / ModelScope 离线环境配置 |

---

## 🧹 已迁移至 ut_common/scripts（通用库）

| 脚本 | 新位置 | 说明 |
|------|--------|------|
| `check_expected.py` | `skills/ut/ut_common/scripts/` | 通用 run-vs-expected 比较器（被 grade_tier/feishu_api 引用） |
| `generate_test_load.py` | `skills/ut/ut_common/scripts/` | 从 manifest 抽取 test_load（被 batch-selector/terminal-workflow 引用） |
| `check_hf_cache_refs.py` | `skills/ut/ut_common/scripts/` | HF 模型缓存预检 |

**已删除**：`migrate_manifest.py`（旧副本，ut_common 已有新版）。

---

## ⚠️ 引用更新提示

迁移后以下调用方已指向新路径（勿改回）：
- `grade_tier.py` → `_CHECK_EXPECTED = <repo>/skills/ut/ut_common/scripts/check_expected.py`
- `auto_run_batches_two_phase.py` → subprocess 调用 `ut_common/scripts/generate_test_load.py`
- 单元测试 `test_check_expected.py` / `test_scripts_reorg_migration.py` 已同步

*更新时间: 2026-08-06*
