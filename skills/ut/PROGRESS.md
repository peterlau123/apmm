# UT Workflow Progress

## 当前状态

**版本**: 2.0 (Hierarchical Agent Architecture)
**日期**: 2026-06-10
**状态**: 开发中

---

## 已完成工作

### Phase 1: 动态运行目录 (2026-06-10)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 动态运行目录创建 `{runs_dir}/{test_name}-{timestamp}` | ✅ |
| 2 | batch 文件使用子目录 `{run_dir}/batches/{batch_id}/` | ✅ |
| 3 | current_run.json 指针文件 | ✅ |
| 4 | workflow_state.json 动态路径 | ✅ |

**修改文件**:
- `workflow.yaml` - config 板块更新，批次路径使用 `{batch_id}` 占位符
- `config_loader.py` - 添加 `resolve_batch_path`, `create_batch_dir`
- `init_workflow_state.py` - 创建 batches/ 目录，支持 --test-list
- `supervisor_loop.py` - 支持 `{batch_id}` 占位符解析
- `generate_batch.py` - 输出到批次目录
- `generate_handled_manifest.py` - 输出到批次目录
- `update_status.py` - 从批次目录读取

### Phase 2: Stage 1 简化 (2026-06-10)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 简化 Stage 1 输入：test_list.txt + manifest_schema.json | ✅ |
| 2 | 创建 manifest_schema.json | ✅ |

### Phase 3: JSON Schema 定义 (2026-06-10)

| # | 任务 | 状态 |
|---|------|------|
| 1 | manifest_schema.json | ✅ 已存在 |
| 2 | batch_config_schema.json | ✅ 新建 |
| 3 | batch_results_schema.json | ✅ 新建 |
| 4 | handled_tests_schema.json | ✅ 新建 |
| 5 | workflow_state_schema.json | ✅ 新建 |

### Phase 4: batch_config.json 格式统一 (2026-06-10)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 修复 generate_batch.py stats 格式 | ✅ |
| 2 | 分离 batch_config.json 和 Worker 返回格式 | ✅ |
| 3 | 更新 batch-selector/SKILL.md | ✅ |

---

## 待完成工作

### Phase 5: Worker 脚本验证

| # | 任务 | 状态 |
|---|------|------|
| 1 | 验证 unit-test-executor/run_batch.py | ✅ 2026-06-11 |
| 2 | 验证 failure-handler/generate_handled_manifest.py | ✅ 2026-06-11 |
| 3 | 验证 manifest-updater/update_status.py | ✅ 2026-06-11 |

### Phase 6: Workflow 集成测试

| # | 任务 | 状态 |
|---|------|------|
| 1 | 运行 supervisor_loop.py --init | ⏳ |
| 2 | 运行 supervisor_loop.py --single-iteration | ⏳ |
| 3 | 验证批次子目录结构 | ⏳ |
| 4 | workflow.yaml post_action 配置 | ✅ 2026-06-11 |

---

## 文件结构

```
skills/ut/
├── shared/
│   ├── config_loader.py          ✅ 已修改
│   ├── manifest_schema.json      ✅ 已存在
│   ├── batch_config_schema.json  ✅ 新建
│   ├── batch_results_schema.json ✅ 新建
│   ├── handled_tests_schema.json ✅ 新建
│   └── workflow_state_schema.json✅ 新建
├── supervisor/
│   ├── scripts/
│   │   ├── init_workflow_state.py ✅ 已修改
│   │   └── supervisor_loop.py     ✅ 已修改
│   └── SKILL.md
├── batch-selector/
│   ├── scripts/
│   │   └── generate_batch.py      ✅ 已修改
│   └── SKILL.md                   ✅ 已修改
├── failure-handler/
│   ├── scripts/
│   │   └ generate_handled_manifest.py ✅ 已修改
│   └── SKILL.md
├── manifest-updater/
│   ├── scripts/
│   │   └ update_status.py        ✅ 已修改
│   └── SKILL.md
├── unit-test-executor/
│   ├── scripts/
│   │   └── run_batch.py
│   └── SKILL.md
└── test-collector/
    └── SKILL.md
```

---

## 运行目录结构

```
runs/ut-{timestamp}/
├── workflow_state.json     # 状态跟踪
├── manifest.json           # 测试清单
├── test_list.txt           # 测试列表（拷贝）
├── batches/
│   └── batch_{timestamp}/
│       ├── batch_config.json   # 批次配置
│       ├── batch_results.json  # 执行结果
│       ├── handled_tests.json  # 失败处理
│       └── logs/
├── logs/                   # 全局日志
└── reports/                # 报告输出
```

---

## 下一步

1. 运行集成测试验证 workflow
2. 验证各 Worker 脚本输出格式符合 schema
3. 完成 supervisor_loop.py 与 Hermes 的 delegate_task 集成

---

*最后更新: 2026-06-10*