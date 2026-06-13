# UT Workflow — vLLM 单元测试验证

> **总入口** — 所有 UT 相关文档、脚本、数据、Skills 的导航中心

---

## ⚠️ 必读文档

如果你是第一次接触 UT Workflow，请按顺序阅读：

| 顺序 | 文档 | 说明 |
|:----:|------|------|
| 1 | **[GOAL.md](GOAL.md)** | 测试目标、范围、完成标准 — 先搞清楚要做什么 |
| 2 | **[docs/guides/testing.md](docs/guides/testing.md)** | 测试执行指南 — 环境架构、连接方式、pytest 命令 |
| 3 | **[skills/ut/workflow/SKILL.md](../../skills/ut/workflow/SKILL.md)** | Workflow 调度器 — 5 阶段流水线的完整执行逻辑 |
| 4 | **[skills/ut/shared/filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml)** | 过滤规则 — 哪些测试被排除、为什么 |
| 5 | **[PROGRESS.md](PROGRESS.md)** | 实时进度 — 当前执行到哪了 |

> 其他文档按需查阅，下方导航表可快速定位。

---

## 📝 文档更新原则

| 文件 | 定位 | 内容 |
|------|------|------|
| PROGRESS.md | 高层视图 | 里程碑、版本摘要 |
| WORKLOG.md | 日志入口 | 日期/任务索引 |
| worklog/ | 详细日志 | 完整操作记录 |

**更新流程**: 完成工作 → worklog/<date>/<task>.md → WORKLOG.md 索引 → PROGRESS.md 摘要

---

## 目录结构

```
tasks/ut/
├── README.md                  ← 本文件（总入口）
├── GOAL.md                    ← 测试目标、范围、完成标准
├── PROGRESS.md                ← 实时进度统计（20.12%, 6,411/31,868）
├── WORKLOG.md                 ← 每日工作日志
├── todo.md                    ← 待办事项 & 设计决策记录
├── workflow-template.yaml     ← Workflow 配置模板（供复制使用）
├── manifest-template.json     ← Manifest 数据模板
│
├── docs/                      ← 文档中心
│   ├── README.md              ←   文档导航
│   ├── 单元测试流程规范_v2.md  ←   完整流程规范（295行）
│   ├── guides/                ←   操作指南
│   │   ├── testing.md         ←     测试执行指南（环境、命令、过滤）
│   │   ├── manual_operations.md ←   手动操作参考
│   │   └── error-stats-guide.md ←  错误统计指南
│   ├── reports/               ←   测试报告
│   │   ├── test-summary.md    ←     测试结果汇总
│   │   ├── weekly/            ←     周报（5个文件）
│   │   └── compatibility/     ←     兼容性分析（4个文件）
│   └── discussions/           ←   架构讨论
│       └── 2026-06-09-about_agents_architecture_and_workflow_design.md
│
├── scripts/                   ← 模型下载 & 环境配置
│   ├── README.md              ←   下载指南（44个模型，5个级别）
│   ├── hf_env.sh              ←   HuggingFace 离线环境
│   └── modelscope_env.sh      ←   ModelScope 环境
│
├── patches/                   ← PyTorch 2.5.1 兼容补丁
│   ├── README.md              ←   补丁说明（3类问题 + 8个文件修改）
│   ├── torch_compat.py        ←   auto_functionalized 兼容层
│   ├── fix_lora_types.py      ←   LoRA 类型签名修复
│   ├── fix_gpu_worker.py      ←   GPU Worker 修复
│   ├── wrap_triton_shim.py    ←   Triton shim
│   ├── *.patch / *.sh         ←   patch 文件 & 应用脚本
│   └── fp32_precision.patch
│
├── test_analysis/             ← 测试数据分析
│   ├── README.md              ←   目录说明（数据来源、合并逻辑）
│   ├── manifest.json          ←   ★ 核心状态文件（31,868条）
│   ├── manifest_legacy.json   ←   旧版备份
│   ├── test_list.txt          ←   统一测试清单（17,391条）
│   └── remote_log_summary/    ←   远程日志摘要
│       ├── README.md
│       ├── passed_ut_cases-20260606.txt
│       ├── failed_ut_cases-20260606.txt
│       └── error_ut_cases-20260606.txt
│
└── workflow_tests/            ← Workflow 集成测试
    ├── verify_workflow_test.py ←   验证脚本
    ├── test_list_passed.txt
    ├── test_list_failed.txt
    ├── test_list_error.txt
    └── test_list_combined.txt
```

