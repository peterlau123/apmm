# UT Skills & Profiles Reorganization Design

**日期**: 2026-06-25
**作者**: liux + Claude
**目的**: 结构化 UT skills 和 profiles，职责清晰，修改一处生效

---

## 1. 问题分析

### 1.1 当前问题

**职责边界混乱**：
- Worker SOUL.md 既在 skill 目录，又在 fixtures/profiles 目录
- 修改一处需要改动多处

**目录结构不清晰**：
- 一眼看不出职责边界
- Supervisor 和 Worker 的 skills 组织混乱

**Skills 加载逻辑复杂**：
- Linear/Kanban 模式加载逻辑不清晰
- Troubleshooting 信息可能丢失

---

## 2. 设计原则

### 2.1 职责分离

**Supervisor（监控者）**：
- 飞书订阅（唯一订阅者）
- 状态机管理（running/paused/waiting_otp/completed/stopped/failed）
- Bastion OTP recovery
- 创建第一个 Kanban task
- 监控进度（Gateway alive + stats poll）
- 发飞书通知

**Worker（执行者）**：
- 执行具体 Stage（Stage2-5）
- 创建 Kanban 依赖链（Orchestrator Worker）
- 更新 manifest
- 不发飞书通知（Supervisor 负责）

---

### 2.2 Skills 加载模式差异

**Linear mode**：
- Supervisor 加载所有 Worker skills
- 目的：理解 Stage 执行细节 + troubleshooting 信息
- 完整上下文支持推理和决策

**Kanban mode**：
- Supervisor 只加载 supervisor + loop_core + shared
- Worker 各自加载专有 skill
- 目的：职责分离 + 上下文精简

---

### 2.3 单一位置定义

**SOUL.md + SKILL.md 在同一 skill 目录**：
- 修改一处生效
- Profile 配置单独管理
- deploy_tier.py 部署时合并

---

## 3. Skills 目录结构

### 3.1 最终结构

```
skills/ut/
│
├── simple-workflow/  ← 线性通道（终端 Agent 用）
│   ├── SKILL.md  ← 线性流程总控 + troubleshooting
│   ├── scripts/
│   │   └── run_linear.py  ← 启动脚本
│   └── references/
│
├── hermes-workflow/  ← Hermes 通道总控（合并 supervisor + orchestrator 调度）
│   ├── SKILL.md  ← 飞书 + Bastion + 状态机 + Kanban task 创建 + 监控
│   ├── SOUL.md  ← ut-supervisor 身份定义
│   ├── profile.yaml  ← Supervisor profile 配置
│   ├── scripts/
│   │   ├── bastion_manager.py
│   │   ├── feishu_handler.py
│   │   ├── state_machine.py
│   │   ├── kanban_task_creator.py  ← 创建 Kanban task + 依赖链
│   │   └── orchestrator_round.py  ← 调度逻辑
│   │   └── hermes_runner.py
│   └── references/
│       ├── otp-recovery.md
│       ├── state-machine.md
│       ├── feishu-integration.md
│       └── kanban-dependencies.md
│
├── batch-selector/  ← Stage2 Worker
│   ├── SKILL.md  ← Stage2 执行细节 + troubleshooting
│   ├── SOUL.md  ← ut-batch-selector 身份定义
│   ├── scripts/
│   │   └── generate_batch.py
│   └── references/
│
├── executor/  ← Stage3 Worker
│   ├── SKILL.md  ← Stage3 执行细节 + troubleshooting
│   ├── SOUL.md  ← ut-executor 身份定义
│   ├── scripts/
│   │   ├── execute_batch.py
│   │   └── parse_remote_log.py
│   └── references/
│       ├── watchdog-timeout.md
│       └── remote-execution.md
│
├── fixer/  ← Stage4 Worker（合并 failure-handler + dependency-resolver）
│   ├── SKILL.md  ← Stage4 执行细节 + troubleshooting + dependency 处理
│   ├── SOUL.md  ← ut-fixer 身份定义
│   ├── scripts/
│   │   ├── analyze_failures.py
│   │   ├── generate_handled_manifest.py
│   │   └── resolve_dependencies.py  ← 合并 dependency-resolver 功能
│   └── references/
│       ├── error-type-classification.md
│       └── dependency-resolution.md
│
├── manifest-updater/  ← Stage5 Worker
│   ├── SKILL.md  ← Stage5 执行细节 + troubleshooting
│   ├── SOUL.md  ← ut-manifest-updater 身份定义
│   ├── scripts/
│   │   ├── update_manifest.py
│   │   └── update_status.py
│   └── references/
│
├── unit-test-collector/  ← Stage1 Worker（新增）
│   ├── SKILL.md  ← Stage1: 收集测试 + troubleshooting
│   ├── scripts/
│   │   └── collect_tests.py  ← 从 test_list.txt 生成 manifest
│   └── references/
│
├── workflow_loop_core/  ← 共享引擎
│   ├── SKILL.md  ← 5 阶段流水线逻辑
│   ├── scripts/
│   │   └── loop_core.py
│
└── shared/  ← 共享 schemas + utils
    ├── schemas/
    │   ├── manifest_schema.json
    │   ├── batch_results_schema.json
    │   └── handled_tests_schema.json
    └── scripts/
        └── validate_schema.py
```

