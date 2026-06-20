# UT Workflow — vLLM 单元测试验证

> **总入口** — 所有 UT 相关文档、脚本、数据、Skills 的导航中心。
> 本文件只做**导引**；具体操作、配置、架构细节见各自的权威文档（下方均有链接）。

## 目录

- [必读文档](#必读文档)
- [快速导航](#快速导航)
- [目录结构](#目录结构)
- [Workflow 架构](#workflow-架构)
- [关键数据文件](#关键数据文件)
- [共享基础设施](#共享基础设施)
- [快速开始](#快速开始)
- [测试环境](#测试环境)
- [问题分类体系](#问题分类体系)
- [飞书通知](#飞书通知)
- [文档维护约定](#文档维护约定)
- [相关文档](#相关文档)

---

## 必读文档

第一次接触 UT Workflow，按顺序读这 5 篇即可上手：

| 顺序 | 文档 | 说明 |
|:----:|------|------|
| 1 | **[GOAL.md](GOAL.md)** | 测试目标、范围、完成标准 — 先搞清楚要做什么 |
| 2 | **[docs/guides/testing.md](docs/guides/testing.md)** | 测试执行指南 — 环境架构、连接方式、pytest 命令 |
| 3 | **[skills/ut/workflow/SKILL.md](../../skills/ut/workflow/SKILL.md)** | Workflow 调度器 — 5 阶段流水线的完整执行逻辑 |
| 4 | **[skills/ut/shared/filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml)** | 过滤规则 — 哪些测试被排除、为什么 |
| 5 | **[PROGRESS.md](PROGRESS.md)** | 实时进度 — 当前执行到哪了 |

> 其余文档按需查阅，用下方[快速导航](#快速导航)定位。

---

## 快速导航

> 本表是**唯一的随机访问入口**——找文档先看这里。

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
| 查看兼容性分析 / 历史周报 | [docs/reports/compatibility/](docs/reports/compatibility/) · [docs/reports/weekly/](docs/reports/weekly/) |
| 了解架构设计讨论 | [docs/discussions/](docs/discussions/) |
| 运行 Workflow 集成测试 | [workflow_tests/verify_workflow_test.py](workflow_tests/verify_workflow_test.py) |
| 了解 Hermes Runner 操作 | [docs/guides/hermes-runner.md](docs/guides/hermes-runner.md) |
| 部署 ut-supervisor 服务 | [../../docs/guides/hermes-supervisor-service.md](../../docs/guides/hermes-supervisor-service.md) |
| 部署 3 个 Gateway 服务 | [../../docs/guides/hermes-gateway-service.md](../../docs/guides/hermes-gateway-service.md) |
| Kanban 模式完整配置 | [docs/kanban/README.md](docs/kanban/README.md) |
| 飞书通知集成细节 | [skills/ut/workflow/references/feishu-integration.md](../../skills/ut/workflow/references/feishu-integration.md) |
| 浏览文档中心 | [docs/README.md](docs/README.md) |

---

## 目录结构

```
tasks/ut/
├── README.md          ← 本文件（总入口）
├── GOAL.md            ← 测试目标、范围、完成标准
├── PROGRESS.md        ← 实时进度统计（数字以此为准）
├── WORKLOG.md         ← 每日工作日志索引
├── todo.md            ← 待办事项 & 设计决策记录
│
├── docs/              ← 文档中心（README.md 为导航）
│   ├── 单元测试流程规范_v2.md   ← 完整流程规范
│   ├── guides/        ←   操作指南（testing / manual_operations / error-stats / hermes-runner）
│   ├── kanban/        ←   Kanban 模式配置指南
│   ├── reports/       ←   测试报告（test-summary / weekly / compatibility）
│   └── discussions/   ←   架构讨论
│
├── scripts/           ← 模型下载 & 环境配置（README.md 为下载指南）
├── patches/           ← PyTorch 2.5.1 兼容补丁（README.md 为补丁说明）
│
├── test_analysis/     ← 测试数据分析
│   ├── README.md      ←   数据来源、合并逻辑
│   ├── manifest.json  ←   ★ 核心状态文件
│   ├── test_list.txt  ←   统一测试清单
│   └── remote_log_summary/   ← 远程日志摘要
│
└── workflow_tests/    ← Workflow 集成测试（verify_workflow_test.py）
```

> Manifest 结构示例见 [skills/ut/shared/manifest_example.json](../../skills/ut/shared/manifest_example.json)；
> 结构定义见 [skills/ut/shared/manifest_schema.json](../../skills/ut/shared/manifest_schema.json)。

---

## Workflow 架构

### 双模式运行

由 `workflow.yaml` 的 `kanban.enabled` 控制：

| 模式 | 配置 | 执行方式 |
|------|------|----------|
| **线性模式** | `kanban.enabled: false` | 单 Agent 进程内循环 Stage 2–5 |
| **Kanban 模式** | `kanban.enabled: true` | Gateway 调度 + 3 Worker Agent（orchestrator/executor/fixer）协作 |

> 长期运行推荐用 `hermes_runner.py`，它按 `kanban.enabled` 自动选择模式，并共享 Bastion 心跳/OTP 恢复与飞书通知。
> 启动逻辑细节见 [docs/guides/hermes-runner.md](docs/guides/hermes-runner.md)；Kanban 完整配置见 [docs/kanban/README.md](docs/kanban/README.md)。

### 5 阶段流水线

```
Stage 1 collect → Stage 2 select_batch → Stage 3 execute → Stage 4 handle_failures → Stage 5 update_status
   (一次性)            (循环)               (循环, 远程pytest)      (循环)                  (循环)
                         └──────── 循环 Stage 2–5 直到 pending_count == 0 ────────┘
```

| Stage | Skill | 执行方式 | 说明 |
|:-----:|-------|:--------:|------|
| 1 | `ut-test-collector` | 一次性 | 收集 vLLM 测试列表 → manifest.json |
| 2 | `batch-selector` | 循环 | 从 manifest 选下一批次（batch_size ≤ 100） |
| 3 | `unit-test-executor` | 循环 | SSH 远程执行 pytest，解析日志 → batch_results.json |
| 4 | `failure-handler` | 循环 | 分析失败原因，分类、尝试修复 → handled_tests.json |
| 5 | `manifest-updater` | 循环 | 更新 manifest 状态，重算 statistics |

### 循环控制

| 条件 | 阈值 | 动作 | 通知 |
|------|------|:----:|:----:|
| 完成 | `pending_count == 0` | ✅ 停止 | 🟩 绿色卡片 |
| 连续失败 | `consecutive_failures > 50` | ⏸️ 暂停 | 🟨 黄色告警 |
| 高错误率 | `error_rate > 80%` | ⏸️ 暂停 | 🟨 黄色告警 |
| 中等错误率 | `error_rate > 30%` | ⚠️ 告警 | 🟥 红色告警 |

> 恢复暂停：把 `config.resume_from` 设为已有 run_dir 路径。阈值定义见 `workflow.yaml` 的 `loop` 段。

### Skills 位置

| Skill / 模块 | 入口 | 说明 |
|------|------|------|
| workflow（线性调度器） | [SKILL.md](../../skills/ut/workflow/SKILL.md) · [scripts/](../../skills/ut/workflow/scripts/) | OpenCode/Claude Code 线性通道 |
| hermes_workflow（Supervisor） | [SKILL.md](../../skills/ut/hermes_workflow/SKILL.md) | Hermes 通道 ut-supervisor 监督者 |
| hermes_runner | [hermes_runner.py](../../skills/ut/workflow/scripts/hermes_runner.py) | 双模式长期运行主体 |
| bastion_manager | [bastion_manager.py](../../skills/ut/workflow/scripts/bastion_manager.py) | Bastion daemon 生命周期 + OTP |
| ut-test-collector | [SKILL.md](../../skills/ut/ut-test-collector/SKILL.md) | Stage 1 |
| batch-selector | [SKILL.md](../../skills/ut/batch-selector/SKILL.md) | Stage 2 |
| unit-test-executor | [SKILL.md](../../skills/ut/unit-test-executor/SKILL.md) | Stage 3 |
| failure-handler | [SKILL.md](../../skills/ut/failure-handler/SKILL.md) | Stage 4 |
| manifest-updater | [SKILL.md](../../skills/ut/manifest-updater/SKILL.md) | Stage 5 |

---

## 关键数据文件

| 文件 | 位置 | 说明 | 更新时机 |
|------|------|------|----------|
| **manifest.json** | `test_analysis/manifest.json` | 测试状态核心文件 | Stage 5 每次循环 |
| **workflow.yaml** | `.agents/workflow.yaml` | 运行时配置 | 手动调整 |
| **workflow_state.json** | `.agents/workflow_state.json` | 运行状态 | 初始化 + 每次循环 |
| **batch_config.json** | `.agents/batch_config.json` | 当前批次配置 | Stage 2 每次循环 |
| **batch_results.json** | `.agents/batch_results.json` | 批次执行结果 | Stage 3 每次循环 |
| **handled_tests.json** | `.agents/handled_tests.json` | 失败处理结果 | Stage 4 每次循环 |

```
manifest.json → batch_config.json → pytest(远程) → batch_results.json
      ↑                                                    │
manifest-updater ←──── handled_tests.json ←──── failure-handler
```

---

## 共享基础设施

| 资源 | 路径 | 说明 |
|------|------|------|
| 过滤规则（单一来源） | [filter_rules.yaml](../../skills/ut/shared/filter_rules.yaml) | 定义排除/包含的测试 |
| 过滤规则加载器 | [load_filter_rules.py](../../skills/ut/shared/load_filter_rules.py) | Python API |
| Schema 校验器 | [validate_schema.py](../../skills/ut/shared/validate_schema.py) | 通用 JSON/YAML 校验 |
| Manifest Schema | [manifest_schema.json](../../skills/ut/shared/manifest_schema.json) | manifest.json 结构定义 |
| Manifest 迁移/回填 | [migrate_manifest.py](../../skills/ut/shared/migrate_manifest.py) | 旧版迁移 + v5 字段回填 |
| 配置加载器 | [config_loader.py](../../skills/ut/shared/config_loader.py) | YAML 配置加载 |

---

## 快速开始

1. **配置** — 编辑 `.agents/workflow.yaml`，按文件头部的 *Quick Config Guide* 注释填写必填参数
   （`input_filter.test_list_path` / `manifest_source`、`config.remote_server`、`config.docker_container`、
   `config.batch_size`、`config.resume_from`）。
2. **验证前置** —
   ```bash
   python tools/agent.py -p t_h20 ping        # Bastion 连接
   grep test_list_path .agents/workflow.yaml  # 清单路径存在
   ```
3. **启动** — 在会话中加载 skill：`加载 ut/workflow skill`。Skill 会自动提示路径、检查前置条件、
   初始化 `workflow_state.json`，然后进入 Stage 1–5 循环。

> 单独跑一个测试：
> ```bash
> python tools/agent.py -p t_h20 run --timeout 300 \
>   "sudo docker exec v0.13.0_torch2.5.1_compile bash -c 'cd /gpfs/gcsp/M2.7_verify/vllm && pytest -vv <test_node>'"
> ```

---

## 测试环境

| 项目 | 详情 |
|------|------|
| 服务器 | t_h20 (10.10.154.13)，经 Bastion (10.10.192.55) 连接 |
| 容器 | `v0.13.0_torch2.5.1_compile` (vLLM v0.13.0 + PyTorch 2.5.1 + CUDA 12.4) |
| GPU | NVIDIA H20-3e × 8，143GB 显存/卡 |
| 共享存储 | `/gpfs/gcsp/M2.7_verify/` (1.9PB)；vLLM 源码 `…/vllm/`；日志 `…/vllm/ut_logs/` |

详见 [docs/guides/testing.md](docs/guides/testing.md) 和 [AGENTS.md](../../AGENTS.md)。

---

## 问题分类体系

人工归因标签（用于报告/周报的人读分类）：

| 类别 | 说明 | 示例 |
|------|------|------|
| **C-代码Bug** | vLLM 源码缺陷 | 类型签名错误、逻辑错误 |
| **E-环境问题** | 测试环境限制 | HF 离线、磁盘配额、GPU 内存 |
| **D-依赖缺失** | Python 包缺失 | mteb, multiprocess, grpc |
| **P-平台兼容** | PyTorch API 缺失 | fp32_precision, wrap_triton |
| **M-模型缺失** | HuggingFace 模型未下载 | Llama, Snowflake 等 |
| **S-跳过问题** | 合理跳过的测试 | 平台不支持、功能未启用 |

> 这是**人读**的归因体系；manifest 里机器可读的 `error_type` 枚举（`dependency`/`network`/`download_error`…）
> 以 [manifest_schema.json](../../skills/ut/shared/manifest_schema.json) 为准。

---

## 飞书通知

Workflow 通过飞书 webhook 推送进度卡片。配置 `.agents/feishu_config.json`：

```json
{ "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/<YOUR_WEBHOOK_ID>", "chat_id": "oc_xxx" }
```

获取 webhook、卡片样式与字段细节见 [skills/ut/workflow/references/feishu-integration.md](../../skills/ut/workflow/references/feishu-integration.md)。
验证：`python skills/ut/workflow/scripts/send_progress_card.py --manifest-path tasks/ut/test_analysis/manifest.json --feishu-config .agents/feishu_config.json --event test`

---

## 文档维护约定

| 文件 | 定位 | 内容 |
|------|------|------|
| PROGRESS.md | 高层视图 | 里程碑、版本摘要、**进度数字的唯一来源** |
| WORKLOG.md | 日志入口 | 日期/任务索引 |
| worklog/ | 详细日志 | 完整操作记录 |

**更新流程**：完成工作 → `worklog/<date>/<task>.md` → `WORKLOG.md` 索引 → `PROGRESS.md` 摘要。

---

## 相关文档

- **项目层**：[AGENTS.md](../../AGENTS.md)（Agent 工作指南）· [README.md](../../README.md)（项目总览）· [PROGRESS.md](../../PROGRESS.md)（项目总体进度）
- **任务层 / 配置**：本目录的 [GOAL](GOAL.md) · [PROGRESS](PROGRESS.md) · [WORKLOG](WORKLOG.md) · [todo](todo.md)，及 [.agents/workflow.yaml](../../.agents/workflow.yaml)

---

*最后更新: 2026-06-20*
