# Executor 并行 GPU 调度 + JUnit 结果 — 设计

- 日期：2026-06-24
- 状态：设计已收敛，待实测两项后进实现
- 关联：`2026-06-23-pytest-timeout-redesign.md`（上一版 watchdog）、postmortem `ut-20260623-223710`（Type-B fabrication）

## 1. 背景：上一版方案的问题

`execute_batch.py` 现状（commit 19d3c2c 之前）：一个 batch 把 N 个 test_node 拼成**一个** pytest 命令、串行跑、外面包**一个** bash watchdog（idle 120s + wall 600s），结果靠 grep `PASSED`/`FAILED` 从人类输出反推。

grill 出的核心病灶：

| # | 问题 |
|---|---|
| G1 | watchdog 是 batch 级，一个用例 hang → SIGKILL 整批，其后的用例根本没启动（连坐） |
| G2 | idle 用 log mtime 启发式，GPU 负载正常慢测试（load model / inference 无输出）必然误触发 |
| G3 | 结果从 `-v` 输出 grep 反推，脆弱（版本变格式、parametrized `::...` 缩写、子串误匹配） |
| G4 | 被杀的用例没有自己的结果行 → 落 `error/other` 而非 `retriable_error/timeout` |
| G5 | `_classify_for_test` 找不到行就回退 whole-summary 分类，一个 OOM 污染所有未完成用例（传染） |
| G6 | `duration_ms: 0` 写死，无 per-test 时长，无法判断"真 hang 还是就是慢" |
| G7 | wall=600s 对 8 个 GPU 用例累计不够，无 hang 也撞 wall |
| G8 | 重试治标不治本：test6 hang → test7/8 被连坐标 error → 重试时 test6 还在 → 连坐跨 batch 传播 |
| G9 | grep summary 丢信息，failure-handler 读 lossy summary 而非真 log |
| G10 | per-test `exit_code` 字段从不填 |
| G11 | 本地 summary / 远程 log 割裂是 bastion 传输 artifact，逼出了 grep 分类层 |

## 2. 关键约束（来自需求澄清）

- **8 张 GPU 可用**，但可用数动态：`nvidia-smi` 检测，使用率 ≥50% 的卡视为占用，其余为 free。3 张占用 → 5 张可用 → 并行度 5。
- **用例已预搜集**，pytest 只执行，无 collection 成本（这使 executor-side 并行的 N× 启动成本归零）。
- **同一容器内并行**（多进程，非多容器）。
- 0 free GPU → 降级串行（取使用率最低的一张硬跑，接受可能 OOM → retriable 重试）。
- per-test wall 预算 v1 = **300s**（不连坐，可给宽）。
- 50% 阈值为 v1 粗筛。

## 3. 选型：executor-side N×docker exec（弃 xdist）

权衡 xdist vs executor-side 并行：

| | xdist (`-n N`) | executor-side N×docker exec |
|---|---|---|
| collection 成本 | 1× 共享 | N×（但本场景 collection=0，劣势消失） |
| CUDA 隔离 | fork 陷阱，要 spawn+plugin 钉卡 | 干净，每次 exec 自带 `CUDA_VISIBLE_DEVICES` env |
| 孤儿 worker | 主杀子不干净，要进程组 | 每测试独立进程+独立 watchdog，杀自己 PGID |
| 单 test hang 连坐 | worker 独立进程不连坐 ✓ | 完全隔离 ✓ |
| per-test watchdog | 难（xdist 内部不好给每 worker 独立 wall） | 天然，每 exec 包自己的 watchdog |
| per-test 结果 | 要 jsonl + 并发 append 处理 | 天然，每次 pytest 跑一个 node，JUnit 直接是该 test 结果 |
| infra 契合 | 加 plugin、改 conftest、spawn | 复用 `_wrap_with_docker_exec_b64`，executor 改并发起 N 次 |

**结论：executor-side N×docker exec。** collection=0 让 xdist 的唯一优势消失，CUDA 集成复杂度变成纯负担。