---

## 4. Skills 加载矩阵

| 模式 | Profile | 加载的 Skills | 原因 |
|---|---|---|---|
| **simple-workflow 线性** | 终端 Agent | simple-workflow + loop_core + unit-test-collector + batch-selector + executor + fixer + manifest-updater + shared | 不需要 hermes-workflow（无 Hermes） |
| **hermes 线性** | ut-supervisor | hermes-workflow + loop_core + unit-test-collector + batch-selector + executor + fixer + manifest-updater + shared | 完整上下文 + troubleshooting |
| **hermes kanban** | ut-supervisor | hermes-workflow + loop_core + shared | 只监控 + 创建依赖链，不执行 Stage |
| **hermes kanban** | ut-batch-selector | batch-selector + loop_core + shared | 只负责 Stage2 |
| **hermes kanban** | ut-executor | executor + loop_core + shared | 只负责 Stage3 |
| **hermes kanban** | ut-fixer | fixer + loop_core + shared | 只负责 Stage4（含 dependency resolution） |
| **hermes kanban** | ut-manifest-updater | manifest-updater + loop_core + shared | 只负责 Stage5 |

---

## 5. Kanban 调度流程

### 5.1 任务依赖链

```
Supervisor → 创建第一个 batch-selector task
batch-selector → 创建 executor → fixer → manifest-updater → next batch-selector
循环直到 batch-selector 返回空 → Supervisor 发飞书完成卡片
```

### 5.2 调度逻辑

**Supervisor 创建完整依赖链**：
- 创建 batch-selector task（启动流程）
- 创建 executor task [parents=batch-selector]
- 创建 fixer task [parents=executor]
- 创建 manifest-updater task [parents=fixer]
- 创建 next batch-selector task [parents=manifest-updater]
- 若 batch-selector 返回空 → 不创建 next → 循环终止

**设计优势**：
1. Supervisor 有完整控制权（可调整依赖链）
2. batch-selector 不需要知道后续依赖关系
3. 职责清晰：Supervisor 调度者，batch-selector 执行者

---

## 6. Profile 配置

### 6.1 Profile 数量

**总共 6 个 profiles**：
- ut-supervisor（Supervisor）
- ut-unit-test-collector（Stage1 Worker）
- ut-batch-selector（Stage2 Worker）
- ut-executor（Stage3 Worker）
- ut-fixer（Stage4 Worker，含 dependency resolution）
- ut-manifest-updater（Stage5 Worker）

### 6.2 Profile 配置示例

**ut-supervisor profile.yaml**：
```yaml
description: 'UT Workflow supervisor: Feishu + Bastion + Kanban task creation + monitoring'

x-deploy:
  auto_load_skills:
    - ut/hermes-workflow
    - ut/workflow_loop_core
    - ut/unit-test-collector  # Linear mode 需要
    - ut/batch-selector       # Linear mode 需要
    - ut/executor             # Linear mode 需要
    - ut/fixer                # Linear mode 需要
    - ut/manifest-updater     # Linear mode 需要
    - ut/shared
```

### 7.1 Phase 1：Skills 目录重组

1. 重命名 skills：
   - workflow → simple-workflow
   - supervisor → hermes-workflow（已改名）
   - ut-test-collector → unit-test-collector
2. 合并 dependency-resolver 到 fixer skill
3. 每个 Worker skill 添加 SOUL.md
4. 每个 Worker skill 添加 troubleshooting references

### 7.2 Phase 2：Profile 配置调整

1. 创建 ut-unit-test-collector profile（Stage1）
2. 创建 ut-batch-selector profile（Stage2）
3. 创建 ut-manifest-updater profile（Stage5）
4. 更新 profile.yaml（6 个 profiles）

### 7.3 Phase 3：脚本调整

1. supervisor/scripts/ 添加 kanban_task_creator.py
2. supervisor/scripts/ 添加 orchestrator_round.py

### 7.4 Phase 4：测试验证

1. 测试 Linear mode（L1-L3）
2. 测试 Kanban mode（L4）

---

## 8. 总结

### 8.1 关键改进

1. **职责清晰**：Supervisor（hermes-workflow skill）创建依赖链 + 监控，Worker 执行
2. **Skills 重命名**：simple-workflow / hermes-workflow / unit-test-collector（已完成改名）
3. **Dependency 合并**：dependency-resolver 合并到 fixer（简化 skills）
4. **加载模式差异**：Linear 完整上下文 + Kanban 职责分离
5. **Troubleshooting 保留**：每个 Worker SKILL.md 包含 troubleshooting
6. **修改一处生效**：SOUL.md + SKILL.md 在同一目录
7. **Profile 明确**：6 个 profiles（Supervisor + 5 Workers）

---

**下一步**: invoke writing-plans skill 创建实施计划