---

## 快速导航

| 我想... | 看这里 |
|---------|--------|
| 了解测试目标与完成标准 | [GOAL.md](GOAL.md) |
| 查看当前进度统计 | [PROGRESS.md](PROGRESS.md) |
| 查看每日工作记录 | [WORKLOG.md](WORKLOG.md) |
| 了解待办事项 & 设计决策 | [todo.md](todo.md) |
| 执行测试（环境/命令/过滤） | [docs/guides/testing.md](docs/guides/testing.md) |
| 了解完整流程规范 | [docs/单元测试流程规范_v2.md](docs/单元测试流程规范_v2.md) |
| 手动处理收集错误 | [docs/guides/manual_operations.md](docs/guides/manual_operations.md) |
| 统计 & 分类测试错误 | [docs/guides/error-stats-guide.md](docs/guides/error-stats-guide.md) |
| 下载测试所需模型 | [scripts/README.md](scripts/README.md) |
| 应用 PyTorch 兼容补丁 | [patches/README.md](patches/README.md) |
| 查看测试数据 & 合并逻辑 | [test_analysis/README.md](test_analysis/README.md) |
| 查看远程日志摘要 | [test_analysis/remote_log_summary/README.md](test_analysis/remote_log_summary/README.md) |
| 查看测试结果报告 | [docs/reports/test-summary.md](docs/reports/test-summary.md) |
| 查看兼容性分析 | [docs/reports/compatibility/](docs/reports/compatibility/) |
| 查看历史周报 | [docs/reports/weekly/](docs/reports/weekly/) |
| 了解架构设计讨论 | [docs/discussions/](docs/discussions/) |
| 运行 Workflow 集成测试 | [workflow_tests/verify_workflow_test.py](workflow_tests/verify_workflow_test.py) |
| 浏览文档中心 | [docs/README.md](docs/README.md) |

---

## Workflow 架构

### 双模式运行

Workflow 支持两种运行模式，由 `workflow.yaml` 的 `kanban.enabled` 控制：

| 模式 | 配置 | 执行方式 |
|------|------|----------|
| **线性模式** | `kanban.enabled: false` | 单 Agent 循环执行 Stage 2-5 |
| **Kanban 模式** | `kanban.enabled: true` | Gateway 调度 + 3 Worker Agent 协作 |

### 线性模式流程（kanban.enabled: false）

5 阶段流水线：

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    ┌────────────────┐
│ Stage 1      │    │ Stage 2      │    │ Stage 3          │    │ Stage 4      │    │ Stage 5        │
│ collect      │ →  │ select_batch │ →  │ execute           │ →  │ handle_      │ →  │ update_status  │
│ (一次性)      │    │ (循环)        │    │ (循环, 远程pytest) │    │ failures     │    │ (循环)          │
└──────────────┘    └──────────────┘    └──────────────────┘    └──────────────┘    └────────────────┘
       ↑                                                                                  │
       └─────────────────── 循环 Stage 2-5 直到 pending_count == 0 ───────────────────────┘
```

### Kanban 模式流程（kanban.enabled: true）

Agent 自动启动 Gateway + 3 Worker：

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Gateway Process (持续运行)                               │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐│
│  │                          Dispatcher (60s tick)                                  ││
│  │                                                                                 ││
│  │  1. Query ready tasks from kanban.db                                           ││
│  │  2. Claim task via CAS (atomic lock)                                           ││
│  │  3. Spawn worker subprocess                                                    ││
│  │     - Load profile SOUL.md                                                     ││
│  │     - Read task body                                                           ││
│  │     - Execute LLM inference                                                    ││
│  │     - Call kanban_complete()                                                   ││
│  │  4. Update task status                                                         ││
│  └────────────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────┘
         │                           │                           │
         v                           v                           v
    ut-orchestrator              ut-executor                 ut-fixer
   (创建 batch 任务)            (执行 pytest)               (修复失败测试)
         │                           │                           │
         └───→ dependency ───────────┴───→ dependency ───────────┘
```

