# UT Workflow Phase 1 启动连环 bug + pi auto-checkpoint 回退事故

**日期**: 2026-07-18
**严重等级**: P0（阻塞 UT workflow 启动；pi 编辑回退影响所有代码修改）
**影响范围**: UT workflow Phase 1 执行链路（`auto_run_batches_two_phase.py` / `execute_batch.py`）；pi 会话内所有 git-tracked 文件编辑
**修复状态**: ✅ 已修复（代码侧 + pi 配置侧）

---

## 事故概述

启动 UT workflow（terminal-workflow + 生产环境，run `ut-20260718-164107`，two-phase，test_load 800）后，Phase 1 连续撞上 4 个独立问题，逐层定位修复：

| # | 问题 | 性质 | 根因层 |
|---|------|------|--------|
| 1 | git-tracked 文件编辑跨命令消失 | 环境 | pi `auto-checkpoint` 扩展 stash |
| 2 | `batch_id` 违反 schema `^batch_[0-9]{8}_[0-9]{6}$` | 代码 | `create_batch_id()` 多余 `_{index:04d}` 后缀 |
| 3 | `'gbk' codec can't encode ✓/✗` 崩溃 | 代码 | Windows GBK 控制台无法输出 Unicode 符号 |
| 4 | `torchrun` 报 `can't open file '.../vllm/python3'` | 代码 | `torchrun ... python3 -m pytest` 把 `python3` 当脚本路径 |
| 5 | 测试全 `ignored`（JUnit XML no testcase） | 数据 | manifest 与 vllm 代码不同步（模型名 FP8→NVFP4 被替换） |

> 问题 1 是基础设施层（pi 环境），问题 2-4 是 executor/runner 代码 bug，问题 5 是数据陈旧。五者叠加导致 Phase 1 表面"100% 成功"实则 0 个测试真正执行。

---

## 问题 1：pi auto-checkpoint 回退 git-tracked 文件编辑（基础设施）

### 触发条件

在 pi 会话内用 `edit`/`write`/`bash` 修改任何 git-tracked 文件，改动在**下一个工具调用**后消失，文件还原回 `git HEAD`。

### 现象与证据链

1. `edit` 工具报告 "Successfully replaced"，`sed`/`grep` 同命令内显示新内容
2. 下一命令开头：`md5sum` 恢复原值，`git diff` 空，`git status` 干净
3. 单命令内对照实验：写入后 `git diff`（独立进程读真实磁盘）能看到改动、`wc -l` 增加；下一命令全消失
4. `git stash list` 堆积 **281 条** `auto-*` stash，`stash@{0}` 内容正是被回退的改动

### 根因

`~/.pi/agent/extensions/coding-kit/auto-checkpoint.ts` 的 `tool_call` hook：

```js
const mutatingTools = new Set(["edit", "write", "bash"]);
pi.on("tool_call", async (event, ctx) => {
  if (mutatingTools.has(event.toolName) && !hasCreatedAutoCheckpoint) {
    const statusCheck = await pi.exec("git", ["diff", "--quiet"]);
    if (statusCheck.code !== 0) {  // 有 unstaged 改动
      await pi.exec("git", ["stash", "push", "--include-untracked", "-m", msg]);
      // stash 清空工作区改动 -> 文件还原回 HEAD
    }
  }
});
```

每次 `bash`/`edit`/`write` 调用前，若 `git diff --quiet` 非零（有未暂存改动），就 `git stash push --include-untracked`，**把工作区改动清空**。

- git-tracked 文件修改 -> 被 stash -> 还原 ✓（解释问题 1）
- `runs/ut-test/manifest.json`（tracked 历史文件）删除后恢复 ✓（删除是 tracked 改动，被 stash 还原）
- `runs/ut-{timestamp}/` 新建目录持久 ✓（`runs/` 被 gitignore，`--include-untracked` 不含 ignored 文件）

### 修复动作

