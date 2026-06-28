# UT Workflow 状态分类逻辑修改 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改 UT workflow 状态分类：timeout/resource→ignored，retriable_error只保留oom，修复container_env注入docker exec

**Architecture:** 
- 状态分类逻辑集中在 execute_batch.py 和 classify_error.py
- container_env 通过 -e flags 注入 docker exec
- 同时修复代码审查发现的 P0/P1 问题

**Tech Stack:** Python, pytest, YAML, Git

---

## 文件结构

| 文件 | 负责 | 修改类型 |
|---|---|---|
| `skills/ut/unit-test-executor/scripts/execute_batch.py` | Stage 3 执行器，timeout处理+环境变量注入 | Modify |
| `skills/ut/unit-test-executor/scripts/classify_error.py` | 错误分类，timeout→ignored | Modify |
| `skills/ut/terminal-workflow/SKILL.md` | terminal-workflow SKILL，validate_required_config调用 | Modify |
| `skills/ut/failure-handler/SKILL.md` | Stage 4 处理范围文档 | Modify |
| `tests/ut/integration/fixtures/workflow.e2e.yaml` | E2E测试配置，补全HF环境变量 | Modify |
| `tests/ut/integration/fixtures/workflow.hermes.e2e.yaml` | Hermes E2E配置，补全HF环境变量 | Modify |
| `.agents/workflow.yaml` | 生产配置，修复kanban enabled矛盾 | Modify |
| `tasks/ut/README.md` | UT README，修复skill名称引用 | Modify |
| `tasks/ut/scripts/start_ut_workflow.py` | 孤儿脚本 | Delete |

---

## Task 1: classify_error.py - timeout→ignored

**Files:**
- Modify: `skills/ut/unit-test-executor/scripts/classify_error.py`
- Test: `tests/ut/unit/`

- [ ] **Step 1: Read current classify_error.py timeout handling**

Read file to locate timeout classification logic.

- [ ] **Step 2: Modify timeout classification**

Change `return ("retriable_error", "timeout")` to `return ("ignored", "timeout")`

- [ ] **Step 3: Run unit tests**

Run: `python -m pytest tests/ut/unit/ -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add skills/ut/unit-test-executor/scripts/classify_error.py
git commit -m "fix(ut): classify timeout as ignored, keep oom as only retriable_error

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: execute_batch.py - container_env注入

**Files:**
- Modify: `skills/ut/unit-test-executor/scripts/execute_batch.py`

- [ ] **Step 1: Add env_vars parameter to _wrap_with_docker_exec_b64**

Add new parameter and construct `-e` flags for environment variables.

- [ ] **Step 2: Update execute_batch to pass container_env**

Get `container_env` from config and pass to the wrapper function.

- [ ] **Step 3: Run unit tests**

Run: `python -m pytest tests/ut/unit/ -q`
Expected: 368 passed

- [ ] **Step 4: Commit**

```bash
git add skills/ut/unit-test-executor/scripts/execute_batch.py
git commit -m "fix(ut): inject container_env into docker exec via -e flags

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: execute_batch.py - timeout XML missing处理

**Files:**
- Modify: `skills/ut/unit-test-executor/scripts/execute_batch.py`

- [ ] **Step 1: Modify _parse_junit timeout handling**

Change status from `retriable_error` to `ignored` when XML is missing.

- [ ] **Step 2: Update _fallback_timeout similarly**

Change fallback to return `ignored` status.

- [ ] **Step 3: Run unit tests**

Run: `python -m pytest tests/ut/unit/ -q`

- [ ] **Step 4: Commit**

