# 2026-08-08 排障溯因日志（run ut-20260807-110322 重跑期）

> 本文档记录 2026-08-08 处理的所有问题：症状、根因链、处置、验证。
> 防止遗忘——后续同类问题直接查这里。

---

## 1. Bifrost daemon 假活（今日最核心问题）

**症状**：execute_batch 提交任务后挂起（GPU 空闲但进程 CPU 0、无输出）；
daemon 心跳正常（独立线程）但任务 Pending 不消费；commands/ 有 10h 的 `.processing` 残留。

**排查链**：
1. daemon 单实例 ✅、心跳 timestamp 正常（MCP health 报 307s 是读 mtime 误判）
2. client submit 报成功（0.19ms）但任务文件不落盘 → 怀疑 BIFROST_CONFIG 缺失
   → **验证**：传 BIFROST_CONFIG 后任务 Completed（client 默认 settings 写错目录——**已兜底**：
   remote_executor `_BIFROST_CONFIG` 默认值 = 正确 settings）
3. daemon 3 次重启后恢复 → 但根因未明（"假活"）
4. **最终根因**：`gpu_monitor.rs` 的 `check_gpu_utilization` 用**同步
   `std::process::Command::output()` 执行 nvidia-smi**，在 async 执行路径
   （`process_task` → `schedule_next` → `is_gpu_idle`）**同步阻塞 tokio runtime
   worker** → 主循环饿死（心跳独立线程不受影响 → 假活）——3add3b5 修了文件 I/O
   的 4 处同步阻塞，**漏了 GPU 探测**。

**修复**（bifrost commit `cb7f4ab`，已推送）：
- `is_gpu_idle` 改 async + `tokio::task::spawn_blocking` 包装 nvidia-smi
- `get_next_idle_gpu` / `schedule_next` 同步改 async 链（3 文件 + 测试适配）
- 验证：cargo test 74 passed；部署后旧任务清理 + sh -c 任务 Completed

**教训**：async 代码里任何同步 `Command::output()`/文件 I/O 都可能饿死 runtime——
排查"假活"（心跳正常 + 不消费）先查 async 路径的同步阻塞点。

## 2. execute_batch backend 故障链（三条路）

| backend | 症状 | 根因 | 结论 |
|---|---|---|---|
| bifrost | 挂起 | daemon 假活（§1） | ✅ 修复 |
| agent | 直接失败 | **bastion 模式**（要密码）+ paramiko 未装 | ❌ 不适用（SSH 免密不兼容） |
| ssh（新增尝试） | 可用但被否 | — | ❌ 用户要求正式路径（bifrost），H20 架构上依赖 bifrost |

**沉淀**：`remote_executor.py` 新增 `_run_ssh`（paramiko 免密直连，含单测）——
保留备用但非正式路径；正式路径 = bifrost。

## 3. 节点过期（stale 591 个）

**症状**：error 333 + peft ~258 快速 abort（0.5s 收集 0）。
**根因**：test_load/manifest 节点是**旧代码生成**的——vllm 测试演进后旧节点
pytest `not found`（如 `test_peft_helper_error` 已从代码移除；当前文件仅 4 个测试）。
**不是缺依赖**（peft 0.19.1 已装）。
**处置**（用户决策）：本次不管——**下次 run 对这 591 个定向 --collect-only 校验**：
测试还在（改名/参数化变）→ 更新节点作为 pending 跑；确认删除 → 移除。
**防再犯**：生成 test_load 时加节点有效性校验。

## 4. cuda:1 320 坏卡节点（device-map）

**症状**：manifest pending 320 个 cuda:1 固化节点（GPU1 硬件故障 Xid31）。
**处置**：rerun 脚本加 `--device-map "cuda:1=cuda:0"`（运行层替换 + 回写原 node）
+ `--from-manifest-cuda1`（manifest 源）——**320 全部通过**（bifrost 修复后）。
**沉淀**：`test_rerun_device_map.py` 单测（替换/还原/往返）。

## 5. ignored 1,984 分类（重跑目标）

| 类别 | 数量 | 性质 |
|---|---|---|
| detokenize（模型类） | 902 | 大模型加载（CodeLlama-7b/Pixtral——模型已下载 hf-mirror）——分批小批量跑 |
| 其他 | 644 | timeout 连坐混合 |
| scheduler/attention/mla | 309 | 推理测试 |
| tool_choice（CPU） | 110 | 秒级（1.02s）——挂起连坐误杀 |
| multimodal/processing | 11 | 慢（大模型） |
| peft_helper | 8 | stale（§3） |

## 6. 汇报脚本问题（apmm_pending_progress.py）

| 问题 | 修复 |
|---|---|
| JSONDecodeError（读 test_load 撞上回写） | 读取重试 3 次 + 容错 |
| 进程匹配只认主跑 → 误判 DONE 静默 | alive 匹配全部相关进程（auto_run/retry/rerun/execute_batch） |
| 进度显示 100% 不变（ignored 算 done） | 改为真实通过率 + ignored 待救 |
| 当前测试状态 | 从 ut_logs 最新日志判断（加载模型/推理/卡住） |

## 7. 模型下载（hf-mirror）

- bigcode/tiny_starcoder_py（1.3G）+ codellama/CodeLlama-7b-hf（26G）+
  mistralai/Pixtral-12B-2409（24G）→ `pytorch_verify/2.5.1/ut/hf_hub/hub`
- 工具：`download_detokenize_models.sh`（脚本判断误报 ✗ 但实际下载成功——snapshots 完整为准）

## 8. 重跑脚本演进（rerun_ignored_remaining.py）

`--include-only`（定向）/ `--prefix`（batch 前缀防冲突）/ `--max-batch-size`（批大小，
32 平衡批间开销与排队）/ `--status`（ignored/error/failed）/ `--device-map` /
`--from-manifest-cuda1` / 外层超时 900→3600s + TimeoutExpired 容错 / ENV=bifrost+config。

---

## 关键教训汇总

1. **async 同步阻塞**是 daemon 假活主因（§1）——排查优先级最高
2. **BIFROST_CONFIG 必须传**（client 默认写错目录）——脚本 ENV 双保险
3. **节点 stale**（代码演进）≠ 测试失败——重跑前校验节点有效性
4. **device-map 回写用原 node**（运行替换 + 结果还原）
5. **进程匹配/DONE flag/JSON 竞态**——进度脚本三坑（§6）

## §9 2026-08-09 补充（分组重跑期）

1. **HF hang 真因（假活主因——不是时钟）**：新 run 缺 workflow.yaml → execute_batch 读不到 container_env（HF_HUB_OFFLINE）→ 测试离线 HF 下载 hang 占满并发 → "假活"观感。修复：复制 workflow.yaml + paths.workflow_yaml（✅ 单元 478 + 端到端验证）。**教训：新 run 必须带 workflow.yaml，H20 是物理机非 VM（时钟假设错误）**
2. **bifrost 假活残余**：tokio 执行层（worker）在 H20 环境偶发卡（任务 spawn 后不执行）——scan 忙轮询已修（7f7a509），执行层待专项（探针 cron 兜底）
3. **test_load 写坏**：update_test_load_two_phase 非原子 write_text → 中断写坏 JSON → 修复原子写（tmp+rename）
4. **update 路径坑**：update 工具读 paths.test_load（不是顶层 test_load_path）——新 run 需补 paths（workflow_yaml + test_load）
5. **_C 算子 JIT 补充**：编译+注册+单测全 OK，但与 vllm 共存 core dump（两个 so 注册 _C CUDA impl——加载机制冲突）——不可用（记录，torch 2.8 评估）
