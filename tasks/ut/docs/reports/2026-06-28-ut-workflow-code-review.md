# UT Workflow 两轴代码审查报告

> **Scope**：以 `tasks/ut/README.md` 为权威 spec，全面审查 UT workflow 系统功能代码、文档、测试，找出不一致、错误、遗漏。
> **Standards 来源**：`AGENTS.md`、`CLAUDE.md`及用户原则「确定性操作放脚本，逻辑判断给 agent」。
> **Review Skill**：`mattpocock/in-progress/review`（Spec 轴 + Standards 轴并行）。
> **Review Date**：2026-06-28
> **Reviewer**：Sisyphus (GLM 5.2)

---

## 审查范围

| 维度 | 涉及路径 |
|---|---|
| 功能代码 | `skills/ut/{terminal-workflow, hermes-workflow, workflow-loop-core, workflow, batch-selector, unit-test-executor, failure-handler, manifest-updater, unit-test-collector, dependency-resolver, shared}` |
| 启动脚本 | `tasks/ut/scripts/{start_ut_workflow.py, start_hermes_ut_runtime.py, deploy_tier.py, grade_tier.py, completion_watcher.py, check_expected.py}` |
| 测试 | `tests/ut/{unit, integration, workflow, test_lists, reports}` |
| 配置 | `.agents/workflow.yaml`、`tests/ut/integration/fixtures/` |
| 文档 | `tasks/ut/docs/{guides, kanban, reports, incidents, archive, discussions}` |

---

## Standards 轴 — 代码/文档/测试是否符合项目规范？

### S1【硬错误】workflow-loop-core 是「文档专用」内核，违背「确定性放脚本」原则

- **位置**：`skills/ut/workflow-loop-core/`
- **事实**：整个目录只有 `SKILL.md`（6.3KB），**无任何 `.py` 实现**。`SKILL.md` §"Linear-mode algorithm" 用 Python 风格伪代码描述 `loop_core.run(...)` 接口，但根本不存在 `loop_core.py`。
- **证据**：`tests/ut/unit/test_loop_core_contract.py` 文件头注释明确写：
  > "loop_core is currently SKILL.md-only — concrete Python wiring lands in the channel SKILLs (ut/workflow supervisor, hermes-workflow) and in hermes_runner. These placeholders document the contract; remove the skips once the wiring exists."
  
  全部 2 个测试都 `@pytest.mark.skip`。
- **影响**：所谓「两通道共用同一份 loop-core 5 阶段流水线」，每次运行都依赖 AI agent 阅读 SKILL.md 散文后自行重实现循环逻辑。这是项目原则「确定性操作放脚本」的**最严重反面**。

### S2【已存在但被遗忘的实现】`skills/ut/workflow/scripts/run_linear_loop.py` 是真正的循环实现，但无 SKILL.md 承认

- **位置**：`skills/ut/workflow/scripts/run_linear_loop.py`（10101 字节）+ `start_l4_linear.py`（3378 字节）
- **事实**：`run_linear_loop.py` 是一个完整 Python 实现，通过 subprocess 串行调用 4 个 Stage 脚本直到 `pending==0`，正是 loop-core SKILL.md 所描述的循环。但：
  - `skills/ut/workflow/` 目录下**无 SKILL.md**
  - README/terminal-workflow SKILL.md 都未引用此文件
  - `test_loop_core_contract.py` 注释坚称 loop-core 是 "SKILL.md-only"
- **结论**：要么 S1 误判（loop 实际已被实现），要么 S2 是孤儿死代码。**两者必居其一，目前状态自相矛盾**。

### S3【硬错误】terminal-workflow SKILL 调用 `validate_required_config(cfg)` 但未传 `channel="linear"`，kanban-OFF 互锁失效