### Kanban 启动步骤

1. Agent 检查 `workflow.yaml kanban.enabled = true`
2. 执行 `start_gateway.py` 启动 3 个 Gateway
3. 创建初始 Orchestrator 任务
4. 执行 `monitor_kanban.py` 监控进度
5. 完成后发送飞书通知

| Stage | Skill | 执行方式 | 说明 |
|:-----:|-------|:--------:|------|
| 1 | `ut-test-collector` | 一次性 | 收集 vLLM 测试列表 → manifest.json |
| 2 | `batch-selector` | 循环 | 从 manifest 选择下一批次（batch_size ≤ 50） |
| 3 | `unit-test-executor` | 循环 | SSH 远程执行 pytest，解析日志 → batch_results.json |
| 4 | `failure-handler` | 循环 | 分析失败原因，分类（C/E/D/P/M/S），尝试修复 |
| 5 | `manifest-updater` | 循环 | 更新 manifest.json 状态，重算 statistics |

### Skills 位置

| Skill | SKILL.md | 脚本目录 |
|-------|----------|----------|
| workflow (调度器) | [skills/ut/workflow/SKILL.md](../../skills/ut/workflow/SKILL.md) | [skills/ut/workflow/scripts/](../../skills/ut/workflow/scripts/) |
| ut-test-collector | [skills/ut/ut-test-collector/SKILL.md](../../skills/ut/ut-test-collector/SKILL.md) | [skills/ut/ut-test-collector/scripts/](../../skills/ut/ut-test-collector/scripts/) |
| batch-selector | [skills/ut/batch-selector/SKILL.md](../../skills/ut/batch-selector/SKILL.md) | [skills/ut/batch-selector/scripts/](../../skills/ut/batch-selector/scripts/) |
| unit-test-executor | [skills/ut/unit-test-executor/SKILL.md](../../skills/ut/unit-test-executor/SKILL.md) | [skills/ut/unit-test-executor/scripts/](../../skills/ut/unit-test-executor/scripts/) |
| failure-handler | [skills/ut/failure-handler/SKILL.md](../../skills/ut/failure-handler/SKILL.md) | [skills/ut/failure-handler/scripts/](../../skills/ut/failure-handler/scripts/) |
| manifest-updater | [skills/ut/manifest-updater/SKILL.md](../../skills/ut/manifest-updater/SKILL.md) | [skills/ut/manifest-updater/scripts/](../../skills/ut/manifest-updater/scripts/) |

---

## 关键数据文件

| 文件 | 位置 | 说明 | 更新时机 |
|------|------|------|----------|
| **manifest.json** | `test_analysis/manifest.json` | 31,868 条测试状态（核心） | Stage 5 每次循环 |
| **workflow.yaml** | `.agents/workflow.yaml` | 运行时 Workflow 配置 | 手动调整 |
| **workflow_state.json** | `.agents/workflow_state.json` | Workflow 运行状态 | 初始化 + 每次循环 |
| **batch_config.json** | `.agents/batch_config.json` | 当前批次配置 | Stage 2 每次循环 |
| **batch_results.json** | `.agents/batch_results.json` | 批次执行结果 | Stage 3 每次循环 |
| **handled_tests.json** | `.agents/handled_tests.json` | 失败处理结果 | Stage 4 每次循环 |

### 数据流

```
manifest.json ──→ batch_config.json ──→ pytest (远程) ──→ batch_results.json
                                                                    │
                                                                    ▼
manifest.json ←── manifest-updater ←── handled_tests.json ←── failure-handler
```

---

## 共享基础设施

