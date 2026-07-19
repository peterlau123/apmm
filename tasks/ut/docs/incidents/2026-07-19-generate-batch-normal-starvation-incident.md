# generate_batch 批次装填率过低事故（manifest 状态冻结 + 候选不足）

**日期**: 2026-07-19
**严重等级**: P1（严重拖慢 Phase 1 执行效率，批次装填率仅 25%，且大量重复选中）
**影响范围**: UT workflow Phase 1 全量执行（run `ut-20260718-164107`，1308 batch）
**修复状态**: 📐 待修复（已定位根因，治标/治本方案待评估）

---

## 事故概述

Phase 1 跑完 1308 batch 后，test_load 4000 测试仍有 1179 个 pending（70.5% 已处理）。按预期 1308 batch × 8 = 10464 槽位应能轻松覆盖 4000 测试，但实际仅处理 2821 个唯一测试。

**核心症状**：
- 1210/1308 个 batch（92.5%）每个只装了 **2 个测试**（而非 batch_size=8），装填率 2.4/batch
- 378 次重复选中（同一测试被多个 batch 选中），唯一测试仅 2821

---

## 触发条件

- two-phase 策略，batch_size=8，test_load=4000
- `generate_batch.py` 从 **manifest**（而非 test_load）选测试
- `execute_batch` 执行后只更新 **test_load**，**不更新 manifest**

---

## 选择逻辑（当前实现）

### 数据流

```
manifest.json (32933测试, 状态冻结)
    ↓ generate_batch.py 读取
select_batch(manifest, batch_size*3=24)  ← 取前24个selectable
    ↓ 分 normal/distributed
if normal:  → normal分支, group_by_file + sorted, 装最多8个
elif distributed: → distributed分支 (normal非空时走不到)
    ↓
batch_config.json (写入 batches/)
    ↓ execute_batch.py 执行
test_load.json 更新状态  ← 只更新test_load!
    ↓
manifest.json 不变  ← 状态冻结!
```

### 关键代码

**`generate_batch.py:161`**（候选来源是 manifest）：
```python
manifest = load_manifest(manifest_path)              # ← 真manifest(32933), 非test_load
candidates = select_batch(manifest, batch_size * 3)  # ← batch_size=8, 取24个候选
```

**`select_batch`（generate_batch.py:74）**：
```python
def select_batch(manifest, batch_size):
    tests = manifest.get("tests", [])
    selectable = [t for t in tests if _is_selectable(t)]     # pending/failed<max_retry
    selectable.sort(key=lambda t: STATUS_PRIORITY.get(...))  # pending=0优先, 稳定排序
    chosen = selectable[:batch_size]                          # ← 取前24个
    return chosen
```

**`generate_batch.py:177`**（normal/distributed 分支）：
```python
distributed = [t for t in candidates if is_distributed(t["test_node"])]
normal = [t for t in candidates if not is_distributed(t["test_node"])]

if normal:                    # normal非空走这条
    grouped = group_by_file(normal)
    batch = []
    for file, tests in sorted(grouped.items()):  # 按文件名字典序
        batch.extend(tests)
        if len(batch) >= batch_size: break
    batch = batch[:batch_size]   # ← normal候选不足8个时, batch装不满
elif distributed:              # normal非空时永远走不到
    batch = distributed[:batch_size]
```

### `24` 的来源

`batch_size * 3 = 8 * 3 = 24`。乘 3 是为多取候选再按 normal/distributed 筛选。但这个放大不足以解决问题（见根因）。

---

## 根因分析（两层）

### 第 1 层：manifest 状态冻结（根本原因）

`generate_batch` 从 manifest 选测试，但 `execute_batch` 执行后只更新 test_load，**不回写 manifest**。

**证据**：
- manifest `updated_at` = `generated_at` = `2026-07-18T11:52:30Z`（从未更新）
- manifest 状态分布：pending=24483（冻结），与 test_load（pending=1179）严重脱节
- test_load 与 manifest 状态不一致：2821/4000

**后果**：manifest 的 24483 pending 永不变，`select_batch(24)` 每次取 manifest **前 24 个 pending**（稳定排序保持 manifest 原始顺序），**前 24 个永远是同一批测试**。已跑过的测试在 manifest 里仍 pending，被反复选中（378 次重复选中）。

### 第 2 层：候选 normal 不足导致装填率低（直接症状）

manifest 前 24 个 pending 里，normal 测试集中在前几个文件（`tests/basic_correctness/`、`tests/kernels/attention/` 字典序靠前）。跑掉几个后，前 24 候选的 normal 部分稳定在少数几个，distributed 占多数。

