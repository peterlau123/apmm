# UT Two-phase运行策略设计文档

**设计日期:** 2026-07-06
**设计方法:** Superpowers Brainstorming
**设计背景:** 解决大批量测试（500+ batch）运行效率问题，避免manifest遗漏

---

## 设计背景与问题

### 当前问题

在2026-07-05的500批次测试运行中，发现以下问题：

1. **执行效率低** - Single-phase策略逐batch处理，每个batch都有agent等待时间
2. **Manifest遗漏** - 脚本批量运行缺少强制检查点，导致424个batch未更新manifest
3. **决策缺失** - 实践中使用了两-phase策略（脚本批量 + 后处理），但未文档化

### 设计目标

- **提高大批量测试运行效率**（500+ batch）
- **保证数据完整性**（避免manifest遗漏）
- **文档化两种运行策略**（single-phase + two-phase）
- **支持灵活决策**（人工决策 + agent辅助重试）

---

## 策略体系概述

### UT Workflow的两个独立维度

**维度1: 运行通道（驱动方式）**
- `terminal-workflow`（终端通道） - 用户在Claude/OpenCode会话触发，线性模式
- `hermes-workflow`（生产通道） - 飞书触发，supervisor托管，支持kanban模式

**维度2: 运行策略（batch处理方式）**
- `single-phase`（默认） - Agent介入每个stage，逐batch处理
- `two-phase`（新增） - Phase 1脚本批量执行 + Phase 2 agent智能处理

---

## 通道 × 策略组合矩阵

两种通道与两种策略可自由组合，形成4种运行模式：

| 组合 | 通道 | 策略 | 适用场景 | 典型用例 |
|------|------|------|---------|---------|
| **组合1** | terminal-workflow | single-phase | 调试单batch | L1-L3测试，实时agent介入调试 |
| **组合2** | terminal-workflow | two-phase | 生产环境（本地） | 本地快速验证500 batch |
| **组合3** | hermes-workflow | single-phase | 生产/调试环境 | 飞书触发全量测试，agent实时处理 |
| **组合4** | hermes-workflow | two-phase | 生产环境（大批量） | 飞书触发快速验证 + 智能补充 |

---

## Two-phase策略结构

### Phase命名约定

```
Two-phase策略结构：

Phase 1: 脚本批量执行（无agent介入）
  ├─ Stage 1: Batch配置生成
  ├─ Stage 2: Batch执行（调用pytest）
  ├─ Stage 3: 结果收集
  └─ Stage 4: Manifest增量更新（强制检查点）

Phase 2: Agent介入处理
  ├─ Stage 1: 统计分析（按error_type分类）
  │   └─ 生成丰富统计报告，等待人工决策
  │
  └─ Stage 2: Agent辅助重试（人工决策后）
      └─ 执行人工指定的batch重试，更新manifest
```

**命名说明：**
- Phase 1的"Stage"是脚本执行流程
- Phase 2的"Stage"是agent处理流程
- 保持Two-phase称呼，清晰表达"脚本批量 → agent智能"的两阶段思想

---

## Phase 1：脚本批量执行

### Phase 1的核心特点

- **无agent介入** - 纯脚本执行，速度最快
- **高GPU利用率** - 无agent上下文开销
- **强制检查点** - 避免manifest遗漏（关键改进）

### Phase 1执行流程

```python
def phase1_batch_loop(batch_group_size, checkpoint_interval):
    """Phase 1: 脚本批量执行 + 强制检查点"""

    checkpoint_log = []

    for i in range(batch_group_size):
        batch_id = create_batch_id(i)

        try:
            # Stage 1: Batch配置生成
            config_path = create_batch_config(batch_id, tests)

            # ✅ 检查点1: 配置文件完整性
            assert config_path.exists(), f"[STOP] 配置文件未创建: {config_path}"
            assert validate_config_schema(config_path), f"[STOP] 配置格式错误"

            # Stage 2: Batch执行
            result = execute_batch_script(batch_id)

            # ✅ 检查点2: 执行完成验证
            assert result.exit_code is not None, f"[STOP] 执行未完成: {batch_id}"

            # Stage 3: 结果收集
            result_path = write_batch_results(batch_id, result)

            # ✅ 检查点3: 结果文件生成
            assert result_path.exists(), f"[STOP] 结果文件未生成: {result_path}"

            # Stage 4: Manifest增量更新
            update_manifest_incremental(batch_id, result)

            # ✅ 检查点4: Manifest更新验证
            assert verify_manifest_updated(batch_id), f"[STOP] Manifest未更新"

            checkpoint_log.append({
                'batch_id': batch_id,
                'status': '✓ SUCCESS',
                'timestamp': datetime.now()
            })

            # ✅ 定期checkpoint写入（便于恢复）
            if i % checkpoint_interval == 0:
                write_checkpoint_file(checkpoint_log)
                print(f"[Checkpoint] 已完成{i}/{batch_group_size}个batch")

        except AssertionError as e:
            # ✗ 检查点失败 → 立即停止循环
            log_error(f"[ABORT] 检查点失败: {e}")
            write_checkpoint_file(checkpoint_log)
            raise

        except Exception as e:
            # 记录错误但继续执行
            log_error(f"[ERROR] Batch执行异常: {batch_id} - {e}")
            checkpoint_log.append({
                'batch_id': batch_id,
                'status': f'✗ ERROR: {e}',
                'timestamp': datetime.now()
            })

    # Phase 1完成报告
    phase1_report = generate_phase1_summary(checkpoint_log)
    write_report(phase1_report, 'phase1_summary.json')

    return checkpoint_log
```

