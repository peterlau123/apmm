# vLLM server 启动超时/退出事故（compile 超时 + 模型缓存缺失）

**日期**: 2026-07-19
**严重等级**: P2（5 个 failed 测试的根因，环境/配置问题非代码 bug）
**影响范围**: UT workflow Phase 1（run `ut-20260718-164107`），5 个 distributed/server 测试因 vLLM server 启动失败而 failed
**修复状态**: 📐 待修复（根因已定位，分两子类分别处理）

---

## 事故概述

Phase 1 的 91 个 failed 测试中，5 个因 **vLLM `RemoteOpenAIServer` 启动失败**而 failed，`error_type` 被记为 `assertion`，实际为 `RuntimeError`。表面看是同一类"server 起不来"，但深入远端日志后发现是 **两种完全不同的根因**：

| 子类 | 数量 | 错误信息 | 真实根因 |
|------|------|---------|---------|
| **compile 超时** | 4 | `RuntimeError: Server failed to start in time.` | vLLM piecewise compile（inductor + cudagraph，mode:3）在 H20 上耗时 >240s，server 还没 ready 就被 240s 超时杀掉 |
| **模型缓存缺失** | 1 | `RuntimeError: Server exited unexpectedly.` | `openai/whisper-small` HF 离线缓存缺失，server 启动即崩溃退出 |

> **纠正**: [HF 模型缓存缺失事故](2026-07-19-hf-model-cache-missing-incident.md) 附录将这 5 个笼统记为"server 启动失败"，未拆根因。本文档拆分后：4 个是 compile 超时（归待办"提 timeout"），1 个是 whisper 缓存缺失（归待办"补模型缓存"，与 HF 缓存事故同类但模型不同）。

---

## 触发条件

- 容器：`v0.13.0_torch2.5.1_compile`（host `t_h20`）
- 测试框架：vLLM `RemoteOpenAIServer`（`tests/utils.py`），默认 `max_wait_seconds=240`
- 测试类型：distributed（async_tp / sequence_parallel）+ 1 个 ASR correctness

---

## 涉及测试清单（5 个）

| # | test_node | batch_id | duration | 错误 | 子类 |
|---|-----------|----------|----------|------|------|
| 1 | `test_async_tp.py::test_async_tp_pass_correctness[False-mp-True-2-RedHatAI/Llama-3.1-8B-Instruct-NVFP4]` | batch_20260718_204040 | 241509ms | Server failed to start in time | compile 超时 |
| 2 | `test_async_tp.py::test_async_tp_pass_correctness[True-mp-True-2-RedHatAI/Llama-3.1-8B-Instruct-NVFP4]` | batch_20260718_204040 | 241234ms | Server failed to start in time | compile 超时 |
| 3 | `test_sequence_parallel.py::test_tp_sp_generation[...-parallel_setup3-...]` | batch_20260719_012239 | 240725ms | Server failed to start in time | compile 超时 |
| 4 | `test_sequence_parallel.py::test_tp_sp_generation[...-parallel_setup11-...]` | batch_20260719_014101 | 240752ms | Server failed to start in time | compile 超时 |
| 5 | `test_transcription_api_correctness.py::test_wer_correctness[...-openai/whisper-small]` | batch_20260719_015742 | 21915ms | Server exited unexpectedly | 模型缓存缺失 |

---

## 证据链

### 证据 1：240s 超时的来源（compile 超时 4 个）

vLLM 测试框架 `RemoteOpenAIServer._wait_for_server` 默认 240s 等 server ready（`tests/utils.py:177`）：

```python
max_wait_seconds = max_wait_seconds or 240
self._wait_for_server(url=self.url_for("health"), timeout=max_wait_seconds)
# 240s 内 health check 不通 -> raise RuntimeError("Server failed to start in time.")
```

4 个 compile 超时的 duration 全部 ≈240-241s（240725 / 240752 / 241234 / 241509ms），与 240s 超时吻合，**不是** wall_timeout=300s 触发。

### 证据 2：async_tp NVFP4 的完整时间线（compile 卡住）

远端日志 `batch_20260718_204040/pytest_batch_20260718_204040.log`：

```
20:41:05  APIServer 启动 (vllm serve RedHatAI/Llama-3.1-8B-Instruct-NVFP4
          --load-format dummy --compilation_config {"mode": 3, ...}
          --tensor-parallel-size 2 --distributed-executor-backend mp)
20:41:05  WARNING: Using piecewise compilation with empty splitting_ops
          WARNING: Piecewise ... Setting cudagraph_mode to FULL.
20:41:14  EngineCore_DP0: Initializing V1 LLM engine (load_format=dummy, quantization=compressed-tensors)
20:41:23  parallel_state: world_size=2 rank=0/1 backend=nccl tcp://127.0.0.1:42981  ← NCCL 初始化成功
          ────── 3.5 分钟无日志（卡在 compile + cudagraph capture） ──────
20:44:57  multiproc_executor: Parent process exited, terminating worker    ← 父进程被杀
20:44:57  TCPStore teardown: TCP client failed to connect (Interrupted system call)  ← worker 清理报错
```

