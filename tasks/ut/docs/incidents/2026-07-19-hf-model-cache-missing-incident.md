# HF 模型缓存缺失事故（16 个 failed，3 个模型未离线缓存）

**日期**: 2026-07-19
**严重等级**: P2（16 个 failed 测试的根因，环境/数据问题非代码 bug）
**影响范围**: UT workflow Phase 1（run `ut-20260718-164107`），16 个测试因 HuggingFace 模型未缓存而失败
**修复状态**: ✅ 已修复（3 个模型已下载至容器 HF 缓存，待重跑验证）

---

## 事故概述

Phase 1 的 91 个 failed 测试中，16 个因 **HuggingFace 模型未在容器本地缓存**而失败。容器设了 `HF_HUB_OFFLINE=1` 禁止联网，本地缓存又缺模型，导致两类错误：
- **HF 网络失败**（9 个）：测试尝试联网下载被拒
- **HF 缓存缺失**（7 个）：`LocalEntryNotFoundError`，离线模式下找不到缓存快照

涉及 3 个模型，已分别通过 modelscope 和 HF mirror 下载修复。

> **纠正**: Phase 1 总结报告 §4.1 称"91 个 failed 多数是 HF 网络错误"，不准确。实际 HF 相关仅 16 个，真正的大头是 48 个 flashmla 数值断言失败（另见 §相关文件）。91 个 failed 精确分类见 §附录。

---

## 触发条件

- 容器：`v0.13.0_torch2.5.1_compile`（host `t_h20`）
- 环境变量：`HF_HUB_OFFLINE=1`（禁止联网下载）
- 测试加载模型时本地 HF 缓存（`~/.cache/huggingface` / `$HF_HOME`）无对应模型快照

---

## 涉及模型清单（16 个失败）

| 模型 repo | 网络失败 | 缓存缺失 | 合计 | 下载方式 |
|-----------|---------|---------|------|---------|
| **TinyLlama/TinyLlama-1.1B-Chat-v1.0** | 9 | 3 | **12** | HF mirror |
| **meta-llama/Meta-Llama-3-8B-Instruct** | 0 | 3 | **3** | modelscope |
| **hmellor/tiny-random-Gemma2ForCausalLM** | 0 | 1 | **1** | HF mirror |
| **合计** | **9** | **7** | **16** | |

---

## 证据链

### 证据 1：HF 网络失败（9 个，全为 TinyLlama）

错误信息（9 个一致）：
```
OSError: We couldn't connect to 'https://huggingface.co' to load the files,
and couldn't find them in the cached files.
Check your internet connection or see how to run the library in offline mode
at 'https://huggingface.co/docs/transformers/installation#offline-mode'.
```

分布：
- `tests/basic_correctness/test_basic_correctness.py`（8 个，参数化 `test_models[...-TinyLlama/TinyLlama-1.1B-Chat-v1.0]`）
- `tests/compile/distributed/test_async_tp.py`（1 个，`test_async_tp_pass_correctness[...-TinyLlama/TinyLlama-1.1B-Chat-v1.0]`）

### 证据 2：HF 缓存缺失（7 个，3 个模型）

错误信息（7 个一致）：
```
huggingface_hub.errors.LocalEntryNotFoundError: Cannot find an appropriate
cached snapshot folder for the specified revision on the local disk and
outgoing traffic has been disabled. To enable repo look-ups and downloads
online, pass 'local_files_only=False' as input.
```

分布：
- `meta-llama/Meta-Llama-3-8B-Instruct`（3 个）-- `tests/compile/distributed/test_fusions_e2e.py`
  - 注：这 3 个 test_node 带 `AttentionBackendEnum.TRITON_ATTN`，但**实际错误是缓存缺失，不是 triton 版本冲突**（triton 冲突见 [2026-07-19-triton-torch-version-conflict-incident.md](2026-07-19-triton-torch-version-conflict-incident.md)，是另外 19 个）
- `TinyLlama/TinyLlama-1.1B-Chat-v1.0`（3 个）-- `tests/compile/fullgraph/test_full_graph.py`
- `hmellor/tiny-random-Gemma2ForCausalLM`（1 个）-- `tests/entrypoints/llm/test_accuracy.py`

---

## 根因分析

### 直接原因

容器 `HF_HUB_OFFLINE=1` 禁止联网，但 3 个模型的本地 HF 缓存快照缺失。测试加载模型时：
- 部分测试代码路径先尝试联网（被 offline 拒绝）-> `OSError: couldn't connect`
- 部分测试代码路径查本地缓存（找不到）-> `LocalEntryNotFoundError`

### 为什么离线模式仍报"网络失败"

不同测试/库版本行为不一致：
- 有的走 `transformers` 老路径，`HF_HUB_OFFLINE=1` 下直接查缓存，缓存无 -> `LocalEntryNotFoundError`
- 有的走 `huggingface_hub` 路径，先尝试网络（忽略 offline 标志或标志未透传）-> `OSError`