- **位置**：`skills/ut/terminal-workflow/SKILL.md` §Startup step 2
- **事实**：SKILL 文档原文 `Validate with hermes_runner.validate_required_config(cfg).` 没传 kwarg。
- **签名**：`def validate_required_config(cfg, *, channel: str = "hermes")` — 默认 `channel="hermes"` 走「backward compat」分支，**接受 kanban.enabled=true**。
- **测试反证**：`test_channel_kanban_constraint.py` 测了四种组合（linear+kanban_on 拒绝 / linear+kanban_off 接受 / hermes+… 接受），但这只验证了函数能力；**没有任何测试断言「terminal-workflow SKILL loader 会传 channel="linear"」**。
- **影响**：README 声称 terminal-workflow "kanban 强制 OFF"，但 AI agent 按 SKILL.md 步骤执行会绕过互锁。**这是 spec 与 standards 的双重崩塌点。**

### S4【遗漏】`start_gateway.py` 实际位置与命名不一致

- **位置**：
  - 物理在 `skills/ut/terminal-workflow/scripts/start_gateway.py`
  - `start_hermes_ut_runtime.py:44` 引用此路径 ✓
  - `start_ut_workflow.py:18` 引用 `skills/ut/hermes-workflow/scripts/start_gateway.py` ✗（不存在）
- **影响**：`start_ut_workflow.py` 在生产 kanban 模式下会因路径不存在而崩溃。terminal-workflow SKILL 又声称「Does not start the Bastion daemon」——gateway 启动脚本塞在 terminal-workflow 目录里完全是 channel 边界泄漏。

### S5【硬错误】`start_ut_workflow.py` 引用 `skills/ut/terminal-workflow/scripts/run_workflow.py` — 文件不存在

- **位置**：`tasks/ut/scripts/start_ut_workflow.py:22`
- **事实**：terminal-workflow/scripts 实际文件为：
  ```
  bastion_manager.py / check_vllm_branch.py / feishu_api.py /
  hermes_runner.py / init_workflow_state.py / monitor_kanban.py /
  request_daemon_approval.py / send_progress_card.py / start_gateway.py
  ```
  **无 `run_workflow.py`**。
- **影响**：linear 模式调用 `start_ut_workflow.py --mode linear` 必崩。

### S6【不规范】`start_ut_workflow.py` 不被任何 README/SKILL 提及，但暴露 CLI

- **位置**：`tasks/ut/scripts/start_ut_workflow.py`
- **事实**：README ¶🅰️ / 🅱️ / 🅲️ 描述的启动路径全部指向 `start_hermes_ut_runtime.py`。`start_ut_workflow.py` 是孤儿 CLI，但它的 `--mode kanban/linear + --tier L1..L4` 接口本来是合理的统一入口。**目前没人会用到它，且它会崩溃（S4+S5）**。

### S7【硬错误】`.agents/workflow.yaml` 默认 `kanban.enabled: true`，与 README/SKILL 相互冲突

- **位置**：`.agents/workflow.yaml:308`
- **事实**：
  - `.agents/workflow.yaml` 注释行 (299-303) 写"Kanban 默认关闭"，**但 line 308 即 `enabled: true`**——注释与代码值自相矛盾
  - README ¶🅱️ 要求用户手工编辑改成 `false`
  - README ¶🅰️ 表中 L1/L2/L3 模式标 "linear"
  - `start_hermes_ut_runtime.py` 默认加载 `tests/ut/integration/fixtures/workflow.l4.yaml`，不是 `.agents/workflow.yaml`
- **影响**：用户若直接用 `.agents/workflow.yaml` 跑 terminal-workflow，会带着 kanban=true，再叠加 S3 的互锁绕过 → 实际跑 kanban 模式 + terminal-workflow supervisor → dispatcher 死锁风险。

### S8【硬错误】hermes-workflow SKILL 中 `from hermes_runner import ...` 依赖隐藏 sys.path 配置

