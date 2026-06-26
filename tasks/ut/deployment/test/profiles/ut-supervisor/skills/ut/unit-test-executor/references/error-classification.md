# 错误分类框架

> 本文档从 SKILL.md 移出，详细描述错误分类与处理策略

## 问题分类框架

| 类别 | 说明 | 示例 |
|------|------|------|
| **C-代码Bug** | vLLM 源码缺陷 | 类型签名错误、逻辑错误 |
| **E-环境问题** | 测试环境限制 | HF 离线、磁盘配额、GPU 内存 |
| **D-依赖缺失** | Python 包缺失 | mteb, multiprocess, grpc |
| **P-平台兼容** | PyTorch API 缺失 | fp32_precision, wrap_triton |
| **M-模型缺失** | HuggingFace 模型未下载 | Llama, Snowflake 等 |
| **S-跳过问题** | 合理跳过的测试 | 平台不支持、功能未启用 |

---

## 按类别处理策略

| 类别 | 优先级 | 处理动作 | 是否汇报 |
|------|:------:|----------|:--------:|
| **C-代码Bug** | P1 | 分析根因 → 提出修复 → 执行修复 → 验证 | 否（自主处理） |
| **E-环境问题** | P0 | 记录 manifest → 汇报 Supervisor → 等待响应 | **是** |
| **D-依赖缺失** | P1 | 尝试 `pip install` → 成功继续 / 失败汇报 | 失败时汇报 |
| **P-平台兼容** | P2 | 标记 `skip` → 记录原因 → 继续 | 否 |
| **M-模型缺失** | P1 | 检查 HF 缓存 → 无缓存则汇报 Supervisor | 缺失时汇报 |
| **S-跳过问题** | P3 | 记录 skip 原因 → 继续 | 否 |

---

## 错误处理决策树

```
测试失败/ERROR:
├── 解析错误信息
├── 分类错误类别 (C/E/D/P/M/S)
│
├── C-代码Bug:
│   ├── 分析根因 (read_file 源码)
│   ├── 提出修复方案
│   ├── patch 修复代码
│   ├── 重新运行测试验证
│   └── 更新 manifest.json: {"status": "fixed", "fix_commit": "..."}
│
├── E-环境问题:
│   ├── 记录完整错误到 manifest.json
│   ├── send_message.py 汇报 Supervisor
│   ├── 等待 Supervisor 响应 (timeout: 120s)
│   │   ├── 响应 "resolved" → 重试测试
│   │   ├── 响应 "skip" → 标记跳过
│   │   ├── 超时 → 执行 fallback (跳过并记录)
│   └── 更新 supervisor_response 字段
│
├── D-依赖缺失:
│   ├── 尝试 pip install <package>
│   │   ├── 成功 → 重试测试
│   │   ├── 失败 → 汇报 Supervisor (dependency_request)
│   └── 记录到 manifest.json
│
├── P-平台兼容:
│   ├── 标记 status: "skipped"
│   ├── 记录 skip_reason: "platform_incompatible"
│   └── 继续下一测试
│
├── M-模型缺失:
│   ├── 检查 ~/.cache/huggingface/
│   │   ├── 有缓存 → 使用本地模型
│   │   ├── 无缓存 → 汇报 Supervisor (model_request)
│   └── 记录到 manifest.json
│
└── S-跳过问题:
    ├── 记录 skip_reason
    └── 继续
```

---

## Manifest.json 错误记录格式

### E-环境问题记录示例

```json
{
  "test_node": "tests/distributed/test_pipeline_parallel.py::test_basic",
  "status": "failed",
  "error_category": "E",
  "error_type": "distributed_gpu_unavailable",
  "error_message": "ValueError: Error initializing distributed - only 1 GPU available (requires >= 2)",
  "available_gpus": 1,
  "required_gpus": 2,
  "reported_to_supervisor": true,
  "reported_at": "2026-06-08T14:00:00+08:00",
  "supervisor_response": "pending"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `error_category` | string | 问题分类（C/E/D/P/M/S） |
| `error_type` | string | 具体错误类型 |
| `error_message` | string | 完整错误提示 |
| `reported_to_supervisor` | bool | 是否已汇报 |
| `supervisor_response` | string | Supervisor 响应状态（pending/resolved/skip） |

---

## Fallback策略

当Supervisor响应超时时自主处理：

| 问题 | 超时 | Fallback动作 |
|------|------|--------------|
| bastion_disconnect | 60s | 暂停执行，每30s重试ping |
| gpu_occupied | 60s | 降级为1 worker |
| dependency_request | 120s | 跳过依赖相关测试 |
| cpu_overload | 120s | 降级为1 worker |

### Fallback执行流程

```
发现问题 → 发送消息 → 等待响应
    │
    ├── Supervisor响应 → 执行响应指令
    │
    └── 等待超时 → 执行fallback
        ├── update_state.py: {"status": "fallback"}
        ├── 执行fallback动作
        ├── send_message.py: fallback_triggered
        └── 继续执行（降级模式）
```

---

*创建日期: 2026-06-09*
*来源: skills/ut/unit-test-executor/SKILL.md*