### Phase 1配置参数

```yaml
phase1:
  auto_create_batches: true        # 自动创建batch配置
  auto_execute: true               # 自动执行batch
  checkpoint_interval: 10          # 每10个batch写checkpoint（便于恢复）
  enable_force_checkpoints: true   # 启用强制检查点（避免manifest遗漏）
```

---

## Phase 2：Agent介入处理

### Phase 2的核心特点

- **统计分析优先** - Stage 1只做统计，不自动重试
- **人工决策介入** - 人工查看报告后决定重试策略
- **Agent辅助执行** - Stage 2接收决策后自动重试batch

---

## Phase 2 Stage 1：统计分析

### 统计维度：以error_type为核心

根据`manifest_schema.json`的error_type枚举（第141行），设计以下统计项：

**Error_type完整枚举（11种）：**

| Error_type | 描述 | 优先级建议 | 修复建议 |
|-----------|------|-----------|---------|
| **dependency** | 依赖缺失（ImportError, ModuleNotFoundError） | P1 | 检查requirements.txt和依赖安装路径 |
| **network** | 网络错误（ConnectionError, HTTP 503/404） | P0 | 检查Bastion连接或网络防火墙配置 |
| **resource** | 资源不足（CUDA OOM, GPU不可用） | P1 | 检查GPU内存分配或减少batch size |
| **version** | 版本兼容问题（vLLM v0.13.0 + PyTorch 2.5.1） | P1 | 检查版本匹配或升级依赖 |
| **functional** | 功能错误（AssertionError, ValueError） | P2 | 代码逻辑问题，需人工分析 |
| **download_error** | 模型下载失败（Model not found, config.json missing） | P1 | 检查HuggingFace模型缓存和网络连接 |
| **oom** | GPU显存不足（CUDA out of memory，retriable） | P0 | 检查GPU内存或减少并发batch |
| **timeout** | pytest执行超时（retriable） | P0 | 检查网络或增加pytest timeout阈值 |
| **collection** | pytest collection/import阶段错误 | P2 | 检查测试环境配置和fixture |
| **assertion** | 断言失败（AssertionError） | P2 | 代码逻辑问题，需人工分析具体assert内容 |
| **other** | 其他未分类错误 | P2 | 未分类错误，需人工逐一查看日志 |

### Stage 1统计报告格式

**JSON格式示例：**

```json
{
  "phase2_stage1_report": {
    "generated_at": "2026-07-06T10:00:00Z",
    "phase1_batches_count": 500,

    "error_statistics": {
      "timeout": {
        "batch_count": 45,
        "test_count": 180,
        "batch_list": [
          "batch_20260701_001",
          "batch_20260701_002",
          ...
        ],
        "test_list": [
          "tests/entrypoints/openai/test_serving_chat.py::test_timeout_case1",
          ...
        ],
        "affected_test_files": [
          "tests/entrypoints/openai/test_serving_chat.py",
          "tests/basic_correctness/test_basic_correctness.py"
        ],
        "suggestion": "检查网络连接或增加pytest timeout阈值",
        "priority": "P0"
      },

      "network": {
        "batch_count": 30,
        "test_count": 120,
        "batch_list": [...],
        "test_list": [...],
        "affected_test_files": [...],
        "suggestion": "检查Bastion连接稳定性或网络防火墙配置",
        "priority": "P0"
      },

      "oom": { ... },
      "dependency": { ... },
      "download_error": { ... },
      "resource": { ... },
      "version": { ... },
      "assertion": { ... },
      "functional": { ... },
      "collection": { ... },
      "other": { ... }
    },

    "summary": {
      "total_errors": 615,
      "total_batches_with_errors": 150,
      "top_3_error_types": ["timeout", "network", "assertion"],
      "recommendation": "优先修复timeout和network问题（P0），可批量重试45+30个batch"
    }
  }
}
```