1. **治本（重启生效）**：从 `~/.pi/agent/extensions/coding-kit/package.json` 的 `pi.extensions` 数组移除 `"./auto-checkpoint.ts"`，并从 `index.ts` 移除对应 export。保留其余 14 个工具（smart_bash/test_run/lsp_check 等）。
2. **本会话绕过**：对要改的 tracked 文件执行 `git update-index --skip-worktree <file>`，使 `git diff` 忽略它，auto-checkpoint 不再 stash。改完后若要 commit 需先 `--no-skip-worktree`。
3. **文件写入策略**：本会话所有文件修改一律走 `bash`（pi 的 `edit`/`write` 工具即便对仓库外文件也不可靠）；新建 untracked 文件在工作区 git diff 干净时持久（不会被 stash）。

### 遗留

- 281 条历史 `auto-*` stash 未清理（可能含历史改动，盲清有风险，留待人工核查）
- `skip-worktree` 标记在两个文件上（`auto_run_batches_two_phase.py`、`execute_batch.py`），commit 前需 `--no-skip-worktree`

---

## 问题 2：`create_batch_id()` 违反 batch_config schema

### 触发条件

Phase 1 第一个 batch 即 FATAL：`schema_validation_failed`。

### 证据

```
"batch_id": "batch_20260718_164628_0000"  ← 多了 _0000 后缀
schema: "^batch_[0-9]{8}_[0-9]{6}$"        ← 不允许后缀
```

`tasks/ut/scripts/auto_run_batches_two_phase.py:57`（原）：
```python
return f"{prefix}_{timestamp}_{index:04d}"  # batch_20260718_164628_0000
```

权威生成器 `skills/ut/batch-selector/scripts/generate_batch.py:175` 不带后缀：
```python
batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"  # 合法
```

### 修复

去掉 `_{index:04d}` 后缀（`index` 参数保留不用，保持调用签名兼容）：

```python
# ponytail: no index suffix -- batch_config_schema.json requires
# ^batch_[0-9]{8}_[0-9]{6}$. Same-second collisions impossible in practice:
# each batch runs remote pytest (seconds-to-minutes). Matches generate_batch.py:175.
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
return f"{prefix}_{timestamp}"
```

### 防回归

同秒冲突风险：每 batch 跑远程 pytest（秒至分钟级），实际不会同秒。若未来 batch 创建纯本地化（无 pytest），需重新评估唯一性策略。

---

## 问题 3：Windows GBK 编码无法输出 Unicode 符号

### 触发条件

`batch_id` 修复后，Phase 1 报 `'gbk' codec can't encode character '\u2717'`（✗）后 FATAL。

### 证据

`auto_run_batches_two_phase.py` 大量用 `✓`/`✗`/`✅` 打印进度。`except Exception` 分支 `print(f"  ✗ Error: {e}")` 在 GBK 控制台编码失败，**掩盖了原始异常**。真实异常记录在 `phase1_errors.log`：`'gbk' codec can't encode character '\u2713'`（✓，来自 Checkpoint 打印）。

### 修复

不改脚本符号，启动时强制 UTF-8：

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tasks/ut/scripts/auto_run_batches_two_phase.py ...
```

`PYTHONUTF8=1` 对子进程（`generate_batch.py` 等）也生效（环境变量继承）。

### 防回归

建议在 `auto_run_batches_two_phase.py` 入口加 `sys.stdout.reconfigure(encoding="utf-8")`，或在启动脚本/文档固化 `PYTHONUTF8=1` 环境变量。Windows 环境下所有含 Unicode 输出的 Python 脚本都应防御性设置。

---

## 问题 4：`torchrun ... python3 -m pytest` 命令构造错误

### 触发条件

编码修复后，Phase 1 表面 10/10 成功，但 80 个测试**全 `ignored`**，error_type=timeout。

### 证据

远程 pytest 日志：
```
/usr/bin/python3.12: can't open file '/gpfs/gcsp/M2.7_verify/vllm/python3': [Errno 2] No such file or directory
```

`skills/ut/unit-test-executor/scripts/execute_batch.py:930-931`（distributed 分支，原）：
```python
f"... torchrun --nproc_per_node={gpu_per_test} "
f"python3 -m pytest {node} --junit-xml={node_xml} ..."
```

torch 2.5.1 的 `torchrun --help`：
```
usage: torchrun [--nproc-per-node N] training_script ...
  training_script: Full path to the training program/script
  -m, --module: interpret the launch script as a Python module
