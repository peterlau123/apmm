# AGENTS.md

AI Agent 工作指南 - 本项目为 **vLLM 验证框架** (M2.7_verify)

---

## 项目概述

这是一个验证框架，用于验证 **MiniMax-M2.7** 模型和 **vLLM** (v0.13.0) 推理引擎在 NVIDIA H20-3e GPU 环境下的功能、性能和精度。

| 组件 | 版本 | 说明 |
|------|------|------|
| vLLM | v0.13.0 | 高性能 LLM 推理引擎 |
| MiniMax-M2.7 | - | 待验证的大语言模型 |
| PyTorch | 2.5.1 / 2.7.0 | 深度学习框架 |
| CUDA | 12.4 / 12.8 | NVIDIA CUDA |
| GPU | NVIDIA H20-3e | 8卡, 143GB显存/卡 |

---

## 目录结构

```
apmm/
├── .agents/                  # Agent运行状态（统一）
│   ├── workflow.yaml         # Workflow 配置（v2.0）
│   ├── workflow_state.json   # Workflow 状态
│   ├── batch_config.json     # 批次配置
│   ├── batch_results.json    # 执行结果
│   ├── handled_tests.json    # 处理后的测试
│   ├── test_manifest.json    # 测试 manifest（用于验证）
│   ├── test_workflow_single_loop.py  # 单次循环测试脚本
│   ├── daemon/               # 守护进程脚本
│   ├── logs/                 # 运行日志
│   └── archive/              # 归档
│
├── skills/                   # Agent技能定义
│   └ ut/                     # 单元测试任务
│       ├── supervisor/       # Supervisor SKILL.md
│       │   └ scripts/
│       │       ├── init_workflow_state.py  # 初始化状态
│       │       ├── supervisor_loop.py      # 主循环
│       │       └ supervisor_status_check.py
│       │       └ supervisor_message_poll.py
│       │       └ supervisor_feishu_listen.py
│       │       └ check_all_agents.py
│       │       └ feishu_api.py
│       │       └ message_router.py
│       │       └ start_runner_agent.py
│       │
│       ├── batch-selector/   # 批次选择器
│       │   └ scripts/
│       │       ├── generate_batch.py       # 生成批次
│       │       └ check_available_gpus.py
│       │
│       ├── unit-test-executor/  # 执行器（已重命名）
│       │   └ scripts/
│       │       ├── run_batch.py           # 执行批次
│       │       ├── batch_test_runner.py
│       │       ├── check_inbox.py
│       │       ├── check_progress.py
│       │       ├── analyze_ut_results.py
│       │       ├── classify_error.py
│       │       ├── progress_tracker.py
│       │       ├── log_manager.py
│       │       ├── issues_tracker.py
│       │       ├── send_message.py
│       │       ├── update_state.py
│       │       ├── start_loop.py
│       │       ├── remote_test_runner.py
│       │       ├── parallel_batch_executor.py
│       │       ├── pytest_config.py
│       │       ├── check_environment.py
│       │       └ mark_passed_cases.py
│       │
│       ├── failure-handler/  # 失败处理器
│       │   └ scripts/
│       │       ├── analyze_failures.py     # 分析失败
│       │       ├── generate_handled_manifest.py
│       │       ├── send_to_supervisor.py
│       │
│       ├── manifest-updater/ # 状态更新器
│       │   └ scripts/
│       │       ├── update_status.py        # 更新状态
│       │       ├── update_manifest.py
│       │       ├── merge_phases.py
│       │       ├── generate_daily_reports.py
│       │       ├── send_to_supervisor.py
│       │
│       ├── dependency-resolver/  # 依赖解决器
│       │   └ scripts/
│       │       ├── check_dependency.py
│       │       ├── install_package.py
│       │       ├── download_model.py
│       │
│       ├── ut-test-collector/  # 测试收集器
│       │   └ scripts/
│       │       ├── collect.py
│       │
│       ├── environment-agent/ # Environment SKILL.md
│       └ bastion-agent/       # Bastion SKILL.md
│
├── tasks/                    # 任务工作区
│   ├── accuracy/             # 精度测试
│   ├── feature/              # 功能测试
│   ├── performance/          # 性能测试
│   ├── compile/              # 编译测试
│   └ ut/                     # 单元测试
│       ├── test_analysis/    # 测试分析
│       │   ├── manifest.json # 主 manifest
│       │   └ test_list.txt
│       │   └ archive/
│       ├── scripts/
│       └ PROGRESS.md
│
├── tools/                    # 工具脚本
│   ├── agent.py              # SSH代理
│   ├── feishu/               # 飞书脚本
│   └ utilities/            # 其他工具
│
├── docs/                     # 项目文档
│   ├── guides/               # 指南
│   ├── reference/            # 参考
│   └ archive/                # 归档
│
├── AGENTS.md                 # 本文件
├── CLAUDE.md                 # AI行为准则
├── README.md                 # 项目总览
├── PROGRESS.md               # 总体进度
└ .gitignore
```