关键：
- **NCCL 在 20:41:23 就成功了**，不是分布式初始化问题
- **`--load-format dummy`** 排除了模型加载耗时
- 20:41:23 → 20:44:57（232s）无日志 = 卡在 **`compilation_config mode:3`（VLLM_COMPILE 最重）+ inductor backend + cudagraph capture**
- 20:44:57 父进程退出 = 240s 超时触发后 `_wait_for_server` raise，teardown 把 server 进程 SIGTERM

启动命令的 compile 配置（mode:3 = `CompilationMode.VLLM_COMPILE`）：
```
--compilation_config {"mode": 3, "compile_sizes": [2, 4, 8],
  "splitting_ops": [], "pass_config": {"fuse_gemm_comms": true}}
```
配套：`backend=inductor`、`cudagraph_mode=FULL`、`cudagraph_capture_sizes=[2,4,8,16]`。

### 证据 3：sequence_parallel 用小模型也超时（证明非模型大小问题）

test_sequence_parallel 的 2 个超时用的是 `hmellor/tiny-random-LlamaForCausalLM`（随机小模型），同样 240s 超时。证明 **compile 慢与模型大小无关，是 mode:3 compile + cudagraph 流程本身在 H20 上耗时过长**。

### 证据 4：transcription whisper-small 是缓存缺失（server exited）

远端日志 `batch_20260719_015742/pytest_batch_20260719_015742.log`：

```python
# tests/utils.py RemoteOpenAIServer.__init__
# download the model before starting the server to avoid timeout
is_local = os.path.isdir(model)
if not is_local:
    model_loader = get_model_loader(load_config)
    model_loader.download_model(model_config)   # ← whisper-small 未缓存，离线模式下失败
self._start_server(model, vllm_serve_args, env_dict)
max_wait_seconds = max_wait_seconds or 240
self._wait_for_server(...)                       # ← server 进程已崩溃，_poll() 发现退出
```

日志关键行：
```
huggingface_hub.errors.LocalEntryNotFoundError: Cannot find an appropriate
cached snapshot folder for the specified revision on the local disk and
outgoing traffic has been disabled.
```

`download_model` 失败后 server 启动即崩溃（exit code != 0），`_wait_for_server` 轮询时 `_poll()` 检测到进程已死，21s 即 raise `Server exited unexpectedly`（远短于 240s）。

> 注：whisper-small 不在 [HF 缓存缺失事故](2026-07-19-hf-model-cache-missing-incident.md) 的 16 个模型清单内（那 16 个是 TinyLlama / meta-llama / Gemma2），是独立遗漏。

---

## 根因分析

### 子类 A：compile 超时（4 个）- compile 太慢 + timeout 太短

**直接原因**：`compilation_config mode:3`（piecewise compile + inductor + FULL cudagraph）在 H20-3e 上首次编译 8B（NVFP4）/ 小模型耗时 >240s，server 来不及 ready。

**为什么 timeout 是 240s**：vLLM `RemoteOpenAIServer` 硬编码默认 `max_wait_seconds or 240`，测试调用时未传 `max_wait_seconds`，用默认值。wall_timeout=300s 是 UT workflow 外层超时，与此无关（240s 先触发）。

**为什么 compile 这么慢**：
- mode:3 是最重的 compile 模式（VLLM_COMPILE），需 inductor 编译 + cudagraph 捕获多个 batch size（[2,4,8]）
- `splitting_ops=[]`（空）导致 piecewise compile 退化为 FULL cudagraph，捕获开销大
- H20-3e 首次编译无 inductor cache，冷启动慢
- 与 [triton-torch 版本冲突事故](2026-07-19-triton-torch-version-conflict-incident.md) 相关但不完全相同：triton 冲突是 19 个 test_fusion_attn 直接报 `Cannot find triton`，而这里 inductor 能跑（triton 可用），只是慢

### 子类 B：模型缓存缺失（1 个）- whisper-small 未预置

**直接原因**：`openai/whisper-small` 未在容器 HF 缓存中预置，`HF_HUB_OFFLINE=1` 下 `download_model` 失败，server 启动即崩溃。

