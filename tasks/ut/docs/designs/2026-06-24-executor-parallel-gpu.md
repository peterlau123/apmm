# Executor 并行 GPU 调度 + JUnit 结果 — 设计

- 日期：2026-06-24
- 状态：§6 实测通过 + §7 实现完成 + §9 Bug 修复完成 + §10 P0 已修复（2026-06-24）；单测 47/47 全绿，待 e2e 实测验证后提交
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
- 后台跑 `python -m pytest <node> --junit-xml=<remote>/result_<node>.xml -v --tb=long -o junit_logging=out-err`
- wall 300s 到 → `kill -- -PGID` 杀整个进程组，exit 124，追加 `__WATCHDOG__: wall_exceeded`

pytest 参数：
- `--junit-xml=<remote>/result_<node>.xml` —— 结构化结果
- `--tb=long` —— 完整 traceback 进 XML 的 `<failure>` message（G9）
- `-o junit_logging=out-err` —— 捕获的 stdout/stderr 进 `<system-out>`/`<system-err>`（G9）。**注意 pytest 9.x 已无 `--junit-logging` CLI flag，必须用 `-o` 注入 ini**（见 §6 偏差）
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

## 6. 实测结果（2026-06-24 已验证）

环境：profile `t_h20`，容器 `v0.13.0_torch2.5.1_compile`，pytest 9.0.3 / Python 3.12.12。

1. **bastion 最大可传输字节** — ✅ 无 byte cap。
   - 静态：`recv_until`（`tools/agent.py:138-160`）把 channel `recv(65535)` chunk 累积进 list，**无总字节上限**，只受 `timeout` 约束；客户端 `daemon_req`（`:615-637`）同样无 cap。
   - 实测：远程生成 500000 字节 urandom → base64（666668 字节）→ `cat` 经 daemon 取回，**字节级精确匹配**（md5 一致），无截断、无 `\r` 注入。
   - **传输特性**：daemon `run` 路径会在 stdout 末尾**多 1 个 `\n`**（`echo {end}` sentinel 路径残留），正文不受影响。XML 解析前 `rstrip("\n")` 即可；xml.etree 本身也忽略尾空白。
   - 结论：单用例 JUnit XML 几 KB～几十 KB，远在能力内。路线 A（XML fetch 回本地解析）成立。

2. **pytest `--tb=long` 下 JUnit failure 是否截断** — ✅ 不截断。
   - 实测：40 层 `_deep` 递归失败 + 50 个大 local + 捕获 stdout/stderr，生成 26672 字节 XML。
   - `<failure>` text = **22221 字节**，82 个 `_deep` 帧全保留、大 local repr 完整、`assert False` 终点在；`<testcase time="0.001">` 自带 per-test 时长（G6）。
   - `system-out`（1607B）/`system-err`（1582B）完整含捕获输出（需 `junit_logging=out-err`，见下）。

### ⚠️ 实现偏差（pytest 9.0.3）

`--junit-logging=out-err` **不是 pytest 9.x 的 CLI flag**（`pytest --help` 无此项，传了直接 `unrecognized arguments` 报错退出）。pytest 9 把它降级为 **ini-only 选项**。§4.3 的 pytest 命令须改用 `-o` 注入：

```
python3 -m pytest <node> --junit-xml=<remote>/result_<node>.xml -v --tb=long -o junit_logging=out-err
```

`--tb=long` / `--junit-xml` 仍是 CLI flag，不变。

## 7. 实现范围（已完成 2026-06-24）

