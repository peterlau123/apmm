# 补救76个历史遗漏Batch执行指令

**生成日期:** 2026-07-07
**目标运行目录:** `runs/ut-20260630-163959`
**遗漏Batch数量:** 76个（全部为Multi-GPU distributed tests）

---

## 概览

| 指标 | 数量 |
|-----|-----|
| 总遗漏Batch | 76 |
| Multi-GPU Batch | 76 |
| Single-GPU Batch | 0 |
| 分布式测试数 | ~400 per batch |

**注意:** 所有遗漏batch都是分布式测试（require GPU >= 2），执行时需要确保多GPU环境可用。

---

## 补救执行方案

### 方案1：使用auto_run_batches_two_phase.py（推荐）

```bash
# 在apmm目录执行
cd D:/workspace/apmm

# 使用Phase 1脚本补救执行
python tasks/ut/scripts/auto_run_batches_two_phase.py \
    --run-dir runs/ut-20260630-163959 \
    --batch-list runs/ut-20260630-163959/missing_batches_remediation.json \
    --batch-group-size 10 \
    --checkpoint-interval 5 \
    --update-manifest-immediately
```

**优势:**
- 强制检查点确保每步完成验证
- Manifest实时更新，避免遗漏
- checkpoint文件支持中断恢复

### 方案2：直接pytest执行（手动）

```bash
# 逐batch执行（示例）
for batch_id in $(cat runs/ut-20260630-163959/missing_batches_list.txt); do
    echo "Remediating: $batch_id"
    
    # 读取batch配置中的测试列表
    tests=$(python -c "import json; c=json.load(open('runs/ut-20260630-163959/batches/$batch_id/batch_config.json')); print(' '.join([t['test_node'] for t in c['tests']]))")
    
    # 执行pytest
    pytest $tests --tb=short -v \
        --json-report --json-report-file=runs/ut-20260630-163959/batches/$batch_id/batch_results.json
    
    # 更新manifest
    python tasks/ut/scripts/merge_batch_manifests.py \
        --run-dir runs/ut-20260630-163959 \
        --batch-id $batch_id
done
```

---

## Opencode执行指令

将以下内容粘贴到Opencode执行：

```
任务：补救76个历史遗漏batch执行

工作目录：D:/workspace/apmm

步骤：
1. 读取补救计划：
   - 文件：runs/ut-20260630-163959/missing_batches_remediation.json
   - 确认76个batch ID列表

2. 确认多GPU环境：
   - 检查GPU数量：nvidia-smi -L
   - 需要 GPU >= 2（distributed tests）

3. 执行补救（推荐使用2-phase脚本）：
   python tasks/ut/scripts/auto_run_batches_two_phase.py \
       --run-dir runs/ut-20260630-163959 \
       --start-from missing \
       --batch-group-size 10 \
       --checkpoint-interval 5

4. 监控执行进度：
   - 查看checkpoint文件：runs/ut-20260630-163959/checkpoint_progress.json
   - 每5个batch检查一次manifest更新

5. 补救完成后验证：
   - 检查batch_results.json数量：find batches/ -name "batch_results.json" | wc -l
   - 预期：651 + 76 = 727个
   - 检查manifest完整性：python -c "import json; m=json.load(open('manifest.json')); print(f'Tests: {len(m[\"tests\"])}')"
```

---

## 执行优先级建议

由于所有batch都是Multi-GPU distributed tests，建议：

1. **GPU资源确认**：确保至少2个GPU可用
2. **分批执行**：batch_group_size=10，避免资源竞争
3. **Checkpoint间隔**：每5个batch保存进度
4. **中断恢复**：如果中途停止，可从checkpoint文件恢复

---

## 预期结果

| 指标 | 补救前 | 补救后 |
|-----|-------|-------|
| Batch执行完成 | 651/729 (89%) | 727/729 (99.7%) |
| Manifest记录 | 32,964 tests | ~33,500 tests |
| 遗漏batch | 76 | 2 (可能失败) |

---

## 相关文件路径

| 文件 | 路径 |
|-----|-----|
| 补救计划 | `runs/ut-20260630-163959/missing_batches_remediation.json` |
| Phase 1脚本 | `tasks/ut/scripts/auto_run_batches_two_phase.py` |
| Manifest文件 | `runs/ut-20260630-163959/manifest.json` |
| Batch目录 | `runs/ut-20260630-163959/batches/` |

---

*生成时间: 2026-07-07*