**为什么和 16 个 HF 缓存缺失分开记**：那 16 个表现为 `OSError`/`LocalEntryNotFoundError`（测试直接加载模型失败），这 1 个表现为 `Server exited unexpectedly`（经 `RemoteOpenAIServer` 包装，download 失败导致 server 崩溃）。根因同类（缓存缺失），但失败路径不同，处理上归到"补模型缓存"。

---

## 处理建议

### 子类 A：compile 超时（4 个）

| 方案 | 做法 | 评估 |
|------|------|------|
| **提 RemoteOpenAIServer timeout**（推荐） | 测试侧传 `max_wait_seconds=600` 或设环境变量 | 治标但有效，mode:3 compile 在 600s 内应能完成。需确认 vLLM 是否支持环境变量覆盖 |
| 提 wall_timeout | UT workflow 外层 300s→600s | **无效**，240s 内层超时先触发。需提的是内层 `max_wait_seconds` |
| 预热 inductor cache | 首次跑前预编译常用模型，落盘 inductor cache | 治本但复杂，需改部署流程 |
| 跳过 mode:3 测试 | filter_rules 排除 `compilation_config.mode=3` 的 distributed 测试 | 损失覆盖，仅作 fallback |

> 归属：本子类对应待办项"提 timeout"（原待办 #4 只提 wall_timeout，需补充提 RemoteOpenAIServer 内层 timeout）。

### 子类 B：模型缓存缺失（1 个）

补 `openai/whisper-small` 至容器 HF 缓存（参考 [HF 缓存缺失事故](2026-07-19-hf-model-cache-missing-incident.md) 的下载方式，whisper-small 无授权问题，用 HF mirror 即可）。

> 归属：本子类对应待办项"补模型缓存"（原待办 #9），在 HF 缓存事故的模型清单基础上补 whisper-small。

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| test_load | `runs/ut-20260718-164107/test_load_4000_20260718_203512.json` | 5 个 failed 记录 |
| async_tp 日志 | 远端 `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260718_204040/pytest_batch_20260718_204040.log` | compile 超时时间线（433-502 行） |
| transcription 日志 | 远端 `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260719_015742/pytest_batch_20260719_015742.log` | whisper 缓存缺失（956-964 行） |
| RemoteOpenAIServer | 远端 `tests/utils.py:177` | `max_wait_seconds or 240` 超时来源 |
| `_detect_content_format` | 远端 `vllm/entrypoints/chat_utils.py` | compile 流程（mode:3） |
| HF 缓存事故 | [2026-07-19-hf-model-cache-missing-incident.md](2026-07-19-hf-model-cache-missing-incident.md) | 16 个 HF 缓存缺失（不含 whisper） |
| triton 冲突事故 | [2026-07-19-triton-torch-version-conflict-incident.md](2026-07-19-triton-torch-version-conflict-incident.md) | 19 个 triton 版本冲突（compile 相关） |
| Phase 1 总结 | [reports/2026-07-19-phase1-500batch-run-summary.md](../reports/2026-07-19-phase1-500batch-run-summary.md) | §4 failed 分析 |

---

## 经验沉淀

1. **"server 启动失败"不是单一根因**：5 个同报 `RuntimeError` 的 failed，深挖后是 compile 超时（4）和缓存缺失（1）两个完全不同的问题。分类要看 duration（≈240s vs 远短于 240s）和远端日志，不能只看 error_message。
2. **240s 是内层超时，wall_timeout 是外层**：`RemoteOpenAIServer` 默认 240s，UT workflow wall_timeout=300s。提 timeout 要提对层——compile 超时提内层 `max_wait_seconds` 才有效，提外层 wall_timeout 无用。
3. **`--load-format dummy` 不等于快**：dummy 模式跳过权重加载，但 mode:3 compile + cudagraph capture 仍可能 >240s。compile 是冷启动主要开销，小模型也躲不掉。
4. **NCCL 成功不代表 server 能起**：async_tp 日志显示 NCCL 20:41:23 就 init 成功，但 server 仍卡在后续 compile。排查 server 启动要看完整时间线，不能见 NCCL OK 就排除分布式问题。
5. **`RemoteOpenAIServer` 会包装下载失败为 "Server exited"**：transcription 的 whisper 缓存缺失，表面是 `Server exited unexpectedly`（21s），实则是 `download_model` 失败。`RemoteOpenAIServer.__init__` 先下载再启动，download 失败会让 server 启动即崩。排查 server exited 要看 download 阶段日志。
6. **HF 缓存预置清单要含 ASR 模型**：whisper-small 不在原 16 个清单内，说明预置清单只覆盖了 LLM/VLM，漏了 ASR。应按测试引用全量模型（含 whisper）建预置检查清单。