**每个error_type统计项字段：**

| 字段 | 说明 | 用途 |
|------|------|------|
| **batch_count** | 该error_type影响的batch总数 | 快速了解影响范围 |
| **test_count** | 该error_type影响的test总数 | 细粒度统计 |
| **batch_list** | 受影响的所有batch_id清单 | Phase 2 Stage 2重试时直接读取 |
| **test_list** | 受影响的所有test_node清单 | 细粒度分析 |
| **affected_test_files** | 受影响的test文件清单 | 按文件维度统计 |
| **suggestion** | 修复建议 | 人工决策参考 |
| **priority** | 优先级（P0/P1/P2） | 人工决策优先级参考 |

### Stage 1执行逻辑

```python
def phase2_stage1_analyze():
    """Phase 2 Stage 1: 统计分析"""

    # Step 1: 扫描Phase 1的所有batch
    phase1_batch_list = get_phase1_batch_list()

    # Step 2: 从manifest读取每个batch的test结果
    manifest = load_manifest()

    # Step 3: 按error_type分类统计
    error_stats = {}

    for batch_id in phase1_batch_list:
        batch_tests = get_tests_by_batch_id(manifest, batch_id)

        for test in batch_tests:
            if test['status'] in ['failed', 'error']:
                error_type = test['error_type'] or 'other'

                # 初始化该error_type的统计项
                if error_type not in error_stats:
                    error_stats[error_type] = {
                        'batch_count': 0,
                        'test_count': 0,
                        'batch_list': [],
                        'test_list': [],
                        'affected_test_files': [],
                        'suggestion': get_error_type_suggestion(error_type),
                        'priority': get_error_type_priority(error_type)
                    }

                # 累加统计
                error_stats[error_type]['batch_count'] += 1
                error_stats[error_type]['test_count'] += 1

                # 记录batch_id（避免重复）
                if batch_id not in error_stats[error_type]['batch_list']:
                    error_stats[error_type]['batch_list'].append(batch_id)

                # 记录test_node
                error_stats[error_type]['test_list'].append(test['test_node'])

                # 记录test_file（避免重复）
                test_file = test['test_file']
                if test_file not in error_stats[error_type]['affected_test_files']:
                    error_stats[error_type]['affected_test_files'].append(test_file)

    # Step 4: 生成统计报告（JSON + Markdown）
    report = generate_report(error_stats)
    write_json_report(report, 'phase2_stage1_report.json')
    write_markdown_report(report, 'phase2_stage1_report.md')

    # Step 5: 输出提示（等待人工决策）
    print("Phase 2 Stage 1完成，统计报告已生成")
    print("请查看报告，决定重试哪些batch")

    return report
```

---

## Phase 2 Stage 2：Agent辅助重试

### Stage 2的核心特点

- **人工决策驱动** - 不自动重试，等待人工决策
- **Agent执行重试** - 接收决策后自动执行batch重试
- **增量更新manifest** - 只更新重试batch的结果

### 人工决策输入格式

```python
user_decision = {
    "retry_error_types": ["timeout", "oom"],  # 重试哪些error_type的batch
    "retry_specific_batches": [],             # 或指定特定batch_id
    "retry_all": False                        # 是否重试所有失败batch
}
```

### Stage 2执行逻辑