容器形态确认：**同一个容器**，由 executor（本地 Python）并发起 N 次 `docker exec -e CUDA_VISIBLE_DEVICES=<id> ... pytest <one_node>`。每次 exec 是独立进程、独立 env、独立 watchdog。不需要多容器。

## 4. 设计

### 4.1 batch 启动：动态 GPU 检测 + 僵尸清理

容器内 `nvidia-smi` 拿每卡占用进程 PID：

```
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits
nvidia-smi --query-compute-apps=pid,used_memory,gpu_uuid --format=csv,noheader
```

逐卡判定：
- 该卡上的占用进程，按 `ps -o pid,ppid,etime,cmd -p <PID>` 的 cmd 分类：
  - cmd 匹配 pytest/watchdog 特征 → **自己的**（潜在僵尸）
  - 其他 → **别人**
- **纯自己僵尸**（该卡只有自己的 pytest 进程）→ 清理：
  1. `SIGTERM`，等 5s
  2. 仍活 → `SIGKILL -9`
  3. 轮询 `nvidia-smi` 验证显存释放（3 次 × 2s 间隔，因 CUDA 显存释放有延迟）
  4. 释放干净 → 卡进 free 池；没释放 → 当占用排除
- **有别人进程**（纯别人 or 混合）→ 直接排除该卡（混合卡不敢只杀自己的，简单且安全）
- free_ids = 全部卡 − 排除卡

僵尸判定靠 **cmd 匹配 + etime**，不靠进程树：孤儿 worker 被 init 收养后 PPID=1，PPID 链追溯不到原 batch（`setsid` 起的进程父死后被 init 收养）。

清理权限坑：同 UID 能杀；不同 UID `kill` 返回 EPERM → 当排除该卡。

### 4.2 并行调度

- N = len(free_ids)
- N ≥ 1：并发起 N 个 docker exec，每个钉一张 free 卡、跑一个 test_node
- N = 0（全被别人占、非僵尸）：D1 — 取 memory.used 最低的一张，串行跑（N=1 退化）

并发用 Python `ThreadPoolExecutor` 或 asyncio（每个 task 一次 `run_remote`）。

### 4.3 单用例执行单元

每个 test_node 一次 docker exec：

```
docker exec -e CUDA_VISIBLE_DEVICES=<free_id> <container> bash -c "<watchdog 脚本>"
```

watchdog 脚本（per-test，删 idle，只留 wall）：
- `setsid` 起子进程组（杀 PGID 防孤儿，对应 G17）
- 后台跑 `python -m pytest <node> --junit-xml=<remote>/result_<node>.xml -v --tb=long --junit-logging=out-err`
- wall 300s 到 → `kill -- -PGID` 杀整个进程组，exit 124，追加 `__WATCHDOG__: wall_exceeded`

pytest 参数：
- `--junit-xml=<remote>/result_<node>.xml` —— 结构化结果
- `--tb=long` —— 完整 traceback 进 XML 的 `<failure>` message（G9）
- `--junit-logging=out-err` —— 捕获的 stdout/stderr 进 `<system-out>`/`<system-err>`（G9）
- log 仍写 `pytest_<batch>_<node>.log`（watchdog 重定向）

### 4.4 结果获取：路线 A（XML fetch 回本地解析）

每次 docker exec 跑完，第二次远程调用合并 fetch XML + log size（和现有"第二次远程调用"模式一致，不额外增加 RTT）：

```
cat <result_<node>.xml>; echo __REMOTE_LOG_SIZE__$(stat -c %s <pytest_<batch>_<node>.log>)
```

本地 Python `xml.etree` 解析 XML，填 batch_results.json：
- XML 里有该 node 的 `<testcase>` → 用其 status/time/failure
- **XML 缺失**（watchdog SIGKILL，pytest 没写）→ `retriable_error/timeout`（这是 JUnit "SIGKILL 不 flush" 在 per-test 模型下变成的精确信号，对应 G4）