---

## Workflow 架构 v2.0

### Hierarchical Agent 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Supervisor Agent Session (持久)                             │
│                                                             │
│  双重职责：                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ Workflow 调度       │  │ Agent 监控          │          │
│  │ • delegate_task     │  │ • 消息路由          │          │
│  │ • state.json管理    │  │ • 心跳检查          │          │
│  │ • Kanban同步        │  │ • 飞书通知          │          │
│  └─────────────────────┘  └─────────────────────┘          │
│                                                             │
│  Context: workflow.yaml + state.json (~10K tokens)          │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ delegate_task (每次 Stage)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Worker Agent Session (临时，执行后释放)                     │
│                                                             │
│  • 加载 SKILL.md                                            │
│  • 执行单个 Stage                                           │
│  • 调用脚本 + 判断逻辑 + 修复代码                            │
│  • 返回极简结果给 Supervisor                                │
│  • Session 结束，Context 释放                                │
└─────────────────────────────────────────────────────────────┘
```

### Workflow Stages

| Stage | 名称 | Skill | delegate_to | Loop | 说明 |
|-------|------|-------|-------------|------|------|
| 1 | collect | ut-test-collector | claude-code | No | 收集测试列表 |
| 2 | select_batch | batch-selector | claude-code | Yes | 选择下一批次 |
| 3 | execute | unit-test-executor | claude-code | Yes | 执行 pytest |
| 4 | handle_failures | failure-handler | claude-code | Yes | 分析失败+修复 |
| 5 | update_status | manifest-updater | claude-code | Yes | 更新 manifest |

### delegate_to 配置说明

`delegate_to` 字段指定 Worker Agent 使用哪个 AI 模型/工具执行：

```yaml
stages:
  - id: select_batch
    delegate_to: claude-code  # 使用 Claude Code 执行
    skill: batch-selector
    loop: true
```

**可用选项**：
- `claude-code` - 使用 Claude Code CLI 工具
- `hermes-agent` - 使用 Hermes Agent session
- `codex` - 使用 OpenAI Codex

### Worker Output Schema

所有 Worker 返回统一格式：

```json
{
  "stats": {
    "passed": 3,
    "failed": 2,
    "error": 0,
    "ignored": 1,
    "pending": 12599
  },
  "next_action": "continue",  // continue | pause | stop | wait
  "error": null,
  "blocked_reason": null
}
```

**注意**：Worker 不返回 batch_id、log_file、details_file 等额外字段。

---

## 远程环境路径映射

本地目录名与远程服务器目录名对照：

| 本地目录 | 远程目录 | 远程路径 |
|---------|---------|---------|
| `accuracy/` | `accuracy_test/` | `/gpfs/gcsp/M2.7_verify/accuracy_test/` |
| `feature/` | `feature_test/` | `/gpfs/gcsp/M2.7_verify/feature_test/` |
| `performance/` | `performance_test/` | `/gpfs/gcsp/M2.7_verify/performance_test/` |
| `pytorch/` | `pytorch_verify/` | `/gpfs/gcsp/M2.7_verify/pytorch_verify/` |
| `unit_test/` | `unit_test/` | `/gpfs/gcsp/M2.7_verify/unit_test/` |
| `vllm源码` | `vllm/` | `/gpfs/gcsp/M2.7_verify/vllm/` |

---

## 测试环境架构

```
本机 (Windows + VPN)
    │
    │  agent.py (SSH over Bastion)
    ▼
堡垒机 10.10.192.55:22 (齐治 Shterm)
    │
    ├──────────────────────────────────────┐
    │                                      │
    ▼                                      ▼
t_ascend (10.250.121.21)              t_h20 (10.10.154.13)
- 联网机器                             - 未联网机器
- 下载依赖/模型                         - NVIDIA H20-3e × 8
- 无/gpfs挂载                           - Docker容器运行测试
                                       - /gpfs 共享存储 (1.9PB)
```

---

## Agent 工作命令

### 连接远程服务器

```powershell
# 检查 daemon 状态
python agent.py -p t_ascend ping
python agent.py -p t_h20 ping

# 执行远程命令
python agent.py -p t_h20 run "ls /gpfs/gcsp/M2.7_verify/"

# 进入交互式 shell
python agent.py -p t_h20 shell
```

### 运行测试

```bash
# 在 t_h20 容器内执行 pytest
sudo docker exec -it v0.13.0_torch2.5.1_ut bash
cd /gpfs/gcsp/M2.7_verify/vllm
pytest -vv tests/test_xxx.py 2>&1 | tee ut_logs/xxx_ut.log
```

或通过 agent.py 远程执行：

```powershell
python agent.py -p t_h20 run --timeout 300 "sudo docker exec v0.13.0_torch2.5.1_ut bash -c 'cd /gpfs/gcsp/M2.7_verify/vllm && pytest -vv tests/test_seed_behavior.py'"
```

---

## 测试过滤规则

运行 pytest 时需排除不支持的平台：

```bash
pytest tests/ \
    --ignore-glob="tests/**/rocm*" \
    --ignore-glob="tests/**/tpu*" \
    --ignore-glob="tests/**/multimodal*" \
    --ignore-glob="tests/**/nixl*" \
    --ignore-glob="tests/**/ec_connector*" \
    --ignore-glob="tests/**/*image*.py" \
    --ignore-glob="tests/**/*video*.py" \
    --ignore-glob="tests/**/*audio*" \
    --ignore-glob="tests/**/encoder*" \
    --ignore-glob="tests/**/prithvi*" \
    -vv -s