```python
def phase2_stage2_retry(user_decision):
    """Phase 2 Stage 2: Agent辅助重试（人工决策后）"""

    # Step 1: 根据决策确定batch清单
    batches_to_retry = []

    # 方式1: 按error_type批量重试（推荐）
    if user_decision.retry_error_types:
        report = load_phase2_stage1_report()
        for error_type in user_decision.retry_error_types:
            batch_list = report['error_statistics'][error_type]['batch_list']
            batches_to_retry.extend(batch_list)

    # 方式2: 指定特定batch重试
    if user_decision.retry_specific_batches:
        batches_to_retry.extend(user_decision.retry_specific_batches)

    # 方式3: 重试所有失败batch（不推荐）
    if user_decision.retry_all:
        batches_to_retry = get_all_failed_batches()

    # 去重
    batches_to_retry = list(set(batches_to_retry))

    # Step 2: Agent执行重试
    print(f"Phase 2 Stage 2开始，准备重试{len(batches_to_retry)}个batch")

    retry_results = []
    for batch_id in batches_to_retry:
        # 重新执行batch
        result = execute_batch_script(batch_id)

        # ✅ 强制检查点：结果文件生成
        result_path = write_batch_results(batch_id, result)
        assert result_path.exists()

        # ✅ 强制检查点：Manifest增量更新
        update_manifest_with_batch_results(batch_id, result)
        assert verify_manifest_updated(batch_id)

        retry_results.append({
            'batch_id': batch_id,
            'status': 'success' if result.exit_code == 0 else 'failed',
            'tests_passed': result.stats['passed'],
            'tests_failed': result.stats['failed']
        })

    # Step 3: 生成重试报告
    retry_report = generate_retry_summary(retry_results)
    write_report(retry_report, 'phase2_stage2_report.json')

    return retry_report
```

---

## 人工决策交互方式

### 支持多种交互方式（根据通道自动选择）

**方式A：workflow.yaml配置（自动化）**

```yaml
phase2_stage2:
  auto_retry_error_types: ["timeout", "oom", "network"]
  wait_for_manual_decision: false
```

**方式B：飞书交互（hermes-workflow通道）**

飞书卡片展示Phase 2 Stage 1统计报告，用户回复决策选项。

**方式C：终端交互（terminal-workflow通道）**

```
Phase 2 Stage 1完成，请输入决策：
  retry --error-types timeout,oom
  retry --batches batch_001,batch_002
  retry --all
  skip
```

**配置方式（fallback）：**

```yaml
decision_interface:
  terminal_workflow: "terminal"   # terminal-workflow → 终端交互
  hermes_workflow: "feishu"       # hermes-workflow → 飞书交互
  fallback: "yaml_config"         # 备选：yaml配置（无需人工介入）
```

---

## workflow.yaml完整配置

### 配置字段设计

```yaml
workflow:
  name: "UT Test Workflow"
  version: "2.2"

  # ✅ 新增：运行策略选择
  execution_strategy: "two-phase"  # "single-phase"（默认）或 "two-phase"

  # ✅ Two-phase策略专用配置
  batch_group_size: 500  # Phase 1执行的batch总数

  # ✅ Phase 1配置
  phase1:
    auto_create_batches: true
    auto_execute: true
    checkpoint_interval: 10
    enable_force_checkpoints: true

  # ✅ Phase 2配置
  phase2:
    stage1:
      generate_report: true
      report_formats: ["json", "markdown"]
      auto_generate_suggestions: true

    stage2:
      auto_retry_error_types: []
      wait_for_manual_decision: true
      retry_on_decision: true

  # ✅ 人工决策交互方式
  decision_interface:
    terminal_workflow: "terminal"
    hermes_workflow: "feishu"
    fallback: "yaml_config"

  # ✅ 通道配置（已有）
  kanban:
    enabled: false

  # ✅ 其他配置（已有）
  remote_server: "t_h20"
  max_retry: 3
  test_list_path: "runs/ut-20260630-163959/test_list.txt"
```

---

## 实施步骤和改动文件

### 需要改动的地方（5个文件）

**1. workflow.yaml模板更新**

**文件位置：**
- `tasks/ut/deployment/production/config/workflow.yaml`（生产配置模板）
- `tests/ut/integration/fixtures/workflow.l*.yaml`（L1-L4测试模板）

**改动内容：**
- 新增字段：`execution_strategy`, `batch_group_size`
- 新增配置块：`phase1`, `phase2`, `decision_interface`

---

**2. 创建auto_run_batches.py改进版本**

**文件位置：** `tasks/ut/scripts/auto_run_batches_two_phase.py`

**改动内容：**
- 添加强制检查点（避免manifest遗漏）
- 支持checkpoint_interval配置（可恢复执行）
- 执行完成后生成Phase 1完成报告

---

**3. 创建Phase 2的Agent Skill**

**文件位置：** `skills/ut/shared/two-phase-handler/SKILL.md`

**改动内容：**
- Stage 1：统计分析逻辑（按error_type分类）
- Stage 2：Agent辅助重试逻辑（接收人工决策）
- 支持多种交互方式（terminal/feishu/yaml_config）

---

**4. 更新README.md文档**

