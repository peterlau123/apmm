# 2026-06-20 — Hermes Workflow Plan 2 部署实现 + 文档完善

## 1. Hermes Workflow Plan 2（部署通道）

以 subagent-driven 方式执行 `tasks/ut/docs/plans/2026-06-20-hermes-workflow-deployment.md`，
每个任务经 实现 → 规格审查 → 代码质量审查 三道关，全部通过。

- **Phase 0（关闭 4 个集成缺口 G1–G4）**：`get_execute_config` 扁平化 + 可注入 `exec_config`；
  `analyze_failed_tests_v5` 可注入 `check_branch`；`execute_batch` 兼容 `test_id`/`test_node`；
  smoke 改用真实管道 —— **实机 smoke 3/3 通过**。
- **Phase 1–3（代码）**：OTP 渐进重发（5/15/30/60min，第 3 次起 @user）、`parse_command`（飞书命令 + 白名单）、
  `refresh_manifest_stats`、`orchestrator_round`（Kanban Stage 5 reconcile + Stage 2 select）。
- **Phase 3–6（产物）**：`ut-orchestrator-SOUL.md`、`hermes_workflow/SKILL.md`、`ut-supervisor` profile.yaml
  （适配真实 Hermes schema）、`hermes-supervisor-service.md` + `hermes-gateway-service.md` 两份 systemd 部署指南、
  `tasks/ut/README.md` 导航行。

合并：fast-forward `bf8dc43..9817c7a` 到 master，分支已删除。测试 **69 passed, 2 skipped**。

## 2. 文档一致性修复（已合并 master）

- `docs/README.md` 索引补上两份 Hermes 部署指南（`84bab25`）。
- `check_stop_conditions` 返回元组顺序统一为 `(done, reason, status)`：修正
  `workflow_loop_core/SKILL.md`（3 处）与 `workflow/SKILL.md`（1 处），并让 `ut/workflow` SKILL
  指向两份新部署指南（`9dd5976`）。

## 3. manifest.json v5 字段回填

- 备份 → `tasks/ut/test_analysis/manifest.backup-2026-06-20.json`（md5 校验一致）。
- 用 `migrate_manifest()` dict 模式为全部 **31,868** 条测试回填 `max_retry=3` + `last_batch_id=null`；
  测试数、状态分布、schema 校验均不变。schema 本身确认为最新（当日 `2142f70` 更新）。

## 4. tasks/ut 文档完善

- `README.md` 重构（440 → ~250 行）：新增 ToC、合并重复链接区、把内嵌的配置/飞书/架构细节改为指向权威文档的指针、
  修正失效引用（已删除的 `workflow-template.yaml`、`manifest_example.json` 实际位置）。
- 为 `GOAL.md`、`todo.md` 增加 ToC（短文档 PROGRESS/WORKLOG 不加，避免臃肿）。
- 全部 ToC 锚点与 README 链接经脚本校验通过。