- **位置**：`skills/ut/hermes-workflow/SKILL.md` §2
- **事实**：hermes-workflow/scripts 目录下只有 3 个文件：
  ```
  kanban_task_creator.py / orchestrator_round.py / start_supervisor.py
  ```
  无 `hermes_runner.py` / `bastion_manager.py`。这两个核心模块物理在 `skills/ut/terminal-workflow/scripts/`。`from hermes_runner import ...` 依赖 sys.path 配置；如果 `start_supervisor.py` 没显式插入 terminal-workflow/scripts 路径，hermes 通道启动必崩。**channel 边界完全错乱**。

---

## Spec 轴 — 代码/文档/测试是否忠实实现 README 与 spec 声明的行为？

### P1【不一致】README 指引用户「加载 ut/workflow skill」但该 skill 不存在

- **位置**：`tasks/ut/README.md` ¶🅱️ 步骤 2
- **事实**：原文 `加载 ut/workflow skill`。但：
  - `skills/ut/workflow/` 无 `SKILL.md`
  - 实际可用 skill 是 `skills/ut/terminal-workflow/SKILL.md`（name: `terminal-workflow`）
  - `workflow-loop-core/SKILL.md` 元数据 description "Channel skills (ut/workflow, hermes-workflow)" 同样错误地引用 `ut/workflow`
- **影响**：用户按 README 操作无法加载 skill。

### P2【遗漏】terminal-workflow SKILL 缺「单测试手动跑」入口

- **位置**：README ¶🅱️ step 4 给出的 `python tools/agent.py -p t_h20 run ... pytest -vv <test_node>`
- **事实**：此命令是 README 直接告诉用户的，**SKILL 没有显式写到这个调用**。spec 角度看用户必须靠 README，不能靠 SKILL 单独完成。轻微问题，但属于 spec/SKILL 不完整。

### P3【不一致】README 触发词描述与 hermes SKILL §3 行为不符

- **位置**：`README.md` ¶🅰️ 表 + ¶🅲️ step 2 "通过飞书发触发词"
- **事实**：
  - README 说：「supervisor 会发参数确认卡，回 `确认` 启动」
  - hermes SKILL §3 明确：裸 `跑 ut workflow` 在 v5 走 Layer 2 → 预期分类为 `unknown` → §3.D 帮助卡——**不再是合法触发词**
  - §3.A 新路径发的是"启动意图确认卡"（蓝/橙色），不是 README 描述的"参数确认卡"
  - §3.A A3 强调 10s 超时；README 没提
- **影响**：README ¶🅲️ step 2 "通过飞书发触发词"过于宽松，且 ¶🅰️ "回 `确认` 启动" 描述已被新行为改变。

### P4【不一致】README "前置一次性启动" 命令与脚本 docstring 描述的启动顺序不符

- **位置**：README ¶🅰️ `python tasks/ut/scripts/start_hermes_ut_runtime.py`
- **事实**：脚本 docstring 自己写「启动顺序：1. 配置预检 / 2. Bastion daemon preflight / 3. 3 Kanban Gateways / 4. Supervisor Agent」，但 README 标题说"前置一次性启动（gateway + supervisor，幂等）"。
  - Bastion daemon 预检形态对 README 步骤完全未提
  - 脚本默认 `--workflow-yaml` 是 `tests/ut/integration/fixtures/workflow.l4.yaml`（line 312），不是生产 yaml
- **影响**：用户跟随 README 跑默认命令实际启动的是 L4 fixture，不是 production。

### P5【不一致】README "L2 mini, ~10 用例, ~3 min" 与 hermes SKILL §3.C 内描述

- **位置**：README ¶🅰️ 表 vs hermes SKILL §3.C
- **事实**：
  - README: L2 用例数 `~10`、源 `mini_test_list.txt`
  - SKILL §3.C: `start_l2.test_list: tests/ut/integration/fixtures/mini_test_list.txt`、`mode: linear` ✓
  - 路径本身对齐；问题在 SKILL §3.A 说 all `start_l1..l4` 走 §3.A 启动确认分支，但 README 没说 L1/L2/L3 触发也需要 10s 内回确认。