| 资源 | 路径 | 说明 |
|------|------|------|
| 过滤规则（单一来源） | [skills/ut/shared/filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml) | 41条规则，定义排除/包含的测试 |
| 过滤规则加载器 | [skills/ut/shared/load_filter_rules.py](../../skills/ut/shared/load_filter_rules.py) | Python API 读取规则 |
| Schema 校验器 | [skills/ut/shared/validate_schema.py](../../skills/ut/shared/validate_schema.py) | 通用 JSON/YAML schema 校验 |
| Manifest Schema | [skills/ut/shared/manifest_schema.json](../../skills/ut/shared/manifest_schema.json) | manifest.json 结构定义 |
| Manifest 迁移 | [skills/ut/shared/migrate_manifest.py](../../skills/ut/shared/migrate_manifest.py) | 旧版 manifest 迁移 |
| 配置加载器 | [skills/ut/shared/config_loader.py](../../skills/ut/shared/config_loader.py) | YAML 配置加载 |

---

## 快速开始

### 1. 配置

复制模板并修改路径：

```bash
cp tasks/ut/workflow-template.yaml .agents/workflow.yaml
# 编辑 .agents/workflow.yaml，修改 workspace、remote_server 等
```

### 2. 启动 Workflow

加载 skill 后按提示操作：

```
加载 ut/workflow skill
```

Skill 会自动：
1. 提示指定 workflow.yaml 路径
2. 检查前置条件（Bastion 连接、文件存在）
3. 初始化 workflow_state.json
4. 进入 Stage 1-5 循环执行

### 3. 手动执行单个测试

```bash
# 通过 agent.py 远程执行
python tools/agent.py -p t_h20 run --timeout 300 \
  "sudo docker exec v0.13.0_torch2.5.1_ut bash -c 'cd /gpfs/gcsp/M2.7_verify/vllm && pytest -vv tests/test_seed_behavior.py'"
```

---

## 测试环境

| 项目 | 详情 |
|------|------|
| 服务器 | t_h20 (10.10.154.13)，通过 Bastion (10.10.192.55) 连接 |
| 容器 | `v0.13.0_torch2.5.1_ut` (vLLM v0.13.0 + PyTorch 2.5.1 + CUDA 12.4) |
| GPU | NVIDIA H20-3e × 8，143GB 显存/卡 |
| 共享存储 | `/gpfs/gcsp/M2.7_verify/` (1.9PB) |
| vLLM 源码 | `/gpfs/gcsp/M2.7_verify/vllm/` |
| 测试日志 | `/gpfs/gcsp/M2.7_verify/vllm/ut_logs/` |

详见 [docs/guides/testing.md](docs/guides/testing.md) 和 [AGENTS.md](../../AGENTS.md)。

---

## 问题分类体系

| 类别 | 说明 | 示例 |
|------|------|------|
| **C-代码Bug** | vLLM 源码缺陷 | 类型签名错误、逻辑错误 |
| **E-环境问题** | 测试环境限制 | HF 离线、磁盘配额、GPU 内存 |
| **D-依赖缺失** | Python 包缺失 | mteb, multiprocess, grpc |
| **P-平台兼容** | PyTorch API 缺失 | fp32_precision, wrap_triton |
| **M-模型缺失** | HuggingFace 模型未下载 | Llama, Snowflake 等 |
| **S-跳过问题** | 合理跳过的测试 | 平台不支持、功能未启用 |

---

## 相关文档

### 项目层
- [AGENTS.md](../../AGENTS.md) — Agent 工作指南（环境、路径映射、命令）
- [README.md](../../README.md) — 项目总览
- [PROGRESS.md](../../PROGRESS.md) — 项目总体进度

### 任务层
- [GOAL.md](GOAL.md) — 测试目标与完成标准
- [PROGRESS.md](PROGRESS.md) — 实时进度统计
- [WORKLOG.md](WORKLOG.md) — 每日工作日志
- [todo.md](todo.md) — 待办事项

### 配置 & Skills
- [.agents/workflow.yaml](../../.agents/workflow.yaml) — 运行时 Workflow 配置
- [skills/ut/workflow/SKILL.md](../../skills/ut/workflow/SKILL.md) — Workflow 调度器（v5.0）
- [skills/ut/shared/filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml) — 过滤规则（41条）

---

*最后更新: 2026-06-12*