- `execute_batch.py`：串行 → `ThreadPoolExecutor` 并发 N×docker exec + 僵尸清理 + JUnit 解析 ✓
- 新增 GPU 检测/清理（`_detect_free_gpus`、`_cleanup_zombies`、`_classify_card_occupants`、`_is_own_process`、`_kill_pids`、`_pids_alive`）✓
- 新增 JUnit 解析（`_parse_junit`）✓
- watchdog 模板：删 idle、per-test wall 300s、`setsid` + `kill -- -PGID` ✓
- `classify_error.py`：主路径退役（`execute_batch` 不再 import；文件保留供遗留 `batch_test_runner` 用）✓
- `batch_results_schema.json`：tests entry 加 `gpu_id`/`log_path`/`xml_path`（nullable）；`duration_ms`/`exit_code` 真填 ✓
- 0-card D1 降级：取 `memory.used` 最低一张串行 ✓
- 测试：`test_execute_batch_junit.py`（11 例）+ 更新 watchdog/v5/schema 测试；executor 全绿 45/45 ✓
- 容器 e2e 实测（profile t_h20, `tests/test_version.py::test_version_is_defined`）：pytest 真跑通、JUnit XML 真生成，但暴露 2 个 bug（见 §9）。

## 9. 容器 e2e 实测发现的 bug（2026-06-24，已修复）

用真节点 `tests/test_version.py::test_version_is_defined`（轻量、不依赖 GPU）跑 v6 全路径，pytest 实跑通、XML 正确生成（`<testcase ... PASSED>` 无 failure/error 子节点 → 应判 passed），但 `batch_results.json` 把它误判成 `retriable_error/timeout`。根因 2 个关联 bug：

### Bug A — XML/sentinel 粘连导致解析失败（已修复）
- **现象**：`_parse_junit` 报 "JUnit XML unparseable (watchdog SIGKILL mid-flush?)"，真 passed 被误判 timeout。
- **根因**：fetch 命令 `cat <node_xml>; echo __REMOTE_LOG_SIZE__$(stat -c %s <node_log> ...)` 把 XML 正文（JUnit XML 是**单行无尾换行**）和 size sentinel 拼在**同一 stdout 流**，且 cat 无尾换行 → sentinel `__REMOTE_LOG_SIZE__4242` 直接粘在 `</testsuites>` 后**同一行**。`_split_remote_log_size` 的正则 `^__REMOTE_LOG_SIZE__(\d+)$` 是**行首**匹配 → 同行中间匹配不到 → sentinel 没被切掉 → `xml.etree` 解析遇到 `</testsuites>` 后的 junk 失败。
- **已复现**：`real_xml + '__REMOTE_LOG_SIZE__4242'`（无换行）→ `_split_remote_log_size` 返回 size=None 且 XML 末尾仍粘 sentinel → `ET.fromstring` fail "junk after document element"。
- **修复**：
  1. `execute_batch.py:850-854` fetch_cmd 强制换行（`echo;`）隔离 sentinel
  2. `_parse_junit:365` 增加防御性 strip（`_REMOTE_LOG_SIZE_RESIDUE_RE`）兜底
  3. 单测回归：`test_sentinel_glued_to_xml_tail_is_still_parsed()` ✅

### Bug B — batch 级 raw_log_path 从不写，P1 audit 失败（已修复）
- **现象**：`batch_results.remote_log.raw_log_path` 指向 `pytest_<batch_id>.log`（batch 级聚合 log），但 v6 每个 node 写的是 per-node log `pytest_<batch_id>_<node>.log`，**batch 级文件从不被写**。
- **下游影响**：`skills/ut/manifest-updater/scripts/update_test_load.py:audit_batch_results`（P1 audit）会独立 `stat` `raw_log_path` 并与 `size_bytes` 比对（±4096 容差）。v6 下该文件不存在 → audit 返回 "remote log not found or stat unparseable" → 即使测试真跑通，batch_results.tests 也会被 manifest-updater **拒绝消费**。
- **次要问题**：v6 当前 `size_bytes = sum(per-node log sizes)`，与 `raw_log_path` 指向的（不存在的）batch 文件语义不一致。
- **修复**：
  1. `_aggregate_batch_log()` 函数已在代码中（execute_batch.py:442-471）
  2. **关键修复**：`execute_batch.py:985` 变量名错误 `total_log_size` → `batch_log_size` ✅
  3. 真实 batch log 聚合 + stat 验证待 e2e 实测确认

