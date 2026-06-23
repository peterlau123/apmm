# UT Workflow × Hermes Kanban 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 UT Workflow 与 Hermes Kanban 的集成，支持双模式运行（线性 workflow / Kanban 模式）。

**Architecture:** 方案 A-1 Skill 分支模式 - 单一 SKILL.md 根据 workflow.yaml 的 kanban.enabled 决定执行路径。Kanban 模式下 Agent 自动启动 3 个 Gateway 并创建初始任务。

**Tech Stack:** Python, YAML, Hermes CLI (hermes gateway/kanban/profile)

---

## 文件结构

| 文件 | 操作 | 负责 |
|------|------|------|
| `skills/ut/workflow/SKILL.md` | 修改 | 版本更新 + 引导流程简化 + Kanban 分支逻辑 |
| `.agents/workflow.yaml` | 修改 | 更新 kanban 节点配置结构 |
| `skills/ut/workflow/scripts/start_gateway.py` | 创建 | Gateway 启动脚本（检测、启动、健康检查） |
| `skills/ut/workflow/scripts/monitor_kanban.py` | 创建 | Kanban 监控脚本（轮询 stats、完成检测） |

---

### Task 1: 更新 workflow.yaml Kanban 配置

**Files:**
- Modify: `.agents/workflow.yaml:254-330` (现有 kanban 节点)

- [ ] **Step 1: 编辑 kanban 节点配置**

将现有 kanban 节点（第 254-330 行）替换为：

```yaml
# ============================================================
# Kanban - Hermes Kanban 配置（方案 A-1）
# ============================================================
kanban:
  enabled: false  # ✍️: true 启用 Kanban 模式，false 使用线性 workflow

  # Board 配置
  board:
    name: "apmm-ut"
    slug: "apmm-ut"

  # Worker Profile 配置
  profiles:
    orchestrator: "ut-orchestrator"
    executor: "ut-executor"
    fixer: "ut-fixer"

  # Gateway 启动配置
  gateway:
    auto_start: true           # Agent 自动启动 gateway
    check_interval: 60         # 调度检查间隔（秒）
    startup_timeout: 30        # gateway 启动超时（秒）

  # 熔断器配置
  circuit_breaker:
    failure_limit: 3           # 连续失败 N 次后自动 block
    error_rate_threshold: 0.8  # 错误率阈值

  # 任务创建配置
  task_creation:
    initial_assignee: "ut-orchestrator"
    priority: 1
    body_template: "Orchestrate UT run for {test_list_path}"
```

- [ ] **Step 2: 验证 YAML 格式**

```bash
python -c "import yaml; yaml.safe_load(open('.agents/workflow.yaml'))"
```

Expected: 无错误输出

- [ ] **Step 3: Commit**

```bash
git add .agents/workflow.yaml
git commit -m "feat: update kanban config structure for A-1 integration"
```

---

### Task 2: 更新 SKILL.md 版本和引导流程

**Files:**
- Modify: `skills/ut/workflow/SKILL.md:1-50` (frontmatter + 触发方式部分)

- [ ] **Step 1: 更新 frontmatter 版号**

修改第 4 行版本和第 8 行标题：

```yaml
version: 5.2.0
```

```markdown
# UT Workflow Skill (v5.2)

> **v5.2 更新**: Kanban 集成 - 根据 workflow.yaml kanban.enabled 决定执行模式（线性/Kanban）。
```

- [ ] **Step 2: 修改触发方式部分（第 14-25 行）**

替换为：

```markdown
## 🚀 触发方式

用户加载 skill 后，Agent 自动引导用户完成配置并执行流程：

```
用户: 加载 ut/workflow skill
Agent: UT Workflow v5.2 已加载。
       请提供以下信息：
       1. workflow.yaml 是否已准备好？（test_list、batch_size 等参数已填写）
       2. workflow.yaml 路径（默认: .agents/workflow.yaml）
       3. 是否断点续跑？（提供 run_dir 路径，或留空新建）
```

Agent 检查 workflow.yaml 中 `kanban.enabled`：
- **false** → 执行线性 workflow（现有流程）
- **true** → 执行 Kanban workflow（新流程，见下方）
```

