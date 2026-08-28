# content_format 断言失败事故（vLLM 上游测试期望与检测逻辑不一致）

**日期**: 2026-07-19
**严重等级**: P3（3 个 failed 测试，vLLM 上游测试数据驱动错误，非 vLLM 代码 bug，非环境问题）
**影响范围**: UT workflow Phase 1（run `ut-20260718-164107`），3 个 `test_chat_utils.py` 测试因测试期望值与实际检测不符而 failed
**修复状态**: 📐 待评估（根因已定位为上游测试期望过时，处理方案二选一：跳过 / patch 期望）

---

## 事故概述

Phase 1 的 91 个 failed 测试中，3 个 `tests/entrypoints/test_chat_utils.py` 的 `test_resolve_content_format_*` 测试断言失败，`error_type` 记为 `assertion`，是**真正的逻辑断言失败**（非环境/网络伪装）。

表面看是两个方向的断言矛盾：
- `hf_defined` 测试：期望 `'openai'`，得到 `'string'`（`assert 'string' == 'openai'`）
- `fallbacks` 测试：期望 `'string'`，得到 `'openai'`（`assert 'openai' == 'string'`）

深入 vLLM 检测逻辑和测试源码后确认：**3 个都是 vLLM 上游测试参数表的期望值与当前 `_detect_content_format` 检测逻辑（及模型实际 chat template）不一致**，不是 vLLM 代码 bug，也不是环境问题。

> **纠正**: [HF 模型缓存缺失事故](2026-07-19-hf-model-cache-missing-incident.md) 附录将这 3 个笼统记为"其他断言"，未分析根因。本文档确认其为上游测试数据驱动错误。

---

## 触发条件

- vLLM v0.13.0
- 测试：`tests/entrypoints/test_chat_utils.py` 的 `test_resolve_content_format_hf_defined` / `test_resolve_content_format_fallbacks`
- `resolve_chat_template_content_format(..., "auto", ...)` 走自动检测路径（`given_format="auto"`）

---

## 涉及测试清单（3 个）

| # | test_node | batch_id | 期望 | 实测 | 测试函数 |
|---|-----------|----------|------|------|---------|
| 1 | `test_chat_utils.py::test_resolve_content_format_hf_defined[hmellor/tiny-random-LlamaForCausalLM-openai]` | batch_20260719_020952 | openai | string | hf_defined |
| 2 | `test_chat_utils.py::test_resolve_content_format_fallbacks[Qwen/Qwen2-VL-2B-Instruct-string0]` | batch_20260719_021035 | string | openai | fallbacks |
| 3 | `test_chat_utils.py::test_resolve_content_format_fallbacks[Qwen/Qwen2-VL-2B-Instruct-string1]` | batch_20260719_021035 | string | openai | fallbacks |

---

## vLLM 检测逻辑（核心）

### `resolve_chat_template_content_format`（`vllm/entrypoints/chat_utils.py:608`）

```python
def resolve_chat_template_content_format(chat_template, tools, given_format, tokenizer, *, model_config):
    if given_format != "auto":
        return given_format
    detected_format = _resolve_chat_template_content_format(...)  # 自动检测
    return detected_format
```

### `_detect_content_format`（`vllm/entrypoints/chat_utils.py:427`）- 判定 string vs openai 的核心

```python
def _detect_content_format(chat_template: str, *, default) -> str:
    jinja_ast = _try_extract_ast(chat_template)
    if jinja_ast is None:
        return default
    try:
        next(_iter_nodes_assign_content_item(jinja_ast))  # AST 里有"遍历 content list"的节点?
    except StopIteration:
        return "string"    # 没有 -> string（template 只处理 content 为字符串）
    except Exception:
        return default
    else:
        return "openai"    # 有 -> openai（template 处理 content 为 list，即 OpenAI 多模态格式）
```

**判定规则**：解析 chat template 的 Jinja AST，若存在"把 `message['content']` 当 list 遍历/赋值"的节点（`_iter_nodes_assign_content_item`），判定 `'openai'`；否则 `'string'`。

---

## 证据链

### 证据 1：fallbacks 测试（2 个失败）- Qwen2-VL 期望 string，实际 openai

远端日志 `batch_20260719_021035/pytest_batch_20260719_021035.log`：

```
model = 'Qwen/Qwen2-VL-2B-Instruct', expected_format = 'string'
...
>   assert resolved_format == expected_format
E   AssertionError: assert 'openai' == 'string'
E     - string
E     + openai

# Qwen2-VL 的 chat template（含 list content 处理分支）:
{% if message['content'] is string %}{{ message['content'] }}<|im_end|>
{% else %}{% for content in message['content'] %}...  ← 遍历 list content

INFO 07-19 02:11:05 [chat_utils.py:590] Detected the chat template content format to be 'openai'.
```