```bash
git add skills/ut/unit-test-executor/scripts/execute_batch.py
git commit -m "fix(ut): classify timeout as ignored with audit classification record

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: terminal-workflow SKILL.md - validate_required_config channel参数

**Files:**
- Modify: `skills/ut/terminal-workflow/SKILL.md`

- [ ] **Step 1: Add channel='linear' parameter**

Change `validate_required_config(cfg)` to `validate_required_config(cfg, channel="linear")`

- [ ] **Step 2: Commit**

```bash
git add skills/ut/terminal-workflow/SKILL.md
git commit -m "fix(ut): pass channel='linear' to validate_required_config (S3)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: failure-handler SKILL.md - 更新处理范围

**Files:**
- Modify: `skills/ut/failure-handler/SKILL.md`

- [ ] **Step 1: Update Behavior section**

Document that only `failed` and `version` error are processed.

- [ ] **Step 2: Commit**

```bash
git add skills/ut/failure-handler/SKILL.md
git commit -m "docs(ut): update failure-handler to only process failed + version error

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: workflow.e2e.yaml - 补全HF环境变量

**Files:**
- Modify: `tests/ut/integration/fixtures/workflow.e2e.yaml`

- [ ] **Step 1: Add VLLM_ASSETS_CACHE and HF_HUB variables**

Add: `VLLM_ASSETS_CACHE`, `HF_HUB_OFFLINE`, `HF_HUB_CACHE`

- [ ] **Step 2: Commit**

```bash
git add tests/ut/integration/fixtures/workflow.e2e.yaml
git commit -m "fix(ut): add full HF env vars to workflow.e2e.yaml

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: workflow.hermes.e2e.yaml - 补全HF环境变量

**Files:**
- Modify: `tests/ut/integration/fixtures/workflow.hermes.e2e.yaml`

- [ ] **Step 1: Add same HF environment variables**

- [ ] **Step 2: Commit**

```bash
git add tests/ut/integration/fixtures/workflow.hermes.e2e.yaml
git commit -m "fix(ut): add full HF env vars to workflow.hermes.e2e.yaml

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: .agents/workflow.yaml - 修复kanban enabled矛盾

**Files:**
- Modify: `.agents/workflow.yaml`

- [ ] **Step 1: Change kanban.enabled to false**

- [ ] **Step 2: Commit**

```bash
git add .agents/workflow.yaml
git commit -m "fix(ut): set kanban.enabled=false to match comment (S7)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: tasks/ut/README.md - 修复skill名称引用

**Files:**
- Modify: `tasks/ut/README.md`

- [ ] **Step 1: Replace ut/workflow with ut/terminal-workflow**

- [ ] **Step 2: Commit**

```bash
git add tasks/ut/README.md
git commit -m "fix(ut): correct skill name from ut/workflow to terminal-workflow (P1)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: 删除孤儿脚本 start_ut_workflow.py

**Files:**
- Delete: `tasks/ut/scripts/start_ut_workflow.py`

- [ ] **Step 1: Remove the file**

```bash
rm tasks/ut/scripts/start_ut_workflow.py
```

- [ ] **Step 2: Commit**

```bash
git add tasks/ut/scripts/start_ut_workflow.py
git commit -m "fix(ut): remove orphan start_ut_workflow.py (S5)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: 验证单元测试全部通过

- [ ] **Step 1: Run all unit tests**

```bash
python -m pytest tests/ut/unit/ -q
```

Expected: 368 passed, 5 skipped, 0 failed

---

## Task 12: 验证E2E测试执行

- [ ] **Step 1: Run L1 smoke test**

```bash
python tests/ut/integration/run_linear_channel.py --workflow-yaml tests/ut/integration/fixtures/workflow.l1.yaml
```

- [ ] **Step 2: Run E2E validation test**

```bash
python tests/ut/integration/run_linear_channel.py --workflow-yaml tests/ut/integration/fixtures/workflow.e2e.yaml
```

---

## Task 13: 推送所有提交

- [ ] **Step 1: Verify commits**

```bash
git log --oneline -10
```

- [ ] **Step 2: Push to origin**

```bash
git push origin master
```

---

*Plan created: 2026-06-28*