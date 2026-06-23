# 2026-06-22 — docs 收拢 + L4 启动脚本搬位 + Windows 服务 + tier/intent spec

会话主线：把项目文档归位规则定下来 → 把 UT 相关文档全部迁入 `tasks/ut/docs/` → 把 L4 启动脚本搬到合理位置 → 补 Windows NSSM 部署文档 → 给"L1–L4 烟囱测试梯度 + Agent 意图识别"写 spec 设计文档。**未动任何运行代码**，所有改动是文档/路径/spec。

---

## 推荐的 3 个 commit（请按顺序提交）

> 用 `git status` 看具体改了哪些，下面是 message 模板。每段最后保留 `Co-Authored-By: Claude <noreply@anthropic.com>` 是 Claude Code 的默认要求。

---

### Commit 1 — 文档收拢 + 归位规则

```text
docs: consolidate UT docs into tasks/ut/docs/ + add hard relocation rule

Reorganize project documentation along the tasks/<x>/docs/ boundary:

Project-level docs/ now contains only cross-subsystem material:
- guides/: ai-workflow, bastion, environment
- reference/: daily-operations (renamed from workflow.md)
- superpowers/specs/: 3 non-UT specs + archive/

UT-specific docs all moved under tasks/ut/docs/:
- designs/  12 specs + agents/ subtree + hermes-kanban-v1-spec.pdf
- plans/    7 UT implementation plans
- incidents/ moved from docs/incidents/ (UT is the only source so far)
- guides/   gained hermes-supervisor-service.md, hermes-gateway-service.md,
            troubleshooting.md (all UT-specific, were misplaced at project level)

Both index READMEs (docs/README.md, tasks/ut/docs/README.md) rewritten.
All cross-references updated (25+ files): SKILL.md, tasks/ut/README.md,
existing specs/plans/incidents/discussions/reports.

Add CLAUDE.md §5 "Documentation relocation rule (hard rule)" generalizing
the boundary to any tasks/<x> subsystem (ut/accuracy/performance/future).
Project-level docs/ is now explicitly forbidden from receiving any
single-subsystem detail doc. Top of both READMEs carries a hard warning.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

### Commit 2 — 重命名 + 搬位 L4 启动脚本

```text
chore(ut): rename start_l4_test.py -> start_hermes_ut_runtime.py, move to tasks/ut/scripts/

The bootstrap script that brings up the 4 Hermes processes (3 worker
gateways + ut-supervisor) was historically named start_l4_test.py and
lived under tests/ut/integration/, which mis-suggested it was test code.

It is, in fact, a generic Hermes UT runtime bootstrap usable from L1
through L4 and even ad-hoc/dev sessions. tests/ should hold pytest
test code; bootstrap utilities belong in scripts/.

Changes:
- git mv tests/ut/integration/start_l4_test.py -> tasks/ut/scripts/start_hermes_ut_runtime.py
- 7 referencing files updated (docs, SKILL refs, integration fixtures)
- _PROJECT_ROOT derivation (parent x 4) still valid at the new depth
- Smoke-tested via `--status`: 6/6 preflight checks pass

This unblocks both production deployment (NSSM/systemd/launchd services
replace the script entirely) and dev/L4 use (script remains the
documented bootstrap when no service manager is in play).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

### Commit 3 — NSSM 部署 + tier/intent spec

```text
docs(ut): add Windows NSSM deployment guide + L1-L4 tier + Agent intent spec

Two new documents:

1. tasks/ut/docs/guides/hermes-windows-service.md
   Sister doc to hermes-supervisor-service.md and hermes-gateway-service.md
   (Linux systemd). Covers Windows NSSM registration of all 4 Hermes
   processes with auto-start, crash-restart, log rotation. Includes a
   macOS launchd quick-reference table so all three platforms have a
   "boot-time service" path. Clarifies the script-vs-service distinction:
   start_hermes_ut_runtime.py is for dev/L4; services are for production.

2. tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md
   Spec for two related capabilities (no code changes in this commit):

   - L1-L4 smoke test tier with frozen fixtures:
     L1 (1 stable pytest, linear)
     L2 (mini_test_list, linear)
     L3 (l3_fast_subset, linear+kanban)
     L4 (l3_retry_subset, kanban + distributed)
     plus production (full UT list).

     Each tier carries its own workflow.l<N>.yaml + L<N>_expected.json.
     L4_expected.json gets anti-fabrication assertions (AF-1/2/3) and
     stage invariants (STG-1/2/3) added to catch the failure modes
     documented in tasks/ut/docs/incidents/2026-06-22-l4-fabrication.md.

   - Two-layer Agent intent classifier for Feishu messages:
     Layer 1 deterministic regex (otp/stop/pause/resume) bypasses LLM.
     Layer 2 LLM (via ut-supervisor SOUL.md) classifies start_l1..l4 /
     start_production / change_config / unknown with confidence >= 0.7.
     Start-class intents must still pass a confirmation card as safety gate.

   Implementation breakdown P0-P5 with ~10h estimate, deferred to a
   future session. TodoList items 5-11 carry the work.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## 提交命令模板

```bash
# 看 staging 状态
git status

# 按 commit 1 的范围加文件（docs 重组 + 引用更新）
git add docs/ tasks/ut/docs/ CLAUDE.md \
  $(git status -s | awk '/^[ ARM]/ && /\.md$/ {print $NF}' | grep -v "tasks/ut/scripts/")

# 用 commit message 1
git commit -F .git/COMMIT_EDITMSG  # 把上面 commit 1 文本粘到编辑器里

# commit 2 — 脚本搬位
git add tasks/ut/scripts/start_hermes_ut_runtime.py \
        tests/ut/integration/  # 已 git mv 走的引用
git commit -F .git/COMMIT_EDITMSG  # commit 2 文本

# commit 3 — 新文档（NSSM + spec）
git add tasks/ut/docs/guides/hermes-windows-service.md \
        tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md \
        tasks/ut/docs/README.md  # 索引补行
git commit -F .git/COMMIT_EDITMSG  # commit 3 文本

# 然后 push（你自己决定时机）
# git push origin test/l4-freeze-config
```

> 顺序提醒：commit 1 改了非常多的 .md 引用（路径迁移），commit 2 重命名脚本，commit 3 才是新增的两份文档。**严格按这个顺序**否则中间状态会出现"路径未更新"的死链。

---

## 下次 session 接续

新 session 时说：

> 接 `tasks/ut/docs/designs/2026-06-22-ut-tier-fixtures-and-agent-intent-design.md` 这份 spec 实施。先 `TaskList` 看待办，按 P0a → P5 顺序做。

TodoList 里的 #5–#11 是 P0a–P5 全部待办。

---

*会话开销节点：本次约 $24，3 commit message + 这份 worklog 落盘后正式收尾。*