- [ ] **Step 3: Commit**

```bash
git add skills/ut/workflow/SKILL.md
git commit -m "feat: update SKILL.md v5.2 - simplify prompt flow"
```

---

### Task 3: 增加 Kanban 分支逻辑到 SKILL.md

**Files:**
- Modify: `skills/ut/workflow/SKILL.md` (在文件末尾增加 Kanban 模式部分)

- [ ] **Step 1: 在 SKILL.md 末尾增加 Kanban 模式部分**

在 `## 禁止操作` 部分之前插入：

```markdown
---

## Kanban 模式执行步骤（kanban.enabled = true）

### Step K0: 检查前置条件

Agent 检查以下条件是否满足：

1. Hermes Agent v0.15.1+ 已安装
   ```bash
   hermes version  # 检查版本
   ```
   不满足 → 提示用户安装 Hermes Agent

2. Board `apmm-ut` 已创建
   ```bash
   hermes kanban boards list | grep apmm-ut
   ```
   不满足 → 提示用户执行:
   ```bash
   hermes kanban boards create apmm-ut --name "APMM UT Workflow"
   ```

3. 3 个 worker profile 已配置
   ```bash
   hermes profile list | grep ut-orchestrator
   hermes profile list | grep ut-executor
   hermes profile list | grep ut-fixer
   ```
   不满足 → 提示用户参考 tasks/ut/docs/kanban/README.md 创建 profile

### Step K1: 启动 Gateway

Agent 执行启动脚本：

```bash
python skills/ut/workflow/scripts/start_gateway.py --workflow-yaml .agents/workflow.yaml
```

脚本行为：
1. 切换到目标 board
2. 启动 3 个 Gateway（orchestrator/executor/fixer）后台进程
3. 等待 gateway 就绪
4. 返回启动状态 JSON

### Step K2: 创建初始任务

Agent 创建 Orchestrator 任务：

```bash
hermes kanban create "Orchestrate UT run" --assignee ut-orchestrator --priority 1
```

任务触发依赖链：Orchestrator → Executor → Fixer

### Step K3: 监控进度

Agent 执行监控脚本：

```bash
python skills/ut/workflow/scripts/monitor_kanban.py --workflow-yaml .agents/workflow.yaml --poll-interval 60
```

脚本轮询 `hermes kanban stats` 直到所有任务完成。

### Step K4: 完成通知

发送飞书通知，Gateway 保持运行（不自动关闭）。
```

- [ ] **Step 2: Commit**

```bash
git add skills/ut/workflow/SKILL.md
git commit -m "feat: add Kanban mode execution steps to SKILL.md"
```

---

### Task 4: 创建 start_gateway.py 脚本

**Files:**
- Create: `skills/ut/workflow/scripts/start_gateway.py`

- [ ] **Step 1: 创建脚本文件**

```python
#!/usr/bin/env python3
"""start_gateway.py - 启动 Hermes Kanban Gateway"""

import subprocess, sys, time, argparse, yaml, json
from pathlib import Path

def run_cmd(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

def check_hermes_version():
    r = run_cmd("hermes version")
    if r.returncode != 0:
        print("ERROR: Hermes not installed")
        return False
    print(f"Hermes version: {r.stdout.strip()}")
    return True

def switch_board(slug):
    r = run_cmd(f"hermes kanban boards switch {slug}")
    if r.returncode != 0:
        print(f"ERROR: Failed to switch board: {slug}")
        return False
    print(f"Switched to board: {slug}")
    return True

def start_gateway(profile):
    cmd = f"nohup hermes profile use {profile} && hermes gateway run > /tmp/gateway_{profile}.log 2>&1 &"
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Started gateway: {profile}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-yaml", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.workflow_yaml).read_text())
    kanban = config.get("kanban", {})
    if not kanban.get("enabled", False):
        print("INFO: Kanban not enabled, skipping")
        sys.exit(0)

    board = kanban.get("board", {}).get("slug", "apmm-ut")
    profiles = kanban.get("profiles", {})
    targets = [profiles.get("orchestrator", "ut-orchestrator"),
               profiles.get("executor", "ut-executor"),
               profiles.get("fixer", "ut-fixer")]

    if not check_hermes_version(): sys.exit(1)
    if not switch_board(board): sys.exit(1)

    for p in targets:
        start_gateway(p)

    time.sleep(5)
    result = {"status": "started", "board": board, "profiles": targets}
    print(f"JSON_OUTPUT: {json.dumps(result)}")
    sys.exit(0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证语法**

```bash
python -m py_compile skills/ut/workflow/scripts/start_gateway.py
```

- [ ] **Step 3: Commit**

```bash
git add skills/ut/workflow/scripts/start_gateway.py
git commit -m "feat: add start_gateway.py for Kanban gateway startup"
```

---

### Task 5: 创建 monitor_kanban.py 脚本

**Files:**
- Create: `skills/ut/workflow/scripts/monitor_kanban.py`

- [ ] **Step 1: 创建脚本文件**

```python
#!/usr/bin/env python3
"""monitor_kanban.py - 监控 Hermes Kanban 任务状态"""