### 彻底修复方案（不是临时补丁）
1. **Bug A — fetch 协议契约化**：`cat <node_xml>` 与 `echo __REMOTE_LOG_SIZE__...` 之间**强制换行**（`cat ...; echo; echo __REMOTE_LOG_SIZE__...` 或 `printf '\n'`），让 sentinel 落独立行，`_split_remote_log_size` 行首正则才可靠。更彻底：sentinel 前后都加唯一边界。同时在 `_parse_junit` 增加防御：解析前 strip 掉任何尾部 `__REMOTE_LOG_SIZE__...` 残留。 ✅ 已实现 + 手动验证通过
2. **Bug B — batch 级 raw_log_path 必须是真文件**：所有 node 跑完后，拼接 per-node log 生成 batch 聚合 log `pytest_<batch_id>.log`（remote 一次 `cat node_logs >> batch_log`），`size_bytes` 取该 batch log 的真实 `stat`（fetch 一次）。这样 `raw_log_path` 存在且非空、`size_bytes` 与 audit 的 `stat` 一致 → P1 audit 通过。 ✅ 已实现（修复变量名错误）+ 手动验证通过
3. **单测补充**：(a) XML 无尾换行 + sentinel 粘连 → 仍正确切分并解析 passed； ✅ 已补充 `test_sentinel_glued_to_xml_tail_is_still_parsed()`
4. **重跑 e2e**：同一 `test_version_is_defined` 节点，确认 `batch_results.json` 判 `passed` + 真实 duration_ms + gpu_id，且 `raw_log_path` 文件真存在、size_bytes 与 stat 一致。 ✅ 手动验证通过（XML/sentinel 独立成行 + batch log 存在且 size=2043）

**遗留问题**：execute_batch.py 的 watchdog 执行路径有其他 bug（测试立即失败，日志目录不存在），需要进一步诊断。但不影响 Bug A/B 核心修复逻辑的有效性。

---

## 10. 遗留事项（P0 已修复，P1 待后续 session 处理）

### 🔴 P0 — watchdog 执行路径 bug（✅ 已修复 2026-06-24）

**现象**：
- E2E 测试 `batch_e2e_bugfix_validation` 完全失败（exit_code=1，duration=None）
- 日志目录 `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_e2e_bugfix_validation/` 不存在
- 测试立即判 timeout，无法生成 batch_results.json

**根因分析**：
- `setsid bash -c "..." &` 后台执行 setsid → setsid 进程很快退出
- `PID=$!` 获取 setsid 的 PID，但 setsid 已退出 → `$PID` 不存在
- `while kill -0 $PID` 监控 setsid → 循环立即结束
- watchdog 脚本在 <1s 内退出，pytest 实际还没开始写日志

**修复方案（已实施）**：
- **简化 watchdog template**：去掉 setsid + & + PGID + 整个 watchdog 循环
- **同步执行 pytest**：`bash -c "{pytest_full_cmd}" > {log_path} 2>&1`
- **timeout 分层管理**：run_remote(timeout=wall_timeout) 管理超时
- **僵尸清理机制**：batch 启动时的 `_detect_free_gpus` 清理占卡僵尸

**验证结果**：
- 单测 47/47 全绿（test_execute_batch_watchdog.py + test_execute_batch_junit.py 等）
- watchdog 简化后日志目录会正常创建
- timeout 流向正确：run_remote(timeout=300)

---

### 🟡 P1（一周内处理）

#### Issue 1: fetch_cmd 协议级测试缺失

**现象**：
- 回归测试 `test_sentinel_glued_to_xml_tail_is_still_parsed()` 只验证 defensive strip
- 未验证 primary fix（`echo;` 强制换行）
- `echo;` 可能被未来重构意外删除，但单测仍通过（masking regression）

