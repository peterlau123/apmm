# UT Workflow 运行总结报告

**运行ID**: ut-20260630-163959  
**报告时间**: 2026-07-03  
**报告人**: OpenCode Agent  

---

## 1. 遇到的问题

### 1.1 Batch目录结构问题 (严重)

**问题描述**:
- 2026-07-02 22:56 之前，`generate_batch.py` 脚本未正确创建子目录
- `batch_results.json` 直接写入 `batches/` 目录，导致多个batch结果相互覆盖
- 无法准确统计实际执行了多少个batch

**根本原因**:
```python
# 旧代码 (有bug)
batch_results_path = batch_dir / "batch_results.json"  # 直接覆盖

# 修复后代码
batch_subdir = batch_dir / batch_id  # 如 batches/batch_20260703_xxxx/
batch_results_path = batch_subdir / "batch_results.json"
```

**影响**:
- 约前100+个batch的结果丢失或被覆盖
- 无法准确统计batch执行进度
- resume机制失效

### 1.2 GPU资源检测不稳定

**问题描述**:
- 间歇性出现 "0 free GPU" 警告
- 导致batch降级为单卡串行执行，所有测试被ignored

**原因**: 远程H20服务器上的僵尸进程占用GPU

**解决方案**: 清理僵尸进程后恢复
```bash
nvidia-smi
ps aux | grep pytest
killall -9 pytest python3
```

### 1.3 Manifest统计不准确

**问题描述**:
- `manifest-updater` 脚本存在bug，未能正确更新统计信息
- 临时使用inline Python脚本手动更新

**临时方案**:
```python
# 手动更新manifest
for batch_results in all_batches:
    for test in manifest['tests']:
        if test['id'] == result['id']:
            test['status'] = result['status']
            # ... 更新其他字段
```

---

## 2. 当前运行状态

### 2.1 统计数据

| 指标 | 数值 | 备注 |
|------|------|------|
| **总测试数** | 32,964 | manifest.json中的总条目 |
| **已执行测试** | 8,365 | 25.39% |
| **待执行测试** | 24,591 | 74.61% |
| **目标Batch数** | 1,100 | 用户设定 |
| **已生成Batch** | ~430 | 有batch_config.json |
| **已完成Batch** | ~398 | 有batch_results.json |
| **中间状态Batch** | 32 | 有config无results |

### 2.2 测试结果分布

| 状态 | 数量 | 占比 |
|------|------|------|
| **Passed** | 7,082 | 84.7% |
| **Failed** | 341 | 4.1% |
| **Error** | 491 | 5.9% |
| **Ignored** | 456 | 5.3% |
| **Pending** | 24,591 | - |

### 2.3 运行时间线

| 时间 | 事件 |
|------|------|
| 2026-06-30 16:39 | Run启动 |
| 2026-07-02 22:56 | 修复batch目录结构 |
| 2026-07-02 22:56-2026-07-03 09:30 | 正常执行阶段 |
| 2026-07-03 09:30 | 暂停执行，生成总结报告 |

### 2.4 文件位置

```
runs/ut-20260630-163959/
├── manifest.json              # 测试清单和状态
├── workflow_state.json        # Workflow状态
├── workflow.yaml              # Workflow配置
├── batches/                   # Batch目录
│   ├── batch_20260702_xxxx/  # 旧格式（目录结构问题）
│   ├── batch_20260703_xxxx/  # 新格式（独立子目录）
│   │   ├── batch_config.json
│   │   └── batch_results.json
│   └── ...
└── ut_logs/                  # 测试日志
    └── batch_xxxx/
```

---

## 3. 待办事项

### 3.1 Resume机制改进 (高优先级)

**目标**: 解决batch统计不准确和resume失效问题

**推荐方案**: **方案A + 方案C 组合**

#### 方案A: workflow_state.json 作为单一事实源

修改 `workflow_state.json` 结构：

```json
{
  "run_id": "ut-20260630-163959",
  "status": "running",
  "target_batches": 1100,
  "created_at": "2026-06-30T16:39:00Z",
  "last_updated": "2026-07-03T09:30:00Z",
  "batches": {
    "batch_20260703_093155": {
      "status": "completed",
      "created_at": "2026-07-03T09:31:55Z",
      "started_at": "2026-07-03T09:32:00Z",
      "completed_at": "2026-07-03T09:40:00Z",
      "config_path": "batches/batch_20260703_093155/batch_config.json",
      "results_path": "batches/batch_20260703_093155/batch_results.json",
      "stats": {
        "total": 8,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "ignored": 8
      }
    }
  },
  "statistics": {
    "generated": 430,
    "running": 0,
    "completed": 398,
    "failed_to_execute": 32,
    "total_tests_executed": 8365,
    "total_tests_pending": 24599
  },
  "last_batch_id": "batch_20260703_093155",
  "resume_info": {
    "can_resume": true,
    "last_successful_batch": "batch_20260703_093155",
    "pending_batches_count": 702
  }
}
```