Qwen2-VL 的 chat template 同时支持 string 和 list（OpenAI）两种 content 格式（有 `is string` 判断 + `for content in message['content']` 遍历分支），AST 含 content item 节点 -> `_detect_content_format` 判定 `'openai'`。

但 `fallbacks` 参数表（`tests/entrypoints/test_chat_utils.py:2291`）硬编码期望 `'string'`：
```python
@pytest.mark.parametrize(("model", "expected_format"), [
    ("Qwen/Qwen2-VL-2B-Instruct", "string"),   # ← 过时期望
    ("facebook/chameleon-7b", "string"),
    ...
])
```

### 证据 2：自相矛盾 - 同模型 Qwen2-VL 在 hf_defined 测试期望 openai 且 PASS

同一个 `Qwen/Qwen2-VL-2B-Instruct` 在 `hf_defined` 测试里期望 `'openai'`（`tests/entrypoints/test_chat_utils.py:2235`），且 **PASSED**：

```
# batch_20260719_020952.log
test_resolve_content_format_hf_defined[Qwen/Qwen2-VL-2B-Instruct-openai1] PASSED [100%]
```

```python
# hf_defined 参数表
(QWEN2VL_MODEL_ID, "openai"),   # ← Qwen2-VL 期望 openai，PASS
```

**这直接证明 `'openai'` 才是 Qwen2-VL 的正确 content format**，`fallbacks` 测试里的 `'string'` 期望是错的。

### 证据 3：hf_defined 测试（1 个失败）- LLAMA_GUARD 期望 openai，实际 string

`hmellor/tiny-random-LlamaForCausalLM` 在测试里被定义为 `LLAMA_GUARD_MODEL_ID`（`tests/entrypoints/test_chat_utils.py:58`），`hf_defined` 参数表期望 `'openai'`：

```python
LLAMA_GUARD_MODEL_ID = "hmellor/tiny-random-LlamaForCausalLM"
...
@pytest.mark.parametrize(("model", "expected_format"), [
    ...
    (LLAMA_GUARD_MODEL_ID, "openai"),   # ← 期望 openai
])
```

但该随机模型的 chat template 是纯 string 格式（无 list content 处理分支），`_detect_content_format` 正确判定 `'string'`：

```
>   assert resolved_format == expected_format
E   AssertionError: assert 'string' == 'openai'
E     - openai
E     + string

INFO 07-19 02:10:07 [chat_utils.py:590] Detected the chat template content format to be 'string'.
```

### 证据 4：两个测试函数代码几乎完全相同

`test_resolve_content_format_hf_defined`（line 2243）与 `test_resolve_content_format_fallbacks`（line 2303）函数体几乎逐行相同，唯一区别在 `get_tokenizer` 参数：

```python
# hf_defined (line 2270)
tokenizer = get_tokenizer(model, ...)                  # 用 model 名

# fallbacks (line 2325)
tokenizer = get_tokenizer(model_config.tokenizer, ...) # 用 model_config.tokenizer
```

两者都走 `resolve_chat_template_content_format(None, None, "auto", tokenizer, ...)` 自动检测，检测结果取决于 tokenizer 实际加载的 chat template。

---

## 根因分析

### 根因：vLLM 上游测试参数表期望值过时/错误

| 测试 | 模型 | 测试期望 | 检测结果 | 谁对 | 说明 |
|------|------|---------|---------|------|------|
| fallbacks | Qwen2-VL | string | openai | **检测对** | Qwen2-VL template 支持 list content，应判 openai。期望 string 是过时值 |
| hf_defined | LLAMA_GUARD (hmellor/tiny-random-Llama) | openai | string | **检测对** | 该随机模型 template 是纯 string，应判 string。期望 openai 与模型实际 template 不符 |

**核心结论**：`_detect_content_format` 的检测逻辑是正确的（依据 chat template AST 是否含 list content 处理），问题出在**测试参数表的期望值**：
- `fallbacks` 的 Qwen2-VL 期望 `'string'` 是旧版本检测逻辑下的值（可能早期 vLLM 未把 list content 支持判为 openai）
- `hf_defined` 的 LLAMA_GUARD 期望 `'openai'` 可能基于该模型早期 template 或 llama-guard 真实模型的 template，但 `hmellor/tiny-random-LlamaForCausalLM` 这个随机替身的 template 是纯 string

### 为什么不是 vLLM 代码 bug