**文件位置：** `tasks/ut/README.md`

**改动内容：**
- 新增运行策略说明
- 新增Two-phase策略使用指南
- 新增配置参数说明表

---

**5. 创建本设计文档**

**文件位置：** `tasks/ut/docs/designs/2026-07-06-two-phase-strategy-design.md`

**改动内容：**
- 完整的设计spec（本文档）
- 与Single-phase对比分析
- 实施细节和测试计划

---

## Single-phase与Two-phase对比

### 对比维度表

| 维度 | Single-phase | Two-phase |
|------|-------------|-----------|
| **核心思想** | Agent介入每个stage | Phase 1脚本批量 + Phase 2 agent智能 |
| **执行速度** | 🟡 慢（逐batch，agent等待） | 🟢 快（Phase 1批量执行） |
| **GPU利用率** | 🟡 中（agent上下文占用） | 🟢 高（无agent开销） |
| **错误处理** | 🟢 实时（Stage 4立即处理） | 🟡 延迟（Phase 2统计分析） |
| **数据完整性** | 🟢 高（实时更新manifest） | 🟡 中（需强制检查点） |
| **决策方式** | 🟢 Agent智能决策 | 🟢 人工决策（Phase 2） |
| **适用规模** | 🟡 小-中（1-200 batch） | 🟢 大（500+ batch） |
| **适用场景** | 调试、实时处理 | 快速验证、生产运行 |
| **Agent介入深度** | 🟢 深度（每个batch） | 🟡 轻度（Phase 2统计） |
| **实现复杂度** | 🟢 低（已有） | 🟡 中（需新脚本） |
| **资源消耗** | 🟡 中（agent token消耗） | 🟢 低（Phase 1无agent） |

---

### 适用场景矩阵

| 场景 | 推荐通道 | 推荐策略 | batch规模 | 原因 |
|------|---------|---------|-----------|------|
| **L1烟雾测试** | terminal-workflow | single-phase | 1 batch | 实时调试，agent介入 |
| **L2-L3测试** | terminal-workflow | single-phase | 10-50 batch | 小规模，实时处理失败 |
| **开发态快速验证** | terminal-workflow | two-phase | 100-500 batch | 快速跑完看整体状态 |
| **生产全量测试** | hermes-workflow | two-phase | 500+ batch | Phase 1快速 + Phase 2智能补充 |
| **调试复杂失败** | terminal-workflow | single-phase | 单batch | Agent深度分析根因 |
| **修复后批量重试** | hermes-workflow | two-phase | Phase 2 Stage 2 | 人工决策后agent执行 |

---

## 关键设计决策

### 设计决策记录

**决策1：Phase 2不自动重试**

**理由：**
- 避免盲目自动重试（可能浪费资源）
- 让人类经验介入决策（判断哪些batch值得重试）
- Phase 1的error_type分类为人工决策提供依据

**决策2：Phase 2分为两个Stage**

**理由：**
- Stage 1只做统计，清晰分离职责
- Stage 2接收人工决策后执行，agent资源聚焦
- 两Stage之间有明确的人工决策点

**决策3：强制检查点机制**

**理由：**
- 解决Phase 1manifest遗漏问题（已发生424个）
- 每个关键节点验证，发现问题立即停止
- 增量式更新manifest，避免一次性合并失败

**决策4：支持多种交互方式**

**理由：**
- terminal-workflow适用终端交互
- hermes-workflow适用飞书交互
- yaml配置作为fallback（无需人工介入）

---

## 测试计划

### 测试场景

**场景1：小规模测试（10 batch）**
- 使用terminal-workflow + single-phase
- 验证Stage 4实时错误处理
- 预期：实时agent介入，数据完整性高

**场景2：中规模快速验证（100 batch）**
- 使用terminal-workflow + two-phase
- Phase 1脚本批量执行
- Phase 2统计报告生成
- 预期：Phase 1速度快，manifest无遗漏

**场景3：大规模生产运行（500 batch）**
- 使用hermes-workflow + two-phase
- Phase 1脚本批量执行（飞书触发）
- Phase 2飞书交互决策
- 预期：飞书卡片展示统计，人工决策后agent重试

**场景4：恢复测试（checkpoint恢复）**
- Phase 1执行到第300 batch时人为中断
- 从checkpoint恢复继续执行
- 预期：恢复后继续执行第301-500 batch，manifest一致

---

## 风险与缓解

### 已识别风险

**风险1：Phase 1manifest遗漏**

