---
name: ut-workflow
description: UT Workflow - vLLM单元测试验证流程，加载skill自动启动完整测试流程
version: 5.2.0
when_to_use: 用户需要执行 vLLM 单元测试验证流程（自动执行）
---

# UT Workflow Skill (v5.2)

> **v5.2 更新**: Kanban 集成 - 根据 workflow.yaml kanban.enabled 决定执行模式（线性/Kanban）。

---

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

---

## 执行步骤

### Step 0: 收集用户输入

Agent 主动询问用户三个问题：

| 问题 | 默认值 | 说明 |
|------|--------|------|
| test_list 或 manifest | 无（必填） | `test_list.txt` 或 `manifest.json` 路径 |
| workflow.yaml 路径 | `.agents/workflow.yaml` | 配置文件路径 |
| 断点续跑 run_dir | 无（新建） | 已有 run_dir 路径，跳过 init |

Agent 将用户输入写入 workflow.yaml 的 `input_filter.test_list_path`（或 `manifest_source`）和 `config.resume_from`。

---

### Step 1: 检查前置条件

自动检查：
1. Bastion 连接状态（`python tools/agent.py -p t_h20 ping`）
2. workflow.yaml 文件存在
3. test_list 或 manifest 文件存在
4. 远程容器可访问（`sudo docker exec ... nvidia-smi`）

如果前置条件不满足：
- Bastion 未连接 → 提示：`python tools/agent.py serve t_h20`
- 文件不存在 → 提示用户准备相应文件
- 容器不可用 → 提示检查容器状态

---

### Step 2: 初始化或恢复 workflow_state.json

**新建运行**（`resume_from` 为空）：
```bash
python skills/ut/workflow/scripts/init_workflow_state.py \
  --workflow-yaml WORKFLOW_YAML_PATH
```

**断点续跑**（`resume_from` 指定已有 run_dir）：
- 跳过 `init_workflow_state.py`
- 直接读取 `{resume_from}/workflow_state.json`
- 从 `current_stage` 继续执行
- 已完成 batch 自动跳过（检查 batch_results.json 是否存在）

---

### Step 3: 执行 Stage 1 (collect，一次性)

**断点续跑时**：如果 manifest.json 已存在且 current_stage > collect，跳过。

**新建时**：init_workflow_state.py 已从 test_list.txt 生成 manifest.json，Stage 1 自动完成。

更新 workflow_state.json：
```python
state['current_stage'] = 'select_batch'
```

---

### Step 4: 执行 Workflow 循环 (Stage 2-5)

循环执行直到 `pending_count == 0`：

```
while pending_count > 0:
    iteration += 1

    # 检查 break_conditions
    if error_rate > 0.8 or consecutive_failures > 50:
        发送飞书暂停卡片
        break

    # Stage 2: select_batch（Agent 直接执行，简单逻辑）
    1. 读取 manifest.json
    2. 过滤 pending 测试
    3. 按 batch_size 截取
    4. 创建 batch_dir，写入 batch_config.json
    5. 更新 state

    # Stage 3: execute（远程执行，使用 base64 脚本避免 shell 引号问题）
    远程执行规则：
    - 将 pytest 命令写入 base64 编码的 Python 脚本
    - 通过 agent.py 上传到容器执行
    - 格式: echo <base64> | base64 -d > /tmp/run.py && python3 /tmp/run.py
    - 容器环境变量从 workflow.yaml config.container_env 读取
    - 超时: workflow.yaml stages.execute.timeout (600s)

    # Stage 4: handle_failures（Agent 核心，LLM 判断）
    Agent 自主分析 batch_results.json 中的失败测试：
    1. 读取错误类型和错误消息
    2. 判断是否可修复：
       - 代码 bug → 尝试修改远程文件并重跑
       - 环境问题（网络/模型下载）→ 尝试修复环境
       - 资源问题（GPU/NCCL）→ 标记 ignored
       - 超时 → 标记 ignored
    3. 写入 handled_tests.json
    4. 超时: workflow.yaml stages.handle_failures.timeout (900s)

    # Stage 5: update_status（Agent 直接执行）
    1. 读取 batch_results.json + handled_tests.json
    2. 更新 manifest.json 中对应测试状态
    3. 重新计算 statistics
    4. 写入 manifest.json

    # 从 manifest.json 统一读取 stats（不累加）
    manifest = json.loads(Path(manifest_path).read_text())
    state["stats"] = manifest["statistics"]

    # 更新 workflow_state.json
    state['iteration'] = iteration
    state['current_stage'] = 'select_batch'

    # 推送飞书进度卡片（每个 batch 完成后）
    python skills/ut/workflow/scripts/send_progress_card.py \
        --manifest-path {manifest_path} \
        --feishu-config {workspace}/.agents/feishu_config.json \
        --event progress \
        --batch-id {batch_id} \
        --iteration {iteration}

    # 失败率/错误率告警
    if failure_rate > 0.3 or error_rate > 0.3:
        python skills/ut/workflow/scripts/send_progress_card.py \
            --manifest-path {manifest_path} \
            --feishu-config {workspace}/.agents/feishu_config.json \
            --event alert \
            --batch-id {batch_id} \
            --iteration {iteration} \
            --reason "failure_rate > 30%"
```

