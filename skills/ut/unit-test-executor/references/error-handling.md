# 错误处理规则

## 错误分类 (C/E/D/P/M/S)

| 类别 | 名称 | 识别规则 | 处理方式 |
|------|------|----------|----------|
| C | 代码Bug | AssertionError, RuntimeError(vllm), ValueError | 记录issues.json，继续执行 |
| E | 环境问题 | OutOfMemoryError, CUDA OOM, Resource unavailable | 汇报Supervisor，等待响应 |
| D | 依赖缺失 | ImportError, ModuleNotFoundError | 汇报Supervisor，请求下载 |
| P | 平台兼容 | NotImplementedError, AttributeError(torch), Torch not compiled | 记录，继续执行 |
| M | 模型缺失 | Model not found, HF download failed | 汇报Supervisor，请求下载 |
| S | 跳过问题 | Skipped标记 | 标记skip，继续执行 |

## 处理流程

```
检测错误 → classify_error.py → 分类
    │
    ├── C/P/S类 → 记录issues.json，继续执行
    │
    └── E/D/M类 → 汇报Supervisor
    │     ├── 立即发送消息
    │     ├── 等待响应
    │     │   ├── Supervisor响应 → 执行响应指令
    │     │   └── 等待超时 → 执行fallback
    │     └── 记录处理结果
```

## 连续错误处理

```
连续错误计数流程:
├── 测试失败 → 计数 +1
├── 测试成功 → 计数清零
│
└── 计数 = 5 (阈值触发)
    ├── 记录skip信息到PROGRESS.md:
    │   ### Skip Record
    │   - Trigger: 5 consecutive errors
    │   - Test File: tests/xxx/test_xxx.py
    │   - Error Type: D-依赖缺失
    │   - Tests Skipped: 42
    │
    ├── 跳过当前测试文件剩余测试
    ├── 清零计数
    └── 继续下一测试文件
```

## Skip记录格式

```markdown
### 2026-06-06 10:30:15 - Skip Record

**触发原因**: 5 consecutive errors
**测试文件**: tests/quantization/test_marlin.py
**错误类型**: D-依赖缺失 (wrap_triton)
**跳过测试数**: 42
**建议处理**: Add wrap_triton shim or skip quantization directory
```

## issues.json更新格式

```json
{
  "id": "D-42",
  "category": "D",
  "category_name": "依赖缺失",
  "description": "wrap_triton 缺失导致 quantization 测试失败",
  "affected_tests": 512,
  "status": "open",
  "first_seen": "2026-06-06T10:30:00",
  "notes": "自动跳过记录，需添加 shim"
}
```

## Fallback策略详情

| 问题类型 | 等待超时 | Fallback动作 |
|----------|:--------:|--------------|
| bastion_disconnect | 60s | 暂停执行，每30s重试ping，等待连接恢复 |
| gpu_occupied | 60s | 降级为1 worker，使用空闲GPU |
| dependency_request | 120s | 跳过依赖相关测试，继续其他测试 |
| cpu_overload | 120s | 降级为1 worker，减少并发 |

---

*创建日期: 2026-06-06*