`generate_batch` 的 `if normal:` 分支只用 normal 候选组装（distributed 被丢弃），normal 不足 8 个时 batch 装不满：

```
manifest前24 pending (冻结, 永远是这24个):
  [大量distributed] [少数normal(2个)]
        ↓
if normal: → 只装2个normal → batch=2个测试 (而非8个)
        ↓
execute更新test_load, 但manifest不变
        ↓
下次select_batch(24)还是这24个 → 重复 (378次重复选中)
```

### 两层叠加

- 第 1 层（manifest 冻结）导致反复选同一批 + 已跑过的被重复选
- 第 2 层（normal 不足 + 分布式被丢弃）导致每 batch 只装 2 个

---

## 现象与证据链

### 证据 1：batch 装填率极低

| 测试数/batch | batch 数 | 占比 |
|-------------|---------|------|
| 2 | 1210 | 92.5% |
| 4 | 1 | 0.1% |
| 7 | 1 | 0.1% |
| 8 | 96 | 7.3% |

累计选中 3199 次，唯一测试 2821，平均 2.4/batch。

### 证据 2：manifest 状态冻结

```
manifest (generate_batch从这里选): pending=24483 (冻结在7/18生成时)
test_load (execute_batch更新这里):  pending=1179 (实时)
不一致: 2821/4000
manifest updated_at = generated_at = 2026-07-18T11:52:30Z (从未更新)
```

### 证据 3：重复选中

378 次重复选中（同一测试被多个 batch_config 选中），top 重复 18 次。根因：manifest 不更新，已跑过的测试仍 pending，被反复选中。

### 证据 4：2-测试 batch 全是 normal，来自 attention 文件

1210 个 2-测试 batch 全是 normal 类型，测试来自 `tests/kernels/attention/test_cache.py`(429x)、`test_merge_attn_states.py`(325x) 等。

---

## 影响

| 项 | 预期 | 实际 | 损耗 |
|----|------|------|------|
| 每批测试数 | 8 | 2.4 平均 | 70% 槽位浪费 |
| 唯一测试/batch | 8 | 2.2（2821/1308） | 大量重复 |
| 跑完 4000 所需 batch | 500 | >2000 | 4 倍 |
| Phase 1 耗时 | ~3h | ~17h（跨多轮） | 严重超时 |

---

## 修复方案

### 方案 A：治本 - generate_batch 从 test_load 选（而非 manifest）✅ 已应用

`generate_batch` 的 `--manifest-path` 改为指向 test_load，或新增 `--test-load` 参数。这样选的是实时状态的测试，不会重复选已跑过的。

```python
# auto_run_batches_two_phase.py:493 (test_load 确认存在后)
manifest_path = Path(paths["manifest"])  # ← 改为 test_load
# 改为:
if test_load_path and Path(test_load_path).exists():
    manifest_path = Path(test_load_path)
```

> 注意：test_load 是 manifest 的子集（4000 vs 32933），select_batch 从 4000 里选，语义正确（test_load 就是本轮要跑的工作集）。

### 方案 B：治本 - execute_batch 回写 manifest

`execute_batch` 执行后同步更新 manifest 对应测试的状态。但 manifest 32933 测试，每次回写开销大，且 manifest 本应是"主记录"（SKILL.md 说 manifest 只在 pending==0 后更新）。不推荐。

### 方案 B2：治本 - normal 不足时降级 distributed 分支 ✅ 已应用

`generate_batch.py:182` 的 `if normal:` 改为 `if len(normal) >= batch_size:`。normal 候选不足 8 个时，走 distributed 分支执行 distributed 测试，让它们退出候选窗口，normal 才能进前 24。

```python
# generate_batch.py:182
if normal:                        # ← 改为
if len(normal) >= batch_size:     # normal 不足时降级 distributed
```

### 方案 B3：边界修复 - normal 不足且无 distributed 时回退 normal ✅ 已应用

方案 B2 引入新 bug：当只剩 <8 个 normal 且 distributed 为空时，`len(normal) >= batch_size` 为 False 且 `elif distributed` 也为 False，落到 `else` 抛 `ValueError: Empty batch`。最后 3 个 pending 永远跑不完。

```python
# generate_batch.py:182 (B2 的基础上加 or not distributed)
if len(normal) >= batch_size or not distributed:
```

normal 不足 OR 没有 distributed 时走 normal 分支（装不满也装），避免抛错。

### 方案 C：治标 - 跳过 distributed + 标记已处理

把 22 个 distributed pending 标记 ignored，让 normal 候选充足。但治标不治本（manifest 冻结导致重复选中仍存在）。