**缓解措施：**
- ✅ 强制检查点机制（每个batch验证）
- ✅ checkpoint_interval配置（定期写入）
- ✅ 发现问题立即停止（不批量遗漏）

**风险2：Phase 1执行速度慢**

**缓解措施：**
- ✅ Phase 1无agent介入（纯脚本执行）
- ✅ GPU并行执行（无agent上下文开销）
- ✅ checkpoint_interval可配置（平衡恢复粒度）

**风险3：Phase 2人工决策延迟**

**缓解措施：**
- ✅ 支持yaml配置自动重试（无需人工介入）
- ✅ 飞书卡片实时展示统计（快速决策）
- ✅ error_type分类清晰（简化决策）

---

## 下一步实施

### 实施优先级

**P0：立即实施（本周）**
1. 创建`auto_run_batches_two_phase.py`（改进版脚本）
2. 更新workflow.yaml模板（新增配置字段）
3. 创建`two-phase-handler` Skill（Phase 2逻辑）

**P1：本周实施（7月6-12日）**
1. 更新`README.md`文档（使用指南）
2. 测试场景2-3（中规模和大规模）
3. 验证强制检查点有效性

**P2：下周实施（7月13-19日）**
1. 测试场景4（checkpoint恢复）
2. 部署到生产环境（hermes-workflow）
3. 优化Phase 2统计报告格式

---

## 总结

### 设计价值

**1. 解决实际痛点**
- 提高大批量测试效率（500+ batch）
- 避免manifest遗漏（强制检查点）
- 文档化实践策略（two-phase）

**2. 灵活组合策略**
- 通道×策略矩阵（4种组合）
- 适用不同场景（调试、验证、生产）
- 配置化参数（batch_group_size、checkpoint_interval）

**3. 平衡效率与质量**
- Phase 1速度优先（脚本批量）
- Phase 2质量优先（人工决策 + agent辅助）
- 强制检查点保证数据完整性

---

## 附录

### A. 相关文件引用

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| **manifest_schema** | `skills/ut/shared/manifest_schema.json` | Error_type枚举定义（第141行） |
| **workflow模板** | `tasks/ut/deployment/production/config/workflow.yaml` | 生产配置模板 |
| **L1-L4模板** | `tests/ut/integration/fixtures/workflow.l*.yaml` | 测试配置模板 |
| **README** | `tasks/ut/README.md` | UT Workflow入口文档 |
| **通道对比** | `tasks/ut/docs/guides/ut-channels-overview.md` | 双通道运行总览 |

### B. Error_type优先级分类

**P0（自动重试）：**
- `timeout` - pytest执行超时（retriable）
- `oom` - GPU显存不足（retriable）
- `network` - 网络错误（连接问题）

**P1（分析建议）：**
- `dependency` - 依赖缺失
- `download_error` - 模型下载失败
- `resource` - 资源不足
- `version` - 版本兼容问题

**P2（人工介入）：**
- `assertion` - 断言失败（代码问题）
- `functional` - 功能错误
- `collection` - pytest collection错误
- `other` - 未分类错误

### C. 环境信息

- **设计日期:** 2026-07-06
- **设计方法:** Superpowers Brainstorming
- **设计师:** Claude Code
- **目标版本:** workflow v2.2

### D. Single-phase Fixture配置模式

**问题：** L1/L2测试fixture使用single-phase策略，但仍需保持phase1/phase2/decision_interface配置块结构一致性。

**解决方案：** 通过配置参数巧妙禁用Phase 2处理：

```yaml
# L1/L2 fixture (single-phase strategy)
workflow:
  execution_strategy: "single-phase"

phase2:
  stage1:
    generate_report: false         # 不生成统计报告
    report_formats: []
    auto_generate_suggestions: false
  stage2:
    auto_retry_error_types: []     # 空列表 = 不重试任何error_type
    wait_for_manual_decision: false # 不等待人工决策
    retry_on_decision: false       # 不执行重试

decision_interface:
  terminal_workflow: "terminal"
  hermes_workflow: "feishu"
  fallback: "yaml_config"
```

**效果：**
- 配置结构保持一致（phase1/phase2/decision_interface都在top-level）
- Phase 2处理被有效禁用（generate_report=false + wait_for_manual_decision=false）
- L1/L2测试按single-phase策略执行，无Phase 2后处理

**适用场景：**
- 烟雾测试（L1）- 快速验证单个batch
- Linear测试（L2）- 小规模验证，无需统计分析

---

*设计文档完成时间: 2026-07-06*