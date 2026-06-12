# AGENTS.md

AI Agent 操作手册 — 本项目为 **vLLM 验证框架** (M2.7_verify)

> 项目总览见 [README.md](README.md)

---

## 环境信息

| 组件 | 版本 |
|------|------|
| vLLM | v0.13.0 |
| PyTorch | 2.5.1 / 2.7.0 |
| CUDA | 12.4 / 12.8 |
| GPU | NVIDIA H20-3e × 8, 143GB/卡 |

### 远程环境

```
本机 (Windows + VPN)
    │  agent.py (SSH over Bastion)
    ▼
堡垒机 10.10.192.55:22
    │
    ├── t_ascend (10.250.121.21)     ← 联网，下载依赖/模型
    │
    └── t_h20 (10.10.154.13)         ← 未联网，NVIDIA H20-3e × 8
         Docker 容器运行测试
         /gpfs 共享存储 (1.9PB)
```

### 路径映射

| 本地目录 | 远程路径 |
|---------|---------|
| `tasks/ut/` | `/gpfs/gcsp/M2.7_verify/unit_test/` |
| `tasks/accuracy/` | `/gpfs/gcsp/M2.7_verify/accuracy_test/` |
| `tasks/feature/` | `/gpfs/gcsp/M2.7_verify/feature_test/` |
| `tasks/performance/` | `/gpfs/gcsp/M2.7_verify/performance_test/` |
| vLLM 源码 | `/gpfs/gcsp/M2.7_verify/vllm/` |

连接方式详见 [docs/guides/](docs/guides/) 和 [tools/agent.py](tools/agent.py)。

---

## 目录结构

```
apmm/
├── .agents/                  # Agent 运行状态
│   ├── workflow.yaml         #   Workflow 配置
│   ├── workflow_state.json   #   运行状态
│   ├── batch_config.json     #   批次配置
│   ├── batch_results.json    #   执行结果
│   ├── handled_tests.json    #   失败处理结果
│   ├── daemon/               #   守护进程
│   ├── logs/                 #   运行日志
│   └── archive/              #   归档
│
├── skills/                   # Agent 技能定义
│   └── ut/                   #   单元测试 Skills（8个）
│       ├── workflow/         #     调度器
│       ├── batch-selector/   #     批次选择
│       ├── unit-test-executor/ #   测试执行
│       ├── failure-handler/  #     失败处理
│       ├── manifest-updater/ #     状态更新
│       ├── ut-test-collector/ #    测试收集
│       ├── dependency-resolver/ #  依赖解决
│       └── shared/           #     共享基础设施
│
├── tasks/                    # 任务工作区
│   ├── ut/                   #   单元测试 → [README](tasks/ut/README.md)
│   ├── accuracy/             #   精度测试
│   ├── feature/              #   功能测试
│   ├── performance/          #   性能测试
│   └── compile/              #   编译测试
│
├── tools/                    # 工具脚本
│   ├── agent.py              #   SSH 代理
│   ├── feishu/               #   飞书通知
│   └── utilities/            #   其他工具
│
├── docs/                     # 项目文档
│   ├── guides/               #   操作指南
│   ├── reference/            #   参考文档
│   └── archive/              #   归档
│
├── AGENTS.md                 # 本文件
├── CLAUDE.md                 # AI 行为准则
├── README.md                 # 项目总览
└── PROGRESS.md               # 总体进度
```

---

## OpenCode 工作模式

OpenCode 默认采用 **Brainstorming → Planning → Execution → Verification** 四阶段工作流，强制先思考、再计划、再实施、最后验证。

**详细流程**：[docs/guides/ai-workflow.md](docs/guides/ai-workflow.md)

**核心原则**：
- ❌ 不跳过思考阶段（必须 Phase 1-3）
- ❌ 不跳过验证阶段（完成后必须 Verification Loop）
- ✅ 每步验证、逐步推进

---

## UT Workflow 架构

UT Workflow 采用 5 阶段流水线，详见：

| 信息 | 权威源 |
|------|--------|
| Workflow 配置 | [.agents/workflow.yaml](.agents/workflow.yaml) |
| 架构图 + Stages 定义 | [skills/ut/workflow/SKILL.md](skills/ut/workflow/SKILL.md) |
| 过滤规则（单一来源） | [skills/ut/shared/filter_rules.yaml](skills/ut/shared/filter_rules.yaml) |
| 模块总入口 | [tasks/ut/README.md](tasks/ut/README.md) |

脚本统一从 `workflow_state.json` 读取路径，详见各 Skill 的 SKILL.md。

---

## 文档管理规范

### 层级职责

```
项目层 (README.md / AGENTS.md)
  │  职责: 总入口 + 导引，只做路标，不堆细节
  │
  └─→ 任务层 (tasks/*/README.md)
        │  职责: 模块总入口，全面导航所有资源
        │
        ├─→ 数据层 (PROGRESS.md / WORKLOG.md / todo.md)
        │    职责: 进度、日志、待办 — 每种信息只在一处
        │
        └─→ 细节层 (docs/ / scripts/ / patches/ / test_analysis/)
             职责: 操作指南、报告、脚本说明 — 罗列详细信息
```

### 核心原则

1. **汇聚优先**：每种信息只在一处 — 进度 → PROGRESS.md，日志 → WORKLOG.md，细节 → docs/
2. **上层导引**：项目层只做路标和链接，不堆砌细节
3. **任务层导航**：tasks/*/README.md 是模块总入口，含完整目录树、架构图、所有子资源链接
4. **细节层罗列**：docs/guides/、*/README.md 等底层文档负责详细信息
5. **归档不动**：WORKLOG.md 记录后仅追加，不修改

### 禁止行为

- ❌ 在项目层 README/AGENTS 中罗列详细步骤、脚本参数、数据表格
- ❌ 创建临时文档记录进度（应写入 PROGRESS.md）
- ❌ 同一信息多处重复记录
- ❌ 修改已归档的 WORKLOG.md
- ❌ 通过 bastion 上传/下载文件
- ❌ 将原始数据直接丢给 LLM 统计

---

## 文件追踪策略

Git 追踪关键脚本和文档，不追踪：

模型文件 (`*.safetensors`, `*.bin`) · 压缩包 (`*.tar`, `*.tar.gz`, `*.zip`) · 数据集缓存 · 日志 (`*.log`) · Python 缓存 · Docker 相关

---

## 相关文档

- [CLAUDE.md](CLAUDE.md) — AI 行为准则
- [README.md](README.md) — 项目总览
- [PROGRESS.md](PROGRESS.md) — 总体进度
- [tasks/ut/README.md](tasks/ut/README.md) — 单元测试总入口
- [tasks/compile/README.md](tasks/compile/README.md) — 编译测试