1. 检测逻辑 `_detect_content_format` 行为一致且可解释：有 list content 节点 -> openai，无 -> string
2. 同模型 Qwen2-VL 在 hf_defined（期望 openai）PASS，在 fallbacks（期望 string）FAIL，**两个测试对同一模型给出矛盾期望**，必有一个是错的
3. Qwen2-VL template 客观上支持 list content（日志可见 `for content in message['content']` 分支），判 openai 符合事实

### 为什么不是环境问题

- 3 个测试 duration 都很短（586ms / 1392ms / 1462ms），无超时
- 模型能正常加载（走到 resolve chat template 步骤），无缓存缺失
- 错误是 `AssertionError`（纯断言），非 `RuntimeError`/`OSError`

---

## 处理建议

### 方案 A：跳过这 3 个测试（推荐）

在 `skills/ut/ut_common/filter_rules.yaml` 把这 3 个 test_node 标记为上游已知问题，跳过不跑。

**理由**：
- 这是 vLLM 上游测试数据错误，不是本仓库要修的代码
- 上游可能已修（更新期望）或在讨论，跟踪上游即可
- patch 上游测试有维护成本（vllm 升级时需重新 apply）

### 方案 B：patch 测试期望

直接改远端 `tests/entrypoints/test_chat_utils.py` 的参数表：
- `fallbacks`：`("Qwen/Qwen2-VL-2B-Instruct", "string")` -> `"openai"`（2 处）
- `hf_defined`：`(LLAMA_GUARD_MODEL_ID, "openai")` -> `"string"`

**风险**：vllm 升级时 patch 会冲突；且改的是替身模型（hmellor/tiny-random）的期望，若上游换真实 llama-guard 模型又得改回。

### 方案 C：跟踪上游

查 vLLM GitHub 这 3 个测试在 v0.13.0 之后的 commit/issue，看上游是否已修期望。若已修，升级 vllm 即解决；若未修，向上游报 issue。

> 归属：本事故对应待办项"failed 重新分类"的子项--这 3 个应标记为 `upstream_test_bug`，不重试（重试必失败，非环境问题）。

---

## 相关文件

| 文件 | 位置 | 说明 |
|------|------|------|
| test_load | `runs/ut-20260718-164107/test_load_4000_20260718_203512.json` | 3 个 failed 记录 |
| hf_defined 日志 | 远端 `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260719_020952/pytest_batch_20260719_020952.log` | LLAMA_GUARD 断言 + Qwen2-VL PASS |
| fallbacks 日志 | 远端 `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_20260719_021035/pytest_batch_20260719_021035.log` | Qwen2-VL 断言 + template AST |
| 测试源码 | 远端 `tests/entrypoints/test_chat_utils.py:2243`(hf_defined) / `:2303`(fallbacks) | 参数表期望值 |
| 检测逻辑 | 远端 `vllm/entrypoints/chat_utils.py:427`(`_detect_content_format`) / `:608`(`resolve_chat_template_content_format`) | string/openai 判定 |
| Phase 1 总结 | [reports/2026-07-19-phase1-500batch-run-summary.md](../reports/2026-07-19-phase1-500batch-run-summary.md) | §4 failed 分析 |
| 过滤规则 | `skills/ut/ut_common/filter_rules.yaml` | 方案 A 的落点 |

---

## 经验沉淀

1. **"真断言失败"也可能是测试本身的错**：3 个是货真价实的 `AssertionError`（非环境伪装），但根因是上游测试期望值过时，不是被测代码错。判断"测试对还是代码对"要看检测逻辑是否自洽、是否有矛盾证据。
2. **同模型跨测试矛盾期望 = 上游测试 bug 的强信号**：Qwen2-VL 在 hf_defined 期望 openai（PASS）、在 fallbacks 期望 string（FAIL），两个测试对同一模型给出相反期望，必有一个错。这类矛盾比单测失败更能定位"测试期望"问题。
3. **`_detect_content_format` 的判定依据是 AST 节点，不是文案**：判定 openai 的条件是 chat template Jinja AST 含"遍历 content list"的节点。排查 content_format 问题要看 template 是否有 `for content in message['content']` 分支，不能只看检测日志文案。
4. **随机替身模型的期望可能不准**：`hmellor/tiny-random-LlamaForCausalLM` 作为 LLAMA_GUARD 的替身，其 chat template 与真实 llama-guard 模型可能不同，测试期望 openai 是基于真实模型，替身模板是 string 导致断言失败。用替身模型的测试要对齐替身实际行为，不能套用真实模型期望。
5. **分类要区分"代码 bug / 测试 bug / 环境问题"**：这 3 个既非 vLLM 代码 bug（检测逻辑正确）也非环境问题（模型加载正常），是上游测试数据错误。三类处理方式不同：代码 bug 改代码，测试 bug 改测试或跳过，环境问题改环境。混为一谈会修错地方。
