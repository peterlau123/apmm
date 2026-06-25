# §7 实现计划 — Executor 并行 GPU 调度 + JUnit 结果

- 日期：2026-06-24
- 依据：`tasks/ut/docs/designs/2026-06-24-executor-parallel-gpu.md` §4/§7
- §6 实测：两项已通过（bastion 500KB 无截断；pytest 9 `--tb=long` failure 22221B 不截断）

## 0. 关键澄清（探索结论）

- **active path 只有一个**：`skills/ut/unit-test-executor/scripts/execute_batch.py`，被 `skills/ut/workflow/scripts/hermes_runner.py` + 两个 SKILL.md 调用。
- **遗留废弃模块**（不进 active path，本计划默认不动）：`batch_test_runner.py`、`gpu_scheduler.py`、`parallel_batch_executor.py`、`remote_test_runner.py`。仅被 06-05~06-15 旧 plan/design/周报引用，无 active import。§7 新增的 `_detect_free_gpus`/`_cleanup_zombie`/`_parse_junit` **直接加进 `execute_batch.py`**，不复用旧 `gpu_scheduler.py`（旧版是 round-robin + xdist 思路，与设计冲突，复用=背债）。
- **schema**：`batch_results_schema.json` tests entry `additionalProperties:false` → 加 `gpu_id` 须同步改 schema。
- **下游**：`skills/ut/manifest-updater/scripts/update_manifest.py` 只读 `test_node/status/error_type`，已有 `duration_ms/exit_code` 写入路径；加 `gpu_id` 对下游透明（忽略未知字段）。
- **pytest 9 偏差**（§6 实测发现）：`--junit-logging=out-err` CLI flag 不存在，改 `-o junit_logging=out-err`。

## 1. 改动文件

| 文件 | 改动 |
|---|---|
| `skills/ut/unit-test-executor/scripts/execute_batch.py` | 核心：串行 → 并发 N×docker exec + GPU 检测/清理 + JUnit 解析；watchdog 模板重写（删 idle、per-test wall 300s、setsid+杀PGID） |
| `skills/ut/unit-test-executor/batch_results_schema.json` | tests entry 加 `gpu_id`(int\|null) |
| `skills/ut/unit-test-executor/scripts/classify_error.py` | 主路径退役：`execute_batch` 不再 import；保留文件不删（遗留 batch_test_runner 仍引用，删=破坏遗留；设计 §7「保留 legacy API 兜底」） |
| `tests/ut/unit/test_execute_batch_watchdog.py` | 更新：新 watchdog 模板（per-test wall、无 idle、setsid） |
| `tests/ut/unit/test_execute_batch_v5.py` | 更新：并发调度 mock、JUnit 解析、XML 缺失→timeout、0-card 降级 |
| `tests/ut/unit/test_execute_batch_schema_validation.py` | 更新：加 `gpu_id` 字段用例 |
| 新增 `tests/ut/unit/test_execute_batch_junit.py` | `_parse_junit` 单测：passed/failed/error/缺失 各路径 |

## 2. execute_batch.py 实现细节

### 2.1 新增模块级函数

- `_detect_free_gpus(*, profile, container, threshold_pct=50) -> list[int]`：容器内 nvidia-smi 拿 index/memory.used/memory.total + compute-apps pid；逐卡 usage% >= threshold → occupied；占用卡 pid 按 `ps -o pid,ppid,etime,cmd` cmd 分类：pytest/watchdog 特征 → 自己僵尸 → `_cleanup_zombie`；其他 → 别人 → 排除该卡；混合卡 → 排除。返回 free_ids。
- `_cleanup_zombie(pid, *, profile, container) -> bool`：SIGTERM → 等 5s → 仍活 SIGKILL -9 → 轮询 nvidia-smi 验证显存释放（3×2s）。EPERM → False。返回是否释放干净。
- `_parse_junit(xml_text, *, exit_code, node) -> dict`：xml.etree 解析；先 rstrip 尾 \n（§6 实测 daemon run 多 1 个尾 LF）。`<testcase>` 存在：无子节点→passed；`<failure>`→failed/error_type=assertion（message 含 OOM→oom）；`<error>`→error/error_type=collection；`time=`→duration_ms=round(float*1000)。XML 缺失/解析失败（watchdog SIGKILL 没 flush）→ status=retriable_error, error_type=timeout。返回 {status,error_type,error_message,duration_ms,exit_code}。