status 映射：JUnit `<testcase>` 无子节点 → passed；`<failure>` → failed/assertion；`<error>` → error/collection（或按 message 细分 oom 等）；缺失 → retriable_error/timeout。

per-test `duration_ms` 取自 `<testcase time="...">`（G6）；per-test `exit_code` 取该 docker exec 的 exit code（G10）。

`classify_error.py` 整层塌掉——pytest 自己是 source of truth，不再 grep 反推（G3/G5/G9/G11）。

### 4.5 idle 启发式删除

G2 的误报机器直接删。per-test wall 300s 是唯一的超时维度。"test 卡住"的信号是 watchdog wall + JUnit 缺失，不是 log mtime。

## 5. 解决对照

| 病灶 | 解决 |
|---|---|
| G1 连坐 | 每用例独立进程，hang 只杀自己 |
| G2 idle 误报 | 删 idle/mtime |
| G3 grep 脆弱 | JUnit XML 结构化 |
| G4 被杀落 error/other | XML 缺失 → retriable_error/timeout |
| G5 传染 | 不再回退 whole-summary |
| G6 无 duration | `<testcase time>` |
| G7 wall 不够 | per-test 300s，不累计 |
| G8 重试连坐 | hang 隔离，不连坐 |
| G9 lossy summary | `--tb=long --junit-logging=out-err` |
| G10 per-test exit_code | 每 exec 的 exit code |
| G11 本地/远程割裂 | XML 小，fetch 回本地解析 |
| G17 孤儿占卡 | `setsid` + 杀 PGID + 僵尸清理 |

## 6. 待实测（实现前验证）

1. **bastion 最大可传输字节**：客户端 `daemon_req`（`tools/agent.py:615-637`）按 64KB chunk 累积到 `\n`，客户端无硬上限；上限取决于 daemon 端 stdout 捕获 + JSON 编码。实测：`head -c 100000 /dev/urandom | base64` 经 `agent.py run` 看拿回多少。XML 单用例几 KB，预期无问题，但要确认。
2. **pytest `--tb=long` 下 JUnit failure 是否截断**：取决于 pytest 版本。实测跑一个故意失败的用例，看 `<failure>` 是否全 traceback。若截断，需额外 fetch 原始 log。

## 7. 实现范围（下次会话）

- `execute_batch.py`：从单进程串行改为并发调度 N×docker exec + 僵尸清理 + JUnit 解析
- 新增 GPU 检测/清理模块（`_detect_free_gpus`、`_cleanup_zombie`）
- 新增 JUnit 解析（`_parse_junit`）
- watchdog 模板：删 idle、改 per-test wall 300s、加 `setsid` + 杀 PGID
- `classify_error.py`：退役（或保留 legacy API 兜底，主路径走 JUnit）
- `batch_results_schema.json`：per-test `duration_ms`/`exit_code` 真填，可能加 `gpu_id` 字段
- 测试：并发调度、僵尸清理、JUnit 解析、XML 缺失→timeout、0-card 降级

## 8. 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 并行机制 | executor-side N×docker exec | collection=0 让 xdist 优势消失，CUDA 隔离/钉卡/结果/infra 全干净 |
| 容器 | 同一容器多进程 | 多容器太重，复用现有 docker exec |
| 超时维度 | per-test wall 300s，删 idle | idle mtime 在 GPU 负载误报；不连坐后 per-test wall 是更细信号 |
| 结果格式 | JUnit XML，本地解析 | 结构化、自带 duration/traceback；SIGKILL 缺失 XML = timeout 精确信号 |
| `--tb` | long + `--junit-logging=out-err` | XML 自带完整 traceback + 捕获输出，减少 log fetch |
| 0 free GPU | 取 min-usage 串行硬跑 | 50% 是粗筛的语义延伸，OOM → retriable 重试 |
| 50% 阈值 | v1 粗筛 | 接受，后续可按 per-test 显存需求精细化 |
| 僵尸判定 | cmd 匹配 + etime | 孤儿 PPID=1，进程树追溯不到 |
| 混合卡 | 直接排除 | 不敢只杀自己进程，简单安全 |