**修改点**:
1. `generate_batch.py`: 生成batch时更新 `workflow_state.json`
2. `execute_batch.py`: 执行完成时更新 `workflow_state.json`
3. `resume.py`: 新增，从 `workflow_state.json` 恢复状态

#### 方案C: Event Log 追加模式

创建 `logs/batch_events.jsonl`:

```jsonl
{"event": "batch_generated", "batch_id": "batch_20260703_093155", "timestamp": "2026-07-03T09:31:55Z", "run_id": "ut-20260630-163959"}
{"event": "batch_started", "batch_id": "batch_20260703_093155", "timestamp": "2026-07-03T09:32:00Z", "pid": 12345}
{"event": "batch_completed", "batch_id": "batch_20260703_093155", "timestamp": "2026-07-03T09:40:00Z", "duration_sec": 480, "stats": {"total":8,"passed":0,"ignored":8}}
```

**优点**:
- 追加模式，不会覆盖历史
- 可重建完整执行历史
- 便于审计和调试

### 3.2 未完成Batch处理

**当前状态**: 32个中间状态batch（有config无results）

**处理方案**:

```python
# scan_intermediate.py
import os
import json

batch_dir = "runs/ut-20260630-163959/batches"
intermediate = []

for d in os.listdir(batch_dir):
    config = os.path.join(batch_dir, d, "batch_config.json")
    results = os.path.join(batch_dir, d, "batch_results.json")
    if os.path.exists(config) and not os.path.exists(results):
        intermediate.append(d)

print(f"发现 {len(intermediate)} 个未完成batch")
print("建议：批量执行或标记为失败")
```

**操作选项**:
1. **批量执行**: 自动重新执行所有中间状态batch
2. **标记跳过**: 将这些batch标记为 `skipped`，从manifest中移除对应测试的batch_id
3. **忽略**: 继续生成新batch，这些测试会在后续被重新选中

### 3.3 统计工具修复

**问题**: `manifest-updater` 脚本bug

**修复计划**:
1. 修复 `skills/ut/manifest-updater/scripts/update_manifest.py`
2. 或弃用，改用 `workflow_state.json` 驱动
3. 新增 `report.py` 工具，从 `workflow_state.json` 生成报告

### 3.4 后续执行计划

**目标**: 完成1,100个batch

**当前进度**:
- 已完成: ~398 batch
- 还需: ~702 batch

**建议执行策略**:

1. **修复resume机制** (1-2小时)
   - 实现方案A和C
   - 测试resume功能

2. **处理中间状态batch** (2-4小时)
   - 执行或跳过32个中间batch
   - 更新manifest

3. **批量执行剩余batch** (预估12-24小时)
   - 使用自动化脚本
   - 每50个batch生成一次进度报告
   - 监控GPU状态

**风险控制**:
- 每2小时检查一次GPU状态
- 设置checkpoint，可从中断处恢复
- 定期备份 `workflow_state.json`

---

## 4. 建议的下一步行动

### 立即执行 (今天)

1. [ ] 修复 `generate_batch.py` - 确保正确使用子目录（已完成）
2. [ ] 实现 `workflow_state.json` 更新逻辑
3. [ ] 处理32个中间状态batch

### 短期 (本周)

4. [ ] 实现 `resume.py` - 从workflow_state恢复
5. [ ] 批量执行剩余~700 batch
6. [ ] 每50 batch生成进度报告

### 中期 (下周)

7. [ ] 分析failed/error/ignored测试结果
8. [ ] 决定重跑策略
9. [ ] 生成最终UT报告

---

## 附录

### A. 关键文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| Manifest | `runs/ut-20260630-163959/manifest.json` | 测试清单 |
| Workflow State | `runs/ut-20260630-163959/workflow_state.json` | 运行状态 |
| Batch Config | `runs/ut-20260630-163959/batches/batch_xxx/batch_config.json` | Batch配置 |
| Batch Results | `runs/ut-20260630-163959/batches/batch_xxx/batch_results.json` | Batch结果 |
| UT Logs | `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_xxx/` | 远程日志 |

### B. 快速命令

```bash
# 查看统计
python -c "import json; m=json.load(open('runs/ut-20260630-163959/manifest.json')); print('Executed:', len([t for t in m['tests'] if t.get('status') and t['status']!='pending']))"

# 检查中间状态batch
python -c "import os; [print(d) for d in os.listdir('runs/ut-20260630-163959/batches') if os.path.exists(f'runs/ut-20260630-163959/batches/{d}/batch_config.json') and not os.path.exists(f'runs/ut-20260630-163959/batches/{d}/batch_results.json')]"

# 手动更新manifest
python scripts/update_manifest.py --manifest runs/ut-20260630-163959/manifest.json
```

### C. 参考文档

- [tasks/ut/README.md](../../../tasks/ut/README.md) - UT模块总入口
- [skills/ut/batch-selector/SKILL.md](../../../skills/ut/batch-selector/SKILL.md) - Batch选择器
- [skills/ut/unit-test-executor/SKILL.md](../../../skills/ut/unit-test-executor/SKILL.md) - 测试执行器

---

*报告结束*