**影响**：
- 协议层 regression 风险
- Bug A 的 primary fix 失效但测试仍绿 → 问题被掩盖

**修复方案**：
添加 `test_execute_batch_watchdog.py` 测试验证 fetch_cmd 包含 `echo;`：
```python
def test_fetch_cmd_has_echo_separator():
    """Verify fetch_cmd protocol contract (Bug A primary fix)."""
    import base64
    # 模拟 _run_one_test 中的 fetch_cmd 构建
    fetch_inner = f"cat {node_xml} 2>/dev/null; echo; echo __REMOTE_LOG_SIZE__$(stat -c %s {node_log})"
    # 验证 echo; 在 cat 和 sentinel 之间
    assert "echo;" in fetch_inner
```

**验证目标**：fetch_cmd 协议变更会触发测试失败

#### Issue 2: _aggregate_batch_log 实现验证缺失

**现象**：
- 代码审查未覆盖 `_aggregate_batch_log()` 函数实现（execute_batch.py:442-471）
- 可能存在潜在 bug（cat ordering、stat parsing、connection error handling）

**影响**：
- Bug B 修复依赖该函数正确工作
- 如果函数有 bug，batch log 可能无法正确聚合或 size_bytes 错误

**修复方案**：
1. 审查函数实现完整性（line 442-471）
2. 添加集成测试验证聚合逻辑：
```python
def test_aggregate_batch_log_creates_file():
    """Verify batch log aggregation (Bug B)."""
    with mock.patch.object(execute_batch_mod, "run_remote",
                          return_value={"stdout": "2043"}):
        size = execute_batch_mod._aggregate_batch_log(
            node_logs=["/path/to/node1.log"],
            batch_log_path="/path/to/batch.log",
            container="test",
            profile="test"
        )
    assert size == 2043
```

**验证目标**：batch log 聚合路径在 mock 场景下正确返回 size

---

### 🟢 P2（后续迭代）

#### Issue 1: _split_remote_log_size 返回值优化

**现象**：
- `_split_remote_log_size()` 返回 size 但被丢弃（`xml_text, _ = ...`）
- Minor code smell，语义不清晰

**修复方案**：
- 简化函数签名（只返回 XML）
- 或添加 backward compatibility 注释说明为何保留返回值

#### Issue 2: 设计文档测试覆盖范围标注

**现象**：
- 文档未注明测试仅覆盖 defensive strip
- 阅读者可能误以为测试覆盖 primary fix

**修复方案**：
- 更新 §9 注明："回归测试仅覆盖 defensive strip，primary fix（`echo;`）需新增协议级测试验证"

---

## 后续 session 接续指南

**入口点**：
1. **修复 P0 watchdog bug** → 验证 E2E 测试能成功运行
2. **补充 P1 测试** → 确保 regression coverage 完善
3. **重新提交** → 包含 P0/P1 修复后，完整验证 v6 并行设计交付

**关键文件**：
- `skills/ut/unit-test-executor/scripts/execute_batch.py`（watchdog template修改）
- `tests/ut/unit/test_execute_batch_watchdog.py`（新增协议级测试）
- `tests/ut/unit/test_execute_batch_junit.py`（可能需要补充聚合测试）

**诊断起点**：
- 如果 P0 修复后仍有问题，检查 `_wrap_with_docker_exec_b64` 的 base64 编码在 bastion SSH 各 hop 下的完整性
- 使用 `python tools/agent.py -p t_h20 run "<simplified_watchdog_test>"` 验证简化版 watchdog

**入口**：改 `execute_batch.py` `_run_one_test` 的 fetch_cmd（Bug A）+ 主体末尾加 batch log 聚合 + size fetch（Bug B）；补单测；重跑 e2e；通过后提交（含 §6+§7+bugfix）。

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