import subprocess, sys, time, argparse, yaml, json
from pathlib import Path

def run_cmd(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

def get_stats(board):
    r = run_cmd(f"hermes kanban stats --board {board}")
    if r.returncode != 0:
        return {"error": r.stderr}
    try:
        return json.loads(r.stdout)
    except:
        stats = {}
        for line in r.stdout.split("\n"):
            if ":" in line:
                k, v = line.split(":")
                stats[k.strip()] = v.strip()
        return stats

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-yaml", required=True)
    parser.add_argument("--poll-interval", type=int, default=60)
    parser.add_argument("--max-wait", type=int, default=3600)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.workflow_yaml).read_text())
    board = config.get("kanban", {}).get("board", {}).get("slug", "apmm-ut")

    print(f"Monitoring board: {board}")
    start = time.time()

    while time.time() - start < args.max_wait:
        stats = get_stats(board)
        if "error" in stats:
            print(f"ERROR: {stats['error']}")
            sys.exit(1)

        pending = stats.get("pending", 0)
        running = stats.get("running", 0)
        print(f"Stats: done={stats.get('done')}, pending={pending}, running={running}")

        if pending == 0 and running == 0:
            print("All tasks completed")
            result = {"status": "completed", "board": board, "stats": stats}
            print(f"JSON_OUTPUT: {json.dumps(result)}")
            sys.exit(0)

        time.sleep(args.poll_interval)

    print("WARN: Max wait exceeded")
    sys.exit(2)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证语法**

```bash
python -m py_compile skills/ut/workflow/scripts/monitor_kanban.py
```

- [ ] **Step 3: Commit**

```bash
git add skills/ut/workflow/scripts/monitor_kanban.py
git commit -m "feat: add monitor_kanban.py for Kanban task monitoring"
```

---

### Task 6: 更新文档链接和日期

**Files:**
- Modify: `skills/ut/workflow/SKILL.md` (相关文档部分)

- [ ] **Step 1: 增加文档链接**

在 `## 相关文档` 部分增加：

```markdown
- [Kanban集成指南](../../../tasks/ut/docs/kanban/README.md)
- [Kanban集成设计](../../../tasks/ut/docs/designs/2026-06-12-ut-workflow-kanban-integration-design.md)
```

- [ ] **Step 2: 更新日期**

```markdown
*版本: 5.2.0*
*更新日期: 2026-06-12*
```

- [ ] **Step 3: Commit**

```bash
git add skills/ut/workflow/SKILL.md
git commit -m "docs: add Kanban integration links and update date"
```

---

### Task 7: 最终验证

- [ ] **Step 1: 检查所有修改已 commit**

```bash
git status
```

- [ ] **Step 2: 验证 YAML 和 Python**

```bash
python -c "import yaml; yaml.safe_load(open('.agents/workflow.yaml'))"
python -m py_compile skills/ut/workflow/scripts/start_gateway.py
python -m py_compile skills/ut/workflow/scripts/monitor_kanban.py
```

---

*创建日期: 2026-06-12*