```

---

## 评测工具

| 工具 | 用途 | 数据集 |
|------|------|--------|
| evalscope | 精度评测 | GPQA-Diamond, GSM8K, MATH-500, MMLU-Pro |
| Multi-SWE-bench | 代码修复评测 | 7种语言, 1632个实例 |

---

## 文件追踪策略

本项目使用本地 Git 仓库追踪关键脚本和文档，不追踪：

- 模型文件 (`*.safetensors`, `*.bin`)
- 压缩包 (`*.tar`, `*.tar.gz`, `*.zip`)
- 数据集缓存 (`datasets/`, `hf_hub/`, `modelscope/`)
- 日志输出 (`*.log`, `outputs/`, `logs/`)
- Python缓存 (`__pycache__/`, `.venv/`, `*.pyc`)
- Docker相关 (`docker_images/`, `docker_bin/`)

---

## 文档管理规范

### 文档层级与职责

| 层级 | 文档 | 职责 | 更新频率 |
|------|------|------|----------|
| **项目层** | README.md | 项目总览、快速开始 | 架构变更时 |
| **项目层** | AGENTS.md | Agent工作指南 | 目录/流程变更时 |
| **任务层** | PROGRESS.md | **进度汇聚点**（主入口） | 每日/每周 |
| **任务层** | tasks/*/README.md | 任务模块说明 | 结构变更时 |
| **工作层** | WORKLOG.md | 工作日志（归档型） | 每日记录 |

### 核心原则

1. **汇聚优先**：进度更新优先写入 **PROGRESS.md**，避免分散
2. **上层导引**：项目层文档（README.md, AGENTS.md）仅作导引，不包含细节
3. **归档不动**：WORKLOG.md 记录后不再修改，仅作归档
4. **禁止随意创建**：不随意新建文档，除非用户明确要求

### 更新规则

| 场景 | 目标文档 | 说明 |
|------|----------|------|
| 任务进度变化 | PROGRESS.md | 主汇聚点，每日更新 |
| 发现新问题/解决 | PROGRESS.md | 记录到对应任务章节 |
| 目录结构变化 | AGENTS.md | 更新目录结构图 |
| 任务模块变更 | tasks/*/README.md | 仅结构级变更时更新 |
| 每日工作记录 | WORKLOG.md | 归档型，记录后不动 |
| 新增指南/规范 | docs/guides/ | 参考型文档 |

### 禁止行为

- ❌ 创建临时文档记录进度（应写入PROGRESS.md）
- ❌ 在项目层文档添加任务细节（应写入任务层）
- ❌ 同一信息多处重复记录（汇聚到一处）
- ❌ 修改已归档的WORKLOG.md（仅追加）
- ❌ 通过 bastion server 上传或下载文件（堡垒机仅用于命令转发，不支持文件传输）
- ❌ 将原始数据直接丢给 LLM 进行统计（应编写脚本在远程执行统计，只返回结果）

---

## 脚本标准化使用说明

### 统一的路径读取方式

所有脚本支持两种模式：

1. **从 workflow_state.json 读取路径**（推荐）：
   ```bash
   python generate_batch.py --workflow-state D:/workspace/apmm/.agents/workflow_state.json
   ```

2. **直接指定路径**：
   ```bash
   python generate_batch.py --manifest-path PATH --output-path PATH
   ```

### 初始化 workflow_state.json

```bash
python skills/ut/workflow/scripts/init_workflow_state.py \
    --workflow-yaml D:/workspace/apmm/.agents/workflow.yaml \
    --manifest-path D:/workspace/apmm/tasks/ut/test_analysis/manifest.json
```

---

## 相关文档

- [CLAUDE.md](./CLAUDE.md) - AI Agent 行为准则
- [README.md](./README.md) - 项目总览和快速开始
- [PROGRESS.md](./PROGRESS.md) - **进度汇聚点（主入口）**
- [.agents/workflow.yaml](./.agents/workflow.yaml) - Workflow 配置
- [skills/ut/workflow/SKILL.md](./skills/ut/workflow/SKILL.md) - Supervisor 调度器
- [docs/bastion.md](./docs/bastion.md) - 堆垒机连接方案
- [tasks/ut/README.md](./tasks/ut/README.md) - 单元测试说明
- [tasks/compile/README.md](./tasks/compile/README.md) - 编译测试说明