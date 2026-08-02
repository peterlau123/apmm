# Phase 2 Stage 1 统计分析报告

**生成时间**: 2026-07-16T22:35:01.524825
**运行目录**: runs\ut-20260716-221134
**Phase 1 总 batch 数**: 1

---

## 概览

- 总失败/Ignored 测试数: 8
- error_type 分类数: 1

### 优先级分布

- **P0 (立即处理)**: 1 个类型
- **P1 (高优先级)**: 0 个类型
- **P2 (中优先级)**: 0 个类型

---

## Error_type 分类详情

### timeout (P0)

- 影响测试数: 8
- 影响 batch 数: 1
- 影响 test_file 数: 2

**处理建议:**
检查测试复杂度，优化依赖下载流程，增加超时时间

**受影响的 batch:**

- `batch_20260716_223109`

**受影响的 test_file:**

- `tests/compile/distributed/test_async_tp.py`
- `tests/compile/distributed/test_fusion_all_reduce.py`

---

## 下一步

请 Operator 查看报告，决定重试策略。

可选决策方式:
1. **按 error_type 批量重试**（推荐）
2. 指定特定 batch 重试
3. 重试所有失败 batch（不推荐）

决策后请写入 `user_decision.json`，格式:
```json
{
  "decision_method": "retry_error_types",
  "retry_error_types": ["timeout"]
}
```