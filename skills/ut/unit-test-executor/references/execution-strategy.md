# 执行策略

> 引用: docs/superpowers/specs/agents/unit-test-executor-agent/test-execution-plan.md

## Phase执行策略

### Phase 1: 13,165 tests (ut_test_list.txt)

| Round | 目标 | 测试数 | 策略 |
|-------|------|:------:|------|
| Round 1 | Model-free | ~7,740 (60%) | 自动检测HF依赖，跳过model测试 |
| Round 2 | Model tests | ~3,870 (30%) | 需下载关键模型 |
| Round 3 | Edge cases | ~1,290 (10%) | 手动分析后执行 |

### Phase 2: ~18,207 tests (diff from full list)

| Round | 目标 | 测试数 |
|-------|------|:------:|
| Round 1 | Model-free | ~11,269 |
| Round 2 | Model-dependent | ~5,635 |
| Round 3 | Edge cases | ~1,878 |

### Phase 3: 34 collection errors

- 手动分析处理
- 需要修复测试脚本本身

## GPU分配

| Worker | GPU | CUDA_VISIBLE_DEVICES |
|--------|-----|----------------------|
| 1 | 0-1 | 0,1 |
| 2 | 2-3 | 2,3 |
| 3 | 4-5 | 4,5 |
| Reserved | 6-7 | 模型下载/特殊测试 |

## 超时设置

| 测试类型 | 超时 |
|----------|:----:|
| Model-free | 120s |
| Model-dependent | 300s |
| HF download | 600s |

## 连续错误阈值

- **阈值**: 5次连续错误
- **触发**: 跳过当前测试文件剩余测试
- **记录**: 写入PROGRESS.md skip记录
- **清零**: 跳过后计数清零，继续下一文件

## HF模型依赖检测

### 路径模式检测

| 路径 | 分类 |
|------|------|
| tests/models/* | MODEL_DEPENDENT |
| tests/lora/* | MODEL_DEPENDENT |
| tests/tokenizers_* | MODEL_DEPENDENT |
| tests/entrypoints/* | MODEL_DEPENDENT |
| tests/evals/* | MODEL_DEPENDENT |
| tests/kernels/* | MODEL_FREE |

### Round 2关键模型

| Model | Priority | Size |
|-------|:--------:|:----:|
| meta-llama/Llama-3.2-1B-Instruct | P0 | ~1.5GB |
| EleutherAI/gpt-j-6b | P1 | ~12GB |
| mistralai/Mistral-7B-v0.1 | P1 | ~14GB |
| bigscience/bloom-560m | P2 | ~1GB |

## 预估时间

| Phase | Round | Tests | Duration |
|-------|-------|:------:|:--------:|
| Phase 1 | Round 1 | ~7,740 | 2-3 hours |
| Phase 1 | Round 2 | ~3,870 | 4-6 hours |
| Phase 1 | Round 3 | ~1,290 | 1-2 hours |
| Phase 2 | Round 1 | ~11,269 | 3-4 hours |
| Phase 2 | Round 2 | ~5,635 | 6-8 hours |
| Phase 2 | Round 3 | ~1,878 | 1-2 hours |
| **Total** | - | **31,947** | **18-27 hours** |

---

*创建日期: 2026-06-06*