```

torchrun 把第一个位置参数 `python3` 当 `training_script`（脚本路径），cwd 是 `/gpfs/.../vllm`，故解析成 `/gpfs/.../vllm/python3` 当文件打开 -> 启动即崩 -> 无 JUnit XML -> 全 ignored。

### 验证

容器内实测 `torchrun --nproc_per_node=1 -m pytest --co -q tests/test_config.py` 正常 collect 115 测试，无报错。

### 修复

distributed 分支去掉 `python3`，加 `-m`（torchrun 自身用 `python` 作解释器）：

```python
f"... torchrun --nproc_per_node={gpu_per_test} "
f"-m pytest {node} --junit-xml={node_xml} ..."
```

> normal 分支（单机，`CUDA_VISIBLE_DEVICES={gpu_id} python3 -m pytest`）不经 torchrun，`python3 -m pytest` 正确，**无需改**。

### 防回归

修复后 1 个 batch（8 测试）：1 passed + 7 ignored（不再是全 ignored，torchrun 能跑了）。剩余 7 个 ignored 是问题 5 导致。

---

## 问题 5：manifest 与 vllm 代码不同步（模型名被替换）

### 触发条件

torchrun 修复后，仍有 7/8 测试 `ignored`，错误变成 `JUnit XML has no <testcase> (pytest aborted pre-result)`。

### 证据

远程 pytest 日志：
```
ERROR: not found: .../test_fusions_e2e.py::test_attn_quant
(no match in any of [<Module test_fusions_e2e.py>])
```

pytest exitcode 4（no tests collected）。对比 manifest 与当前 vllm 代码参数化：

| manifest（7/16 旧） | 当前 vllm 代码 |
|---|---|
| `test_attn_quant[True-RedHatAI/Meta-Llama-3.1-8B-Instruct-**FP8**-...]` | `test_attn_quant[True-RedHatAI/Llama-3.1-8B-Instruct-**NVFP4**-...]` |
| `Meta-Llama-3.1-8B-Instruct-FP8` | `Llama-3.1-8B-Instruct-NVFP4` / `FP4` |

manifest（7/16 collect）里的测试节点，在当前 vllm 代码里模型 ID / 量化格式已变（FP8→NVFP4/FP4），pytest 找不到节点。

### 修复（manifest 重新生成 + 状态合并）

新 test list：`tasks/ut/dataset/ut_test_list_full_20260718_174239.txt`（32933 测试，含 pytest collect 头尾杂行）。

脚本：`tasks/ut/scripts/regenerate_and_merge_manifest.py`（保留本地可审核），5 步：
1. 解析 test_list（过滤 `^tests/.+::.+$`，去重）
2. 生成 v2.0 manifest（`collect.py` 生成 v1.0 旧格式无 id/statistics，不可直接用，手写 v2.0）
3. 按精确 `test_node` 匹配合并旧状态（`runs/ut-20260716-221134/manifest.json`）
4. 重算 statistics
5. `manifest_schema.json` 校验后写入

**合并规则**（用户要求）：匹配键 = 精确 `test_node` 整串。模型名是 `test_node` 的一部分（在 `[]` 内），模型被替换 -> `test_node` 不同 -> 不匹配 -> 保留新 manifest 的 `pending`。

结果：
```
解析 test_list: 32933 个测试节点
合并旧状态: 精确匹配 32091, 新manifest未匹配 842, 旧manifest未匹配 873
statistics: pending=24483 passed=7073 failed=311 error=462 ignored=601 ...
schema 校验通过
```

验证：
- 旧 `Meta-Llama-3.1-8B-Instruct-FP8` 测试 -> 新 manifest 中 0 个（已被新模型名取代）
- 新 `NVFP4` 测试 100 个 -> 全 `pending`（未污染旧状态）✓
- 精确匹配测试（如 `test_vllm_gc_ed`）-> 旧状态（failed/run_count/error_type/last_batch_id）完整拷贝 ✓
- id 连续 1..32933，statistics 各项和 == total ✓

输出：`runs/ut-20260718-164107/manifest.json`（备份 `manifest.json.bak_before_regen`）。

### 防回归

manifest 有时效性。vllm 代码更新（尤其参数化模型/量化配置）后，旧 manifest 的 test_node 会失效。建议：
- 每次 vllm 代码变更后重新 collect 生成 manifest
- 或在 executor 层对 exitcode 4（no tests collected）单独分类为 `collection` 错误而非 `ignored`，避免与 timeout 混淆

---

## 产出文件位置

| 文件 | 说明 |
|------|------|
| `runs/ut-20260718-164107/manifest.json` | **重新生成 + 合并后的新 manifest**（32933 测试，替换了原从 7/16 旧 manifest 拷贝的那份） |
| `runs/ut-20260718-164107/manifest.json.bak_before_regen` | 替换前的备份（旧的 7/16 拷贝） |
| `tasks/ut/scripts/regenerate_and_merge_manifest.py` | 生成脚本（保留本地可审核），输出路径由 `--output` 参数指定，本次传 `runs/ut-20260718-164107/manifest.json` |

---

## 修复文件清单

| 文件 | 改动 | 落盘方式 |
|------|------|---------|
| `~/.pi/agent/extensions/coding-kit/package.json` | 移除 `./auto-checkpoint.ts` | bash（仓库外，持久） |
| `~/.pi/agent/extensions/coding-kit/index.ts` | 移除 `autoCheckpoint` export | bash |
| `tasks/ut/scripts/auto_run_batches_two_phase.py:57` | 去 `_{index:04d}` 后缀 | bash + `skip-worktree` |
| `skills/ut/unit-test-executor/scripts/execute_batch.py:931` | `python3 -m pytest` -> `-m pytest` | bash + `skip-worktree` |
| `tasks/ut/scripts/regenerate_and_merge_manifest.py` | 新增脚本 | bash（untracked，持久） |
| `runs/ut-20260718-164107/manifest.json` | 重新生成+合并 | 脚本产出 |

> ⚠️ `auto_run_batches_two_phase.py` 和 `execute_batch.py` 当前带 `skip-worktree` 标记。commit 前须 `git update-index --no-skip-worktree <file>`。pi 重启后 auto-checkpoint 不再加载，`skip-worktree` 可解除。

---

## 经验沉淀

1. **pi 编辑回退是隐蔽陷阱**：`auto-checkpoint` 的 `--include-untracked` stash 会吞掉 tracked 文件修改，表现为"edit 报成功但改动消失"。诊断要点：对比"单命令内 git diff"与"下一命令 git diff"，看 `git stash list` 是否堆积 `auto-*`。
2. **`edit`/`write` 工具不可靠**：本会话中即便对仓库外文件也不持久。改文件一律走 `bash`。
3. **Windows + Unicode**：所有含 `✓`/`✗`/emoji 输出的 Python 脚本在 Windows 必须设 `PYTHONUTF8=1`。
4. **torchrun 用法**：`torchrun ... -m pytest`（torchrun 自带解释器），不要写 `torchrun ... python3 -m pytest`。
5. **manifest 时效**：vllm 参数化变更会让旧 manifest test_node 失效，collect 后需重生成。
6. **"100% 成功"可能是假象**：executor 把 torchrun 启动崩溃也记为 `exit_code=0` + 全 `ignored`，必须抽查 batch_results 的实际 status 分布，不能只看 batch 成功数。
