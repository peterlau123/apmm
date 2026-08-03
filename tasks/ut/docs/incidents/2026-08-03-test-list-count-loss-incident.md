# 2026-08-03 测试清单数量溯因报告（test_async_llm 22 条静默丢失）

## 概要

- **日期**：2026-08-03
- **影响范围**：`ut_test_list_full_20260718_174239.txt`（32933 条）及由此生成的 `ut-20260718-164107/manifest.json`
- **根因**：`hf_hub` / `hf_hub/hub` 目录混淆导致 TinyLlama 模型缓存结构损坏，`pytest --collect-only` 收集 `tests/v1/engine/test_async_llm.py` 时 `LocalEntryNotFoundError`，**整个文件 22 条用例静默丢失**
- **严重度**：中（清单残缺但流程继续，未中断执行）

## 现象

对比 06-24 与 07-18 两次收集的 test_list：

| 数据源 | 总条数 | ERROR | test_async_llm |
|---|---|---|---|
| 06-24 test_list（正确基线）| 32964 | 0 | 51 |
| 07-18 test_list（异常）| 32933 | **1** | **32**（丢 22）|
| 08-03 test_list（修复后）| 32955 | 0 | **51**（找回）|

丢失的 22 条均为 `tests/v1/engine/test_async_llm.py` 的用例：
`test_abort`、`test_abort_final_output`、`test_check_health`、`test_customize_loggers`、
`test_dp_rank_argument`、`test_finished_flag`、`test_load`、`test_mid_stream_cancellation`、
`test_multi_abort` 等（含 DELTA/FINAL_ONLY 参数化变体）。

## 根因分析

### 直接原因：collect ERROR 中断

07-18 收集日志末尾：

```
============ ERRORS ============
______ ERROR collecting tests/v1/engine/test_async_llm.py ______
tests/v1/engine/test_async_llm.py:30: in <module>
    TEXT_ENGINE_ARGS = AsyncEngineArgs(
vllm/engine/arg_utils.py:593: in __post_init__
    self.model = get_model_path(self.model, self.revision)
vllm/transformers_utils/repo_utils.py:202: in get_model_path
    return snapshot_download(repo_id=model, **common_kwargs)
huggingface_hub.errors.LocalEntryNotFoundError:
Cannot find an appropriate cached snapshot folder for the specified revision
on the local disk and outgoing traffic has been disabled.
!!!! Interrupted: 1 error during collection !!!!
```

`test_async_llm.py` **在模块顶层实例化** `TEXT_ENGINE_ARGS = AsyncEngineArgs(model="TinyLlama/TinyLlama-1.1B-Chat-v1.0")`
（L30-33），`__post_init__` 会调用 `snapshot_download()` 查找模型缓存。
`HF_HUB_OFFLINE=1` 下缓存缺失 → 抛异常 → pytest 收集该文件失败 → 22 条用例全部丢失。

### 深层原因：hf_hub / hf_hub/hub 目录混淆

TinyLlama 模型缓存结构损坏：

```
hf_hub/hub/models--TinyLlama--TinyLlama-1.1B-Chat-v1.0/   ← 标准缓存位置
    ├── refs/main → fe8a4ea1...   (版本指针，唯一存在)
    ├── ✗ snapshots/              (缺失 → LocalEntryNotFoundError)
    └── ✗ blobs/                  (缺失)

hf_hub/TinyLlama/TinyLlama-1.1B-Chat-v1.0/               ← 异常：模型被解压到 HF_HOME 根目录
    ├── config.json / model.safetensors / tokenizer.json / ...
```

huggingface_hub 的 `snapshot_download(local_files_only=True)` 只认
`hub/models--*/snapshots/<revision>/` 结构，**不认根目录的解压副本**。
模型文件实际在 `hf_hub/TinyLlama/`（错误位置），标准缓存只有 refs 指针
（无 snapshots/blobs）→ 离线查找必然失败。

### 时间线

| 时间 | 事件 |
|---|---|
| 06-24 | 收集正常（32964 条，TinyLlama 缓存完整）|
| 06-29 12:55 | TinyLlama 标准缓存被破坏（只剩 refs/）|
| 06-29 12:56 | 模型被解压到 `hf_hub/TinyLlama/`（非标准位置）|
| 07-02 | vLLM registry.py 更新（替换 Hermes 等模型）→ test_pipeline_parallel 参数化变化（29→20，**正常**）|
| 07-18 17:42 | 收集时 TinyLlama 缓存缺失 → 1 ERROR → 22 条静默丢失 → manifest 32933 条 |
| 08-03 | 修复 TinyLlama snapshots 符号链接 → 重新收集 32955 条（找回 22 条）|

## 修复

1. **补齐 TinyLlama 标准缓存结构**（符号链接解压副本到 snapshots/）：
   ```
   snapshots/fe8a4ea1ffedaf415f4da2f062534de366a451e6 -> hf_hub/TinyLlama/TinyLlama-1.1B-Chat-v1.0
   ```
   验证：`snapshot_download(local_files_only=True)` 成功返回。

2. **run_collect.sh 增加收集后校验**（commit e0b23b56）：
   - 检测 `ERROR collecting` > 0 → exit 1 拒绝残缺结果
   - 检测 `Interrupted: N error` → 失败
   - 解析 `tests collected` 数量，无法解析 → 失败
   - 与上次收集数量对比，波动 >5% → 告警人工确认

## 教训

1. **目录规范**：HF 模型必须放在标准缓存 `HF_HOME/hub/models--*/snapshots/` 结构下，
   不要在 `HF_HOME` 根目录直接解压模型副本（huggingface_hub 不认）。
2. **收集校验**：`pytest --collect-only` 的 ERROR 是**静默中断**（非零退出但 tee 输出完整），
   下游必须校验日志中的 ERROR/Interrupted 标记，否则残缺清单会一路流到 manifest。
3. **模块级副作用**：测试文件在模块顶层实例化引擎参数（触发模型查找）是脆弱设计，
   收集时任何缓存缺失都会导致整个文件丢失。
