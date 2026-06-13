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

| Stage | Skill | Version | Loop | 说明 |
|:-----:|-------|:-------:|:----:|------|
| **1** | ut-test-collector | v2.1 | ❌ | 收集测试列表（含 errors/failures 初始化） |
| **2** | batch-selector | v2.2 | ✅ | 选择批次（验证批次优先） |
| **3** | unit-test-executor | v3.2 | ✅ | 执行 pytest（含日志解析） |
| **4** | failure-handler | v3.0 | ✅ | 失败处理（脚本优先，Agent判断） |
| **5** | manifest-updater | v3.2 | ✅ | 更新状态（含 run_count/pass_rate） |

**Loop**: Stage 2-5 until `pending_count == 0`

详见 [skills/ut/workflow/SKILL.md](../../skills/ut/workflow/SKILL.md)

---

## Skills Review 状态

| 日期 | Review 内容 | 状态 |
|------|-------------|:----:|
| 2026-06-13 | Stage 1-5 输入输出对齐检查 | ✅ |
| 2026-06-13 | Schema 一致性修复（manifest/batch_config/batch_results） | ✅ |
| 2026-06-13 | 功能缺失补充（run_count/pass_rate/fixed_pending_verify） | ✅ |
| 2026-06-13 | workflow.yaml + workflow_schema.yaml 优化 | ✅ |

---

## 已完成工作

| 日期 | 里程碑 | 状态 |
|------|--------|:----:|
| 2026-06-13 | Skills Review + P1/P2/P3 修复 | ✅ |
| 2026-06-13 | manifest_schema.json 扩展（errors/failures/resolved） | ✅ |
| 2026-06-13 | workflow.yaml + workflow_schema.yaml 优化 | ✅ |
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

## 2026-06-13 Skills Review 详情

### Commit 摘要

| Commit | 内容 |
|--------|------|
| `4b26863` | failure-handler 3 个待修复问题（schema 移除 resolved 索引、manifest-updater 添加 errors/failures 处理、flowchart stats 补充） |
| `e9726b2` | manifest-updater v3.2（schema 一致性 + run_count/last_run_at/last_duration_ms/last_exit_code/pass_rate） |
| `0bf40cc` | batch-selector v2.2（fixed_pending_verify 优先选择）+ ut-test-collector v2.1（errors/failures/resolved 初始化） |
| `518e81d` | workflow.yaml + workflow_schema.yaml P1/P2/P3 优化 |

### 版本更新

| Skill | 旧版本 | 新版本 | 变化 |
|-------|:------:|:------:|------|
| ut-test-collector | 2.0.0 | 2.1.0 | +errors/failures/resolved 初始化 |
| batch-selector | 2.1.0 | 2.2.0 | +fixed_pending_verify 优先选择 |
| manifest-updater | 3.1.0 | 3.2.0 | +run_count/pass_rate 追踪 |
| manifest_schema.json | 2.0 | 2.0 | +errors[]/failures[]/resolved_* 定义 |
| workflow_schema.yaml | 2.0 | 2.0 | +input_filter/log_extraction/kanban.* 定义 |

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

## 更新模板

> 复制以下模板添加新的里程碑

```markdown
### YYYY-MM-DD 更新

| Commit | 内容 |
|--------|------|
| `<hash>` | <简要描述> |

| Skill | 旧版本 | 新版本 | 变化 |
|-------|:------:|:------:|------|
| <name> | <old> | <new> | <变化描述> |
```

---

*最后更新: 2026-06-13 (Skills Review + P1/P2/P3 修复完成)*
