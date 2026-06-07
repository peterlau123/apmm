# 依赖下载处理规则

## 下载路径

| 类型 | 机器 | 路径 |
|------|------|------|
| Python依赖 | t_ascend | `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies` |
| HF模型 | t_ascend | `/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub` |

注：/gpfs为共享存储，t_h20可直接访问

## 下载流程

```
Step 1: 收到请求
├── inbox: {"type": "download_model", "name": "xxx"}
├── 更新status: {"status": "downloading"}

Step 2: 检查磁盘空间
├── 调用 check_disk.py
├── 如果空间不足 → 发送disk_space_warning

Step 3: 执行下载
├── 调用 download_model.py 或 download_package.py
├── 监控下载进度

Step 4: 下载成功
├── 验证文件完整性
├── 发送 dependency_ready (P2)
├── 更新status: {"status": "running"}

Step 5: 下载失败
├── 记录失败模型到 failed_models.json
├── 累计失败计数
├── 失败 < 10个 → 继续尝试其他模型
├── 失败 ≥ 10个 → 发送 dependency_failed (P1)
└── 等待用户响应（跳过或重试）
```

## 模型下载失败处理策略

| 失败数量 | 处理方式 |
|----------|----------|
| < 10个 | 记录失败，继续下载其他模型 |
| ≥ 10个 | 发送 `dependency_failed`，通知用户 |

**用户响应选项**：
- `skip_failed` → 跳过失败模型，记录到skip_manifest
- `retry_failed` → 重试下载失败模型

## Skip记录格式

记录文件：`/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/skip_manifest.json`

```json
{
  "skipped_models": [
    {"name": "xxx/model1", "reason": "download_failed", "skipped_at": "2026-06-06T10:30:00"},
    {"name": "xxx/model2", "reason": "download_failed", "skipped_at": "2026-06-06T10:35:00"}
  ],
  "total_skipped": 15,
  "last_updated": "2026-06-06T10:35:00"
}
```

## 磁盘空间监控

| 条件 | 处理 |
|------|------|
| /gpfs使用 > 90% | 发送 `disk_space_warning` (P1) |
| /gpfs使用 > 95% | 发送 `disk_space_critical` (P0)，停止下载 |

**汇报格式**：
```json
{
  "type": "disk_space_warning",
  "priority": "P1",
  "data": {
    "path": "/gpfs/gcsp/M2.7_verify",
    "used_percent": 92,
    "total_gb": 1900,
    "used_gb": 1748,
    "available_gb": 152
  }
}
```

---

*创建日期: 2026-06-06*