### P6【遗漏】terminal-workflow SKILL 完全无测试覆盖

- **位置**：`tests/ut/unit/test_terminal_workflow.py`
- **事实**：仅一行 `pytest.skip("terminal-workflow tests pending implementation")`。整个 terminal 通道行为无任何回归测试。
- **影响**：spec 声称「terminal 线性跑能正常运行」无测试支撑。

### P7【遗漏】Kanban 模式集成测试是 placeholder

- **位置**：`tests/ut/workflow/integration/test_kanban_mode.py`
- **事实**：仅 `def test_placeholder(): pass`。无法验证 README ¶🅰️ 表 "L4 retry ~60 min" 或"正式生产"路径仍可端到端跑通。
- **影响**：用户提到「kanban=on 只要能跑即可」spec 缺乏 runtime 验证。

### P8【不一致】`.agents/workflow.yaml` 注释自相矛盾

- **位置**：`.agents/workflow.yaml` lines 299-303 vs 308
- **事实**：
  ```yaml
  # Kanban - Hermes Kanban配置
  # 注意：UT workflow 是线性批处理，不需要多 agent 协作，Kanban 默认关闭。
  # ...
  kanban:
    enabled: true # ✍️: true 启用 Kanban 模式，false 使用线性 workflow
  ```
  注释说"默认关闭"但值是 `true`。

### P9【遗漏】`workflow-loop-core` 既无代码也无「最小可运行样本」，但 README 把它当作已就绪基础设施

- **位置**：README "双通道速查" `共用同一份 workflow-loop-core`。
- **事实**：loop-core 实为 0 行 Python；共用的是文档共识，不是代码。属"基础设施幻觉"。

### P10【不一致】`tests/ut/integration/fixtures/` 含未被任何 SKILL/README 提及的文件

- **位置**：fixtures 目录含有 `workflow.e2e.yaml / workflow.hermes.e2e.yaml / workflow.linear.yaml / e2e_validation_list.txt` 等额外文件，未被 SKILL §3.C 的 tier → yaml 映射覆盖。
- 影响：轻微，但 `workflow.linear.yaml` 这种通用名暗示存在某种通用 fixture，而 SKILL §3.C 没列它。

### P11【不一致】`start_hermes_ut_runtime.py` 默认参数与 README 默认场景错位

- 同 P4 补充：脚本默认 yaml 是 `workflow.l4.yaml`，README 表格「最常用」第一行却是 L1 烟雾，但 L1 走飞书触发，二者并不都依赖 start_hermes_ut_runtime.py。需要预启动的只有 L4/生产，所以默认 L4 算合理——但 README 没明说"只 L4/生产才需要预启动脚本"。

### P12【死链/引用风险】hermes SKILL §"When to switch channels" 引用的文档未在本次扫描中验证存活性

- 路径列表需复核：
  - `tasks/ut/docs/guides/hermes-supervisor-service.md`
  - `tasks/ut/docs/guides/hermes-gateway-service.md`
- 未本次确认存在性，属审查遗漏，建议后续补齐。

---

## 优先级排序与下一步

