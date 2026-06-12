# Multi-SWE-bench 评测进度

## 当前状态

**已暂停** - 2026-05-08

原因：50% 空 patch 问题未解决，准备先在简单数据集（AIME）上验证推理流程。
1. ✅ 数据集准备：Multi-SWE-bench 数据集已下载到 `/gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench/`
2. ✅ 推理脚本：`inference_multi_swe.py` 已创建
3. ✅ 部分推理：已生成 `predictions.jsonl`（492 条记录）
4. ✅ 诊断脚本：`diagnose_empty_patch.py` 已创建并运行

### 待完成
1. ⏳ 解决空 patch 问题
2. ⏳ 完成完整数据集推理（1632 实例）
3. ⏳ 运行评测（Docker 验证）

---

## 问题诊断

### 空 Patch 问题

**统计数据**：
- 总预测：492 条
- 空 patch：248 条（**50.4%**）
- 分布不均：某些 repo 空 patch 率高达 80-100%

**空 patch 率 Top 10 repos**：
| Repo | 空patch数 | 总数 | 空patch率 |
|------|-----------|------|-----------|
| yhirose/cpp-httplib | 1/1 | 100% |
| jqlang/jq | 15/17 | 88.2% |
| ponylang/ponyc | 65/82 | 79.3% |
| facebook/zstd | 22/29 | 75.9% |
| fmtlib/fmt | 28/41 | 68.3% |

### 诊断结果分析

**测试实例**：ripgrep#727, fmtlib/fmt#4310

| 实例 | 模型输出长度 | has_diff_format | extract_diff 结果 |
|------|--------------|------------------|-------------------|
| ripgrep#727 | 2113 chars | ✅ true | 1679 chars (有效) |
| fmtlib/fmt#4310 | 12724 chars | ✅ true | 1348 chars (有效) |

**关键发现**：
- 诊断时模型**能生成有效 patch**（包含 `diff --git` 格式）
- `extract_diff` 函数**工作正常**，能正确提取 patch
- 但 `predictions.jsonl` 中对应实例的 patch 是**空的**

**结论**：问题不在 `extract_diff` 函数，而是原始推理时模型没有生成有效输出。

### 可能原因

1. **Prompt 构造差异**
   - 原始脚本：body 截取前 500 字符，issue body 截取前 500 字符
   - 诊断脚本：body 截取前 1000 字符，issue body 截取前 300 字符

2. **API 端口差异**
   - 原始脚本默认：`http://localhost:8000/v1`
   - 实际服务：`http://localhost:9527/v1`
   - 如果原始推理连接失败，可能导致空输出

3. **vLLM 服务状态**
   - 原始推理时服务可能不稳定
   - 或者 max_tokens 设置导致输出截断

---

## 下一步行动

### 方案 A：重新推理（推荐）

1. 使用正确的 API 端口（9527）
2. 增加并发数提高效率
3. 确保每个请求都有有效响应

```bash
python inference_multi_swe.py \
    --api_base http://localhost:9527/v1 \
    --output_file predictions_new.jsonl \
    --max_tokens 4096
```

### 方案 B：修复推理脚本

1. 添加更完善的错误处理
2. 记录完整的模型输出用于调试
3. 添加并发支持提高效率

---

## 文件路径

| 文件 | 路径 |
|------|------|
| 推理脚本 | `/gpfs/gcsp/M2.7_verify/accuracy_test/Multi-SWE/inference_multi_swe.py` |
| 诊断脚本 | `/gpfs/gcsp/M2.7_verify/accuracy_test/Multi-SWE/diagnose_empty_patch.py` |
| 预测结果 | `/gpfs/gcsp/M2.7_verify/accuracy_test/Multi-SWE/predictions.jsonl` |
| 诊断结果 | `/gpfs/gcsp/M2.7_verify/accuracy_test/Multi-SWE/diagnose_results.json` |
| 数据集 | `/gpfs/gcsp/M2.7_verify/datasets/Multi-SWE-bench/` |
| 评测工具 | `/gpfs/gcsp/M2.7_verify/tools/multi-swe-bench/` |

---

## 时间记录

- 2026-05-08: 初始化评测环境，创建推理脚本
- 2026-05-08: 运行推理，发现 50% 空 patch 问题
- 2026-05-08: 创建诊断脚本，分析问题根因