# PYTHONPATH 泄漏 Incident

**日期**: 2026-06-24
**严重等级**: P0（阻塞 L4 测试）
**影响范围**: 所有 Hermes Gateway profiles (ut-orchestrator, ut-executor, ut-fixer)
**修复状态**: ✅ 已修复

---

## 问题描述

L4 测试启动时，Orchestrator worker 执行 `generate_batch.py` 失败，报错：

```
ModuleNotFoundError: No module named 'jsonschema'
```

**预期行为**: Worker 应使用项目环境（anaconda3）的 jsonschema
**实际行为**: Worker 使用了 Hermes venv 的 PYTHONPATH，找不到 jsonschema

---

## 根因分析

### 泄漏链路

```
start_gateway.py (启动者环境)
    ↓ Popen(["hermes", "gateway", "run"])
Gateway 进程 (继承启动者 PYTHONPATH)
    ↓ 调度 worker scripts
Worker 进程 (继承 Gateway PYTHONPATH)
    ↓ import jsonschema
ModuleNotFoundError ❌
```

### 为什么泄漏？

1. **Hermes Gateway 在独立 profile 中运行**
   - Gateway 进程通过 `start_gateway.py` 启动
   - `Popen` 继承启动者的环境变量（包括 PYTHONPATH）

2. **启动者环境有 PYTHONPATH**
   - 如果启动者在 Hermes venv 中，PYTHONPATH 会指向 Hermes 的依赖路径
   - Worker scripts 优先使用 PYTHONPATH 中的模块，而不是项目环境

3. **Worker 需要 jsonschema**
   - `skills/ut/*/scripts/*.py` 使用 `jsonschema.validate()` 验证 JSON
   - Hermes venv 可能没有安装 jsonschema（或版本不兼容）

---

## 修复方案

### 双重防护策略

| 层级 | 修复位置 | 作用 | 状态 |
|---|---|---|---|
| **Layer 1** | `start_gateway.py` | Gateway 启动时清除 PYTHONPATH（主修复） | ✅ 已实施 |
| **Layer 2** | Worker scripts 开头 | Worker 自我清除 PYTHONPATH（fallback） | ✅ 已实施 |

### Layer 1: start_gateway.py（主修复）

**修改位置**: `skills/ut/terminal-workflow/scripts/start_gateway.py`

```python
def start_profile_gateway(profile, logs_dir):
    # ...

    # Clear PYTHONPATH to prevent Hermes venv environment leak
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)

    kwargs = {"stdout": out, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL, "env": env}
    # ... creationflags / preexec_fn

    proc = subprocess.Popen(["hermes", "gateway", "run"], **kwargs)
```

**优点**:
- 集中修复，所有 Gateway profiles 统一处理
- 部署自动化（通过 `deploy_tier.py` 启动）
- 覆盖 L4 生产场景

### Layer 2: Worker scripts（fallback）

**修改位置**: 6 个 Worker scripts 开头

```
skills/ut/batch-selector/scripts/generate_batch.py
skills/ut/unit-test-executor/scripts/execute_batch.py
skills/ut/failure-handler/scripts/analyze_failures.py
skills/ut/failure-handler/scripts/generate_handled_manifest.py
skills/ut/manifest-updater/scripts/update_manifest.py
skills/ut/manifest-updater/scripts/update_test_load.py
```

**代码**:
```python
import os
# Clear PYTHONPATH inherited from Hermes venv (see SKILL pitfall)
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']
```

**优点**:
- 防御性最强（覆盖所有 Gateway 启动方式）
- 即使手动启动 Gateway 也能防护

---

## 验证步骤

### 手动验证

1. **启动 Gateway**（通过 `start_gateway.py`）
2. **检查 Gateway 进程环境**
   ```bash
   ps aux | grep hermes
   cat /proc/<pid>/environ | tr '\0' '\n' | grep PYTHONPATH
   ```
   **预期**: PYTHONPATH 不存在或为空

3. **触发 Worker 执行**（L4 batch 选择）
4. **检查 Worker 日志**
   - 无 `ModuleNotFoundError: jsonschema`
   - batch 选择成功执行

### L4 测试验证

**日期**: 2026-06-24 21:23

**结果**:
- ✅ Orchestrator worker 成功执行 `generate_batch.py`
- ✅ batch 选择完成（batch_20260624_212355）
- ✅ Executor worker 成功启动

**问题**: 后续测试超时（watchdog SIGKILL），但这是另一个问题（见 `2026-06-24-L4-test-issues-and-fixes.md`）

---

## 影响范围

### 直接影响

| Profile | 影响 | Worker scripts |
|---|---|---|
| `ut-orchestrator` | batch 选择失败 | `generate_batch.py` |
| `ut-executor` | pytest 执行失败 | `execute_batch.py` |
| `ut-fixer` | 错误分析失败 | `analyze_failures.py` |

### 间接影响

- L4 测试无法启动（Orchestrator 第一轮就失败）
- Gateway 任务被 blocked
- Workflow 状态机卡住

---

## 防止复发

### 代码层面

1. ✅ `start_gateway.py` 清除 PYTHONPATH（主修复）
2. ✅ Worker scripts 清除 PYTHONPATH（fallback）
3. ⏳ 更新 SKILL 文档（见 `2026-06-24-L4-test-issues-and-fixes.md` §3.1）

### 测试层面

**新增测试**: 验证 Gateway 启动时 PYTHONPATH 清除

```python
# tests/ut/unit/test_gateway_startup.py
def test_gateway_startup_clears_pythonpath():
    """验证 start_gateway.py 启动 Gateway 时清除 PYTHONPATH"""
    with mock.patch.dict(os.environ, {'PYTHONPATH': '/fake/hermes/venv'}):
        result = start_profile_gateway("ut-executor", logs_dir)
        # 验证 Gateway 进程环境无 PYTHONPATH
```

**优先级**: P2（建议在下次迭代添加）

---

## 相关文档

| 文档 | 用途 |
|---|---|
| `2026-06-24-L4-test-issues-and-fixes.md` | L4 测试所有问题综合报告 |
| `skills/ut/terminal-workflow/scripts/start_gateway.py` | Gateway 启动脚本（主修复点） |
| `skills/ut/*/scripts/*.py` | Worker scripts（fallback 修复点） |
| `tasks/ut/docs/guides/hermes-gateway-service.md` | Gateway 服务运维指南 |

---

## Lessons Learned

1. **环境隔离重要性**: Gateway worker 应完全隔离，不继承启动者的环境变量
2. **双重防护策略**: 主修复 + fallback，防御性优先
3. **Gateway profile 配置**: `.env` 是 user-owned，无法通过 distribution 清除 PYTHONPATH
4. **部署自动化**: `deploy_tier.py` 应管理 Gateway 启动流程，避免手动启动

---

**报告生成**: 2026-06-25
**作者**: UT Supervisor Agent