---

### Step 5: 完成通知

```bash
python skills/ut/workflow/scripts/send_progress_card.py \
    --manifest-path {manifest_path} \
    --feishu-config {workspace}/.agents/feishu_config.json \
    --event complete \
    --iteration {iteration}
```

---

## 远程执行标准化（base64 方式）

**问题**：PowerShell → agent.py → SSH → bash → docker exec 五层嵌套，引号频繁出错。

**方案**：将远程命令写入 base64 编码的 Python 脚本，消除引号问题。

```python
import subprocess, base64

script = """import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['HF_HOME'] = '/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub'
env['CUDA_VISIBLE_DEVICES'] = '0,1,2,3,4,5,6,7'
cmd = ['python3', '-m', 'pytest', 'test_file.py::test_name', '-q', '--tb=long']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
print(r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-2000:])
"""

encoded = base64.b64encode(script.encode()).decode()
remote_cmd = f'echo {encoded} | base64 -d > /tmp/ut_run.py && python3 /tmp/ut_run.py'

subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '900',
    f'sudo docker exec {container} bash -c "{remote_cmd}"'],
    capture_output=True, text=True, cwd=workspace)
```

---

## 断点续跑

**触发**：用户提供 `resume_from` 路径。

**流程**：
1. 读取 `{resume_from}/workflow_state.json`
2. 检查 `current_stage`：
   - `collect` → 从 Stage 1 开始
   - `select_batch` → 从循环开始
   - 其他 → 从对应 stage 继续
3. 遍历已有 batch 目录，跳过 `batch_results.json` 已存在的 batch
4. 从下一个 pending batch 继续执行

**恢复示例**：
```
用户: 加载 ut/workflow skill
Agent: 请提供 test_list 路径（或 manifest.json 路径）
用户: 断点续跑 D:/workspace/apmm/runs/ut-20260612-101857
Agent: 检测到已有运行目录，共 3 个 batch 已完成，从 batch_4 继续...
```

---

## 路径转义规则

**YAML 中 Windows 路径必须使用正斜杠**：

```yaml
# ✅ 正确
test_list_path: "D:/workspace/apmm/tasks/ut/workflow_tests/test_list.txt"

# ❌ 错误（\t 被解释为 tab）
test_list_path: "D:\workspace\apmm\tasks\ut\workflow_tests\test_list.txt"
```

Agent 在写入 workflow.yaml 时自动将反斜杠转换为正斜杠。

---

## 飞书通知

每个 batch 完成后自动推送一次。通知场景：

| event | 触发条件 | 卡片颜色 |
|-------|---------|:---------:|
| `progress` | 每个 batch 完成 | 🟦 蓝色 |
| `complete` | `pending_count == 0` | 🟩 绿色 |
| `alert` | `failure_rate > 0.3` 或 `error_rate > 0.3` | 🟥 红色 |
| `paused` | `consecutive_failures > 50` 或 `error_rate > 0.8` | 🟨 黄色 |

---

## 超时配置

| 配置项 | 值 | 位置 |
|--------|:--:|:------|
| Stage 3 execute | 600s | `workflow.yaml stages.execute.timeout` |
| Stage 4 failure-handler | 900s | `workflow.yaml stages.handle_failures.timeout` |
| Worker per-stage | 600s | `workflow.yaml execution.worker.timeout_per_stage` |

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

---

## 禁止操作

- ❌ 不执行具体测试任务（让 Worker subagent 执行）
- ❌ 不读取 batch_results.json 详细错误内容
- ❌ 不在 context 中累积历史状态
- ❌ 不硬编码路径（从 workflow_state.json 读取）
- ❌ 不在 YAML 中使用反斜杠路径

---

## 相关文档

- [workflow.yaml](../../.agents/workflow.yaml) - Workflow 配置
- [workflow_state_schema.json](./workflow_state_schema.json) - 状态文件格式
- [ut-test-collector/SKILL.md](../ut-test-collector/SKILL.md) - Stage 1 Worker
- [batch-selector/SKILL.md](../batch-selector/SKILL.md) - Stage 2 Worker
- [unit-test-executor/SKILL.md](../unit-test-executor/SKILL.md) - Stage 3 Worker
- [failure-handler/SKILL.md](../failure-handler/SKILL.md) - Stage 4 Worker
- [manifest-updater/SKILL.md](../manifest-updater/SKILL.md) - Stage 5 Worker

---

*创建日期: 2026-06-06*
*更新日期: 2026-06-12*
*版本: 5.1.0*