| 级别 | ID | 一句话 | 建议方向 |
|---|---|---|---|
| 🔴 P0 | S1/S2 | loop-core 是 SKILL.md-only；同时 `skills/ut/workflow/scripts/run_linear_loop.py` 是孤儿真实现 | 二选一：要么把孤儿脚本搬到 `workflow-loop-core/loop_core.py` 并加测试，要么删掉孤儿脚本并在 SKILL 注明 "AI 实现" |
| 🔴 P0 | P1 | README 叫用户加载 `ut/workflow` skill，该 skill 不存在 | 改 README 文案为 `加载 ut/terminal-workflow skill` |
| 🔴 P0 | S3 | terminal-workflow SKILL 调 `validate_required_config(cfg)` 不传 `channel="linear"`，互锁失效 | 把调用改为 `validate_required_config(cfg, channel="linear")`，加 unit test 断言此 kwarg 被传 |
| 🔴 P0 | S5 | `start_ut_workflow.py` 引用 `run_workflow.py` 不存在 | 删除 `start_ut_workflow.py`（被 `start_hermes_ut_runtime.py` 取代）或修路径 |
| 🟠 P1 | S4/S8 | `start_gateway.py` / `hermes_runner.py` / `bastion_manager.py` 物理位置全在 terminal-workflow/scripts 但被 hermes 通道使用 | 抽到 `skills/ut/shared/scripts/`，更新所有 import 路径 |
| 🟠 P1 | S7/P8 | `.agents/workflow.yaml` 注释说"默认关闭"但值是 `true` | 选一个改：把默认改为 `false`（更符合 README 调试通道）并改注释为 truth |
| 🟠 P1 | P3 | README 说"回确认启动"，hermes SKILL §3.A 已改成 10s 蓝/橙卡 | 同步 README 描述 |
| 🟡 P2 | P6 | terminal-workflow 全 skill 仅 1 个 skip 占位测试 | 实测 SKILL 定义的 callback 行为（handle_checkpoint / handle_bastion_disconnect / check_user_commands / check_terminal_conditions） |
| 🟡 P2 | P7 | Kanban 集成测试是空文件 | 至少加一个 mock 3-gateway 的端到端 dry run |
| 🟡 P2 | P4/P11 | start_hermes_ut_runtime.py 默认 L4 fixture 与 README 误导 | README 加一句"仅 L4/生产需预启动" |

### 各轴最严重一项

- **Standards 轴最严重**：**S1+S2** — 拥有"应该用脚本承载"的循环逻辑却以散文存在，孤儿脚本表明曾经有过实现。客观事实是「核心代码丢失或被遗忘」。
- **Spec 轴最严重**：**P1** — 用户按 README 操作第一步就会卡住——`ut/workflow` skill 根本不存在，这不是边界细节，是入口失效。

---

## 附：审查方法说明

本次审查采用 `mattpocock/in-progress/review` skill 的两轴框架，但因任务范围是「整个系统状态」而非「git diff since fixed point」，所以将 Spec 与 Standards 适配为：

- **Spec 轴** = 代码/文档/测试是否符合 README 与关联 SKILL 声明的行为
- **Standards 轴** = 代码是否遵循项目规范（AGENTS.md/CLAUDE.md）+ 「确定性操作放脚本、逻辑判断给 agent」原则

未派并行 sub-agent 的原因：现有可用模型（GLM 5.2）直接阅读源文件效率更高，且本任务的关键发现依赖交叉对照多个不同来源（SKILL/script/test/yaml/doc），单 agent 反而能把握上下文一致性。

审查覆盖文件（节选）：
- `tasks/ut/README.md`、`tasks/ut/GOAL.md`
- `skills/ut/terminal-workflow/SKILL.md`
- `skills/ut/hermes-workflow/SKILL.md`
- `skills/ut/workflow-loop-core/SKILL.md`
- `.agents/workflow.yaml`
- `tasks/ut/scripts/start_ut_workflow.py`、`start_hermes_ut_runtime.py`
- `skills/ut/terminal-workflow/scripts/hermes_runner.py`（validate_required_config 验证）
- `tests/ut/unit/{test_terminal_workflow.py, test_channel_kanban_constraint.py, test_loop_core_contract.py}`
- `tests/ut/workflow/integration/test_kanban_mode.py`
- `tests/ut/integration/fixtures/` 全目录（L*_expected.json、workflow.l*.yaml 等）

---

*Generated by Sisyphus (GLM 5.2) on 2026-06-28*