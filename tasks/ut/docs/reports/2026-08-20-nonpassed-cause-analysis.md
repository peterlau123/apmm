# 非 passed 用例根因盘点报告（2026-08-20）

> 数据源：`tasks/ut/dataset/manifest.json`（2026-08-20 更新，以 `runs/ut-20260808-manifest-remaining` 为准）
> 全集：32,955 条（08-03 正确清单）｜ 状态口径：latest run test_load > 6 月 run > 快照

---

## 1. 概览

| 状态 | 数量 | 占比 | 说明 |
|---|---|---|---|
| ✅ passed | 26,875 | 81.5% | — |
| ❌ failed | 3,095 | 9.4% | 断言/运行时失败 |
| ⚠️ error | 470 | 1.4% | 用例级错误（多为环境/模型类） |
| ⏭️ ignored | 888 | 2.7% | timeout 连坐 / pytest skipped |
| 🔁 retriable_error | 3 | 0.0% | executor 崩溃（可重试） |
| ⏳ pending | 1,624 | 4.9% | **待重跑池**（用户拍板 pending 化，2026-08-08） |

**非 passed（含终态失败）合计：4,456**（failed + error + retriable + ignored）
**待重跑 pending：1,624**（另计，非失败）

---

## 2. failed（3,095）根因分析

### 2.1 按失败类别（_classify）
| 类别 | 数量 | 说明 |
|---|---|---|
| _C算子 | 872 | marlin/moe/gptq/awq 算子缺失（NotImplementedError） |
| other | 719 | 其他（pydantic/断言/杂项） |
| inductor | 446 | torch.compile/dynamo 相关 |
| FP8 | 401 | float8 内核在 H20 上的兼容问题 |
| models | 351 | HF 模型缓存缺失/无权限 |
| flash/mla | 212 | flash_attn/flashmla 内核问题 |
| torch API | 72 | torch 无该属性（版本差异） |
| cutlass | 22 | cutlass/machete 内核缺失 |

### 2.2 按根因簇（error_message 聚类）
| 根因簇 | 数量 | 解读 |
|---|---|---|
| NotImplementedError | 777 | 缺算子实现（_C 扩展缺失/未注册） |
| RuntimeError 其他 | 533 | 运行时错误（含 engine 内核崩溃） |
| 导入错误 | 521 | 扩展/模块加载失败（ImportError/undefined symbol） |
| HF 模型缓存缺失/无权限 | 323 | LocalEntryNotFound/404/403（离线缺模型） |
| pydantic ValidationError | 196 | 参数校验失败（测试参数不合法） |
| Python 异常 | 192 | Attribute/Type/Key/ValueError 等 |
| 断言失败 | 161 | 数值/逻辑断言不匹配 |
| engine 初始化失败 | 120 | Engine core initialization failed |
| 网络/连接失败 | 84 | 连接错误/重试耗尽 |

### 2.3 文件热点 TOP
`test_marlin_gemm.py` 605 ｜ `test_block_fp8.py` 391 ｜ `test_moe.py` 316 ｜ `test_batched_moe.py` 288 ｜ `test_initialization.py` 158 ｜ `test_grouped_topk.py` 96 ｜ `test_fusion.py` 76 ｜ `test_flash_attn.py` 68

---

## 3. error（470）根因分析

| 根因簇 | 数量 | 解读 |
|---|---|---|
| HF 模型缓存缺失/无权限 | 210 | 离线缺模型/无下载权限 |
| 网络/连接失败 | 118 | 连接中断/超时 |
| RuntimeError 其他 | 88 | 运行时错误 |
| engine 初始化失败 | 29 | server 启动失败 |
| 超时 | 14 | 执行超时 |

文件热点：`test_full_cudagraph.py` 64 ｜ `test_vision.py` 35 ｜ `test_chat.py` 34 ｜ `test_metrics.py` 23 ｜ `test_llama4_pythonic_tool_parser.py` 21

**特征**：error 类以**环境问题为主**（模型缺失 210 + 网络 118 = 328，占 70%）

---

## 4. ignored（888）根因分析

| 根因簇 | 数量 | 解读 |
|---|---|---|
| JUnit XML 输出问题 | 490 | timeout 连坐标记（watchdog/JUnit 超时） |
| skipped | 241 | pytest 主动跳过（非失败） |
| 其他空 | 120 | 无 error_message（collect 级 ignored） |
| 超时 | 32 | 显式超时 |
| filtered | 5 | 过滤 |

文件热点：`test_attention.py` 194 ｜ `test_cache.py` 192 ｜ `test_prefix_prefill.py` 96 ｜ `test_chat_utils.py` 41

**特征**：ignored 中 490（55%）是 timeout 连坐（JUnit XML 标记），241（27%）是 pytest skipped（真非失败）

---

## 5. retriable_error（3）

全部为 `executor task crashed`（pytest_full_cmd 执行器崩溃）：`test_min_tokens.py` 2 + `test_plot_filters.py` 1 —— **可重试**

---

## 6. pending 待重跑池（1,624）

| 原状态构成 | 数量 |
|---|---|
| 原 ignored（timeout 连坐，JUnit XML） | 1,265 |
| 原 models（HF 模型类） | 257 |
| 原 other | 102 |

**处置建议**：用 `rerun_selective.py --run-dir runs/ut-20260808-pending2 --status pending` 重跑（跳过模型类/兼容 SKIP 的过滤见该脚本 `--category`）

---

## 7. 汇总与建议

### 7.1 可重跑性汇总（4,456 终态失败）
| 处置方向 | 数量 | 构成 |
|---|---|---|
| 兼容性 SKIP（记录不重跑） | ~2,037 | _C算子 872 + inductor 446 + FP8 401 + flash/mla 212 + cutlass 22 + torch API 72 + inductor(ignored) 37 |
| 环境类（需模型/网络就位） | ~674 | failed models 351 + error models 323 |
| 可重跑（真失败/超时） | ~1,745 | NotImplementedError 777 中的非 SKIP 部分 + RuntimeError + 断言 + timeout 等 |

### 7.2 主要根因链
1. **_C 算子缺失**（1,000+）：marlin/moe/FP8 内核未注册或 torch 2.5.1 与 vLLM 0.13.0 编译不匹配——已知问题（记录不硬修，见兼容性报告）
2. **HF 模型离线缺失**（~900）：detokenize/vision/llama4 等模型未入缓存——模型下载后可救
3. **timeout 连坐**（1,755 = ignored 490 + pending 1,265 原 ignored）：watchdog/JUnit 超时标记，重跑可救
4. **导入/编译错误**（~521）：扩展加载失败（部分为 _C 相关问题）

*报告生成: 2026-08-20 ｜ 分析脚本: /tmp/analyze_rootcause.py*