### 2.2 watchdog 模板重写（per-test）

删 idle/mtime 段（G2），只留 wall；加 `setsid` + 杀 PGID（G17）：
- `setsid` 起子进程组，`PID=$!`，PGID=$PID
- 后台跑 `cd /gpfs/.../vllm && python3 -m pytest <node> --junit-xml=<remote>/result_<node>.xml -v --tb=long -o junit_logging=out-err`
- wall 300s 到 → `kill -- -PGID` 杀整个进程组，exit 124，追加 `__WATCHDOG__: wall_exceeded`
- log 仍写 `pytest_<batch>_<node>.log`

### 2.3 execute_batch 主体改造

- `free_ids = _detect_free_gpus(...)`
- `N = len(free_ids)`；N==0 → D1 降级取 min-usage 一张串行（N=1）
- `ThreadPoolExecutor(max_workers=N)`，每 test_node 一 task：分配 gpu_id → `_wrap_with_docker_exec_b64(container, watchdog(pytest_one_node, gpu_id, junit_xml))` → `run_remote` 拿 exit_code → 二次 `run_remote` `cat junit_xml; echo __REMOTE_LOG_SIZE__$(stat...)` → `_parse_junit` → 收集 entry（含 gpu_id/duration_ms/exit_code）
- 每 task 独立 docker exec + 独立 watchdog，hang 只杀自己（G1/G8）

### 2.4 batch_results.json 字段

- `tests[].duration_ms` ← JUnit `<testcase time>`（真填）
- `tests[].exit_code` ← 该 docker exec exit code
- `tests[].gpu_id` ← 分配的卡 id（新字段）
- batch 级 `exit_code` ← 聚合（全 0 则 0，有非 0 取其一；下游只看 tests 级）
- `remote_log.raw_log_path` ← 按 schema 要求形如 `pytest_<batch_id>.log`；per-node log/xml 按约定文件名 `pytest_<batch_id>_<node>.{log,xml}` 写在同目录

## 3. 决策（已与用户确认 2026-06-24）

1. **per-node log/xml 路径入 schema**：tests entry 加 `log_path`+`xml_path`（均 nullable string）。schema 改动 = `gpu_id` + `log_path` + `xml_path` 三个新字段。
2. **0-card 降级本期实现**：N==0 → 取 `memory.used` 最低一张串行（N=1），OOM → `retriable_error` 重试（§6.2 已验证 OOM 走 `<error>`/`<failure>` message 含 OOM → error_type=oom）。
3. **遗留模块不删**：`batch_test_runner/gpu_scheduler/parallel_batch_executor/remote_test_runner` 保留，不动。`classify_error.py` 主路径退役但文件保留。

## 4. 验证（goal-driven）

- `pytest tests/ut/unit/test_execute_batch_junit.py` → `_parse_junit` 四路径全绿
- `pytest tests/ut/unit/test_execute_batch_watchdog.py` → 新 watchdog 模板（per-test wall、无 idle、setsid+杀PGID）
- `pytest tests/ut/unit/test_execute_batch_v5.py` → 并发调度 mock + 0-card 降级
- `pytest tests/ut/unit/test_execute_batch_schema_validation.py` → gpu_id/log_path/xml_path 字段
- 全量 `pytest tests/ut/unit/` 回归不破
- 容器实测（可选，需 daemon）：1 个真 pytest 用例跑通 JUnit 路径
