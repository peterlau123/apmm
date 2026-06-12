# 单元测试进度追踪

> **vLLM v0.13.0 + PyTorch 2.5.1 pytest 测试进度**

---

## 最新统计

| 指标 | 数值 |
|------|:----:|
| 总测试用例数 | 31,868 |
| 已执行用例数 | 6,412 |
| 进度 | 20.12% |
| 通过数 | 6,411 |
| 失败数 | 1 |
| 错误数 | 0 |
| 待执行数 | 25,456 |

---

## Skills 架构

**架构决策**: Hierarchical Agent（Workflow + Worker）

### Workflow Stages

| Stage | Skill | Loop | 说明 |
|:-----:|-------|:----:|------|
| **1** | ut-test-collector | ❌ | 收集测试列表 |
| **2** | batch-selector | ✅ | 选择批次 |
| **3** | unit-test-executor | ✅ | 执行 pytest（含日志解析） |
| **4** | failure-handler | ✅ | 失败处理 |
| **5** | manifest-updater | ✅ | 更新状态 |

**Loop**: Stage 2-5 until `pending_count == 0`

详见 [skills/ut/workflow/SKILL.md](../../skills/ut/workflow/SKILL.md)

---

## 已完成工作

| 日期 | 里程碑 | 状态 |
|------|--------|:----:|
| 2026-06-12 | Hermes Kanban 集成 Phase 1（基础设施） | ✅ |
| 2026-06-12 | 代码提交：v5.1 重构 + Kanban 准备 | ✅ |
| 2026-06-11 | 日志解析集成到 Stage 3 | ✅ |
| 2026-06-11 | Skill 重命名 supervisor→workflow | ✅ |
| 2026-06-11 | Schema 统一 Phase 1-4（校验+迁移） | ✅ |
| 2026-06-11 | 文件整理方案设计 | ✅ |
| 2026-06-10 | Phase 1-3: Workflow 配置 + SKILL.md 创建 | ✅ |
| 2026-06-10 | Phase 4: 脚本标准化 | ✅ |
| 2026-06-10 | Phase 5: 整体测试准备 | ✅ |
| 2026-06-10 | Phase 7: 审核修复 | ✅ |
| 2026-06-08 | Phase 1+Phase 2 清单合并 | ✅ |

---

## Hermes Kanban 集成

> 详见 [docs/kanban/README.md](docs/kanban/README.md)

| Phase | 内容 | 状态 |
|:-----:|------|:----:|
| **1** | 基础设施：Board + 3 Profile + 依赖链验证 | ✅ |
| **2** | 方案 A-1 集成：SKILL.md v5.2 + start_gateway.py + monitor_kanban.py | ✅ |
| **3** | Kanban 模式真实运行验证 | ⬜ |
| **4** | 生产化：多 GPU 并行 + 断点续跑 + 性能基准 | ⬜ |

### Phase 1-2 完成项

- [x] Hermes Agent v0.15.1 确认安装
- [x] 项目专用 board `apmm-ut` 创建
- [x] 3 个 worker profile（ut-orchestrator / ut-executor / ut-fixer）
- [x] SOUL.md 角色定义 + API Key 配置
- [x] 示例任务创建 + parent→child 依赖晋升验证
- [x] 集成文档 [docs/kanban/README.md](docs/kanban/README.md)
- [x] SKILL.md v5.2 版本更新 + Kanban 分支逻辑
- [x] start_gateway.py 脚本创建（启动 3 Gateway）
- [x] monitor_kanban.py 脚本创建（监控任务完成）
- [x] workflow.yaml kanban 配置结构更新

---

## 待完成工作

- **Phase 6**: Workflow 集成测试
  - 运行 workflow_loop.py --init
  - 运行 workflow_loop.py --single-iteration
  - 测试 4 个 test list
- **Kanban Phase 2**: 单任务验证
  - 启动 3 个 gateway 同时运行
  - 真实 batch 任务执行验证
  - 熔断器验证

---

## 统计更新日志

| 时间 | 进度 | 通过数 | 备注 |
|------|:----:|:------:|------|
| 2026-06-11 | 20.12% | 6,411 | Skill 重命名完成 |

---

*最后更新: 2026-06-12 (Kanban Phase 1 完成)*