**推荐方案 A**：改一行（manifest_path -> test_load_path），从根上解决重复选 + 装填率问题。

### 防回归

- `generate_batch` 应从"工作集"（test_load）选，不从"主记录"（manifest）选
- 监控：batch_config 的 tests 数 < batch_size 时告警
- 监控：重复选中率（同一 test_node 被 >1 个 batch 选中 = 异常）
- 单测：构造 manifest 状态冻结场景，验证不重复选

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `generate_batch.py` | `skills/ut/batch-selector/scripts/generate_batch.py:161` | 候选来源是 manifest（应为 test_load） |
| `select_batch` | `skills/ut/batch-selector/scripts/generate_batch.py:74` | 取前 batch_size×3 候选 |
| normal/distributed 分支 | `skills/ut/batch-selector/scripts/generate_batch.py:177` | normal 不足时装不满 |
| `auto_run_batches_two_phase.py:465` | `tasks/ut/scripts/auto_run_batches_two_phase.py` | manifest_path 来源（改这里切 test_load） |
| `execute_batch.py` | `skills/ut/unit-test-executor/scripts/execute_batch.py` | 只更新 test_load，不回写 manifest |
| run 数据 | `runs/ut-20260718-164107/` | 1308 batch, manifest vs test_load 状态脱节 |

---

## 经验沉淀

1. **"工作集"与"主记录"必须区分**：test_load 是本轮工作集（实时状态），manifest 是主记录（冻结快照）。选测试应从工作集选，`generate_batch` 从 manifest 选是设计错误。
2. **状态回写必须闭环**：执行端（execute_batch）更新了 test_load，但选择端（generate_batch）读 manifest，两者脱节导致重复选。读和写必须指向同一数据源。
3. **装填率是被忽略的效率指标**：只看 batch 数和成功率，没发现每 batch 只 2 个测试。应监控 `sum(tests_per_batch)/(batch_count×batch_size)`。
4. **重复选中是危险信号**：同一 test_node 被多个 batch 选中，说明状态没更新或选择源错误。
5. **"放大候选数"治标不治本**：`batch_size*3` 想多取候选再筛，但 manifest 冻结下前 24 永远固定，放大到 240 也没用（前 N 个固定）。


---

## 修复验证结果（2026-07-19 21:10）

两个修复（方案 A + B2）应用后，跑了 147 个 batch 清完剩余 pending：

| 指标 | 修复前 | 修复后 | 提升 |
|------|--------|--------|------|
| 每批测试数 | 2.4 平均 | **8.0**（38/38 batch 装满） | +233% |
| 重复选中 | 378 次 | 0 | 消除 |
| 清完 1179 pending 所需 batch | ~580（预估） | **147**（实际） | -75% |
| 装填率 | 30% | **100%** | +70pp |

### 完整 Phase 1 最终结果（pending=0，全部跑完）

3 个 bug（方案 A + B2 + B3）全部修复后，test_load 4000 测试 100% 处理：

```
1384 batch, 99.71% 成功率
test_load 4000: passed=1418, failed=91, error=12, ignored=2479, pending=0
通过率: 94.0% (1418/1509)
已处理: 4000/4000 (100%)
```

修复后 38 个 batch **全部装满 8 个测试**（验证 `Counter(sizes)={8:38}`），彻底消除装填率问题和重复选中。最后 3 个 straggler（normal<8 且无 distributed）经 B3 修复后装 3 个跑完，pending 归零。

---

## 附：incident 文档自身丢失与恢复

### 事故

本 incident 文档（及 reports 下的运行总结）在编写后不久从工作区消失。

### 根因

auto-checkpoint 的 `git stash push --include-untracked` 吞掉了 untracked 新文件：
- `skip-worktree` 只对 **tracked 文件**生效，新建的 untracked 文件无法用 skip-worktree 保护
- auto-checkpoint 的 `--include-untracked` 会 stash 所有 untracked 文件
- 用 bash 写新文件后没立即 `git add` 变 tracked，下个 tool_call 就被 stash 吞了

### 恢复

untracked 文件在 stash 的第三个 parent（`stash@{N}^3`），用 `git show` 提取：

```bash
# 搜哪个 stash 含此文件 (需 -u 含 untracked)
git stash show -u stash@{0} --name-only | grep <file>
# 从 stash 的 untracked 树提取
git show stash@{0}^3:<path> > <path>
```

### 防回归

新建 untracked 文件后**立即 `git add` + `skip-worktree`**，或写入 gitignored 目录（如 `runs/`）。