两种错误的根因相同：**模型未缓存**。只要模型在本地缓存中，两类错误都会消失。

---

## 解决办法（已执行）

按模型选择下载源（规避 HF 直连的网络/授权问题）：

| 模型 | 下载方式 | 原因 |
|------|---------|------|
| meta-llama/Meta-Llama-3-8B-Instruct | **modelscope** | HF 需授权访问，modelscope 无需授权且网络可达 |
| TinyLlama/TinyLlama-1.1B-Chat-v1.0 | **HF mirror**（hf-mirror.com） | 小模型，mirror 可达，设 `HF_ENDPOINT=https://hf-mirror.com` 下载 |
| hmellor/tiny-random-Gemma2ForCausalLM | **HF mirror** | 同上 |

下载后模型放入容器 HF 缓存目录，`HF_HUB_OFFLINE=1` 下测试可从本地缓存加载。

### 下载操作要点

- **modelscope**：`modelscope download --model <repo> --local_dir <cache_path>`，需注意 modelscope 的模型名与 HF repo 可能不同（如 Meta-Llama-3 在 modelscope 可能是 `LLM-Research/Meta-Llama-3-8B-Instruct`），下载后需建立 HF 缓存期望的目录结构/符号链接
- **HF mirror**：`HF_ENDPOINT=https://hf-mirror.com huggingface-cli download <repo>`，或 `huggingface-cli download <repo> --endpoint https://hf-mirror.com`
- 下载完成后确认缓存结构符合 `~/.cache/huggingface/hub/models--<org>--<name>/snapshots/<rev>/` 规范，否则测试仍找不到

---

## 影响与待办

### 对 Phase 1 数据的影响

- 16 个 failed 实为 `dependency`（模型缓存缺失），非 `assertion`，应重分类
- 重跑这 16 个测试预期通过（模型已缓存），Phase 1 真实通过率将上升

### 对待办项文档的影响

[`reports/2026-07-19-phase1-pending-todos.md`](../reports/2026-07-19-phase1-pending-todos.md) 中：
- **P1-3（failed 重新分类）**：这 16 个重分类为 `dependency`（模型缓存缺失），与 19 个 triton 版本冲突的 `dependency` 同类但根因不同
- 模型下载已解决，无需在 filter_rules 排除这些测试

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| test_load | `runs/ut-20260718-164107/test_load_4000_20260718_203512.json` | 16 个 failed 记录（error_message 含 HF 错误） |
| Phase 1 总结 | `reports/2026-07-19-phase1-500batch-run-summary.md` | §4.1 误判来源（称"多数 HF 网络错误"） |
| 待办项 | `reports/2026-07-19-phase1-pending-todos.md` | P1-3 受影响 |
| triton incident | `incidents/2026-07-19-triton-torch-version-conflict-incident.md` | 另 19 个 failed 的根因（版本冲突） |
| 过滤规则 | `skills/ut/ut_common/filter_rules.yaml` | 本事故无需排除测试（模型已补齐） |

---

## 经验沉淀

1. **离线环境的模型缓存必须预置**：`HF_HUB_OFFLINE=1` 下，所有测试引用的模型必须提前下载到缓存。应建立"测试引用模型清单 -> 缓存预置检查"的预检流程。
2. **HF 直连不可达时按模型选源**：meta-llama 等需授权模型用 modelscope，普通小模型用 HF mirror。不要一刀切。
3. **error_message 外层文案会误导分类**：`OSError: couldn't connect` 看似网络问题，实则是"缓存无 + 离线禁下载"。分类应基于"模型是否在缓存"而非错误文案。
4. **test_node 带 TRITON_ATTN 不一定是 triton 错误**：test_fusions_e2e 的 3 个 test_node 带 `TRITON_ATTN`，但实际错误是 HF 缓存缺失。分类要看 error_message 内容，不能只看 test_node 参数。
5. **91 failed 不是"多数 HF 网络错误"**：精确分类后 HF 仅 16 个，真正大头是 48 个 flashmla 数值断言失败。报告抽样归因容易以偏概全，应全量分类。

---

## 附录：91 个 failed 精确分类

| 类别 | 数量 | 文件 | 根因 |
|------|------|------|------|
| triton 版本冲突 | 19 | test_fusion_attn.py | triton 3.5.0 与 torch 2.5.1 不兼容 |
| **HF 模型缓存缺失** | **16** | test_basic_correctness / test_async_tp / test_fusions_e2e / test_full_graph / test_accuracy | **模型未离线缓存（本事故）** |
| 数值断言失败 | 48 | test_flashmla.py | assert 0.98 < 0.0001（数值不对，另查） |
| server 启动失败 | 5 | test_async_tp / test_sequence_parallel / transcription | RuntimeError: Server failed to start |
| 其他断言 | 3 | test_chat_utils.py | assert 'string' == 'openai' |
| **合计** | **91** | | |
