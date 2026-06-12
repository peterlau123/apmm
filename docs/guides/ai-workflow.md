# AI Agent 工作流程规范

> 本文档定义 OpenCode 在本项目中的标准工作模式，固化 Brainstorming + Verification Loop 流程。

---

## 工作模式总览

OpenCode 默认采用 **Brainstorming → Planning → Execution → Verification** 四阶段流程：

```
Phase 1: Understanding  →  收集需求、约束、成功标准
Phase 2: Exploration    →  提出多个方案、评估trade-offs
Phase 3: Design         →  分段呈现设计、逐步验证
Phase 4: Planning       →  创建实施计划、分解任务
Phase 5: Execution      →  按计划实施、每步验证
Phase 6: Verification   →  Build/Type/Lint/Test/Security/Diff 全面检查
```

---

## Phase 1-3: Brainstorming（思考阶段）

### 触发条件

当用户提出任何功能需求、改进想法、架构变更时，**必须先执行 Brainstorming**，不能直接跳到实施。

### Phase 1: Understanding（理解）

**目标**：清晰理解用户意图、约束和成功标准。

**行为**：
- 检查项目当前状态（读取关键文件、了解现有架构）
- **一次只问一个问题**（避免信息过载）
- 优先使用多选题形式
- 收集：目的、约束条件、成功标准

**输出**：
```markdown
## Understanding Summary
- Purpose: [用户想达成什么]
- Constraints: [技术/时间/资源约束]
- Success Criteria: [如何判断成功]
- Current State: [项目现状]
```

### Phase 2: Exploration（探索）

**目标**：提出多个可行方案，暴露 trade-offs。

**行为**：
- 提出 **2-3 个不同方案**（不能只给一个）
- 对每个方案描述：
  - 核心架构
  - Trade-offs（优缺点）
  - 复杂度评估
- 询问用户选择哪个方案

**输出示例**：
```markdown
## Approach Options

### Option A: [方案名称]
- Architecture: [简要架构]
- Pros: [优势列表]
- Cons: [劣势列表]
- Complexity: [低/中/高]

### Option B: [方案名称]
...

### Option C: [方案名称]
...

Question: Which approach resonates with you?
```

### Phase 3: Design Presentation（设计呈现）

**目标**：分段呈现设计细节，逐步获得用户确认。

**行为**：
- **每段 200-300 字**（避免一次性输出太多）
- 涵盖：架构、组件、数据流、错误处理、测试策略
- **每段后询问**："Does this look right so far?"

**输出示例**：
```markdown
## Design Section 1: Architecture

[200-300字架构描述]

**Question**: Does this architecture look right so far?

---

## Design Section 2: Components

[200-300字组件描述]

**Question**: Does this component design look right so far?
```

### Phase 4: Planning Handoff（计划移交）

**触发**：设计获得用户认可后。

**行为**：
- 询问："Ready to create the implementation plan?"
- 用户确认后，切换到 `Writing Plans` skill
- 创建详细的实施计划

---

## Phase 5: Execution（实施阶段）

### 触发条件

计划创建完成并获得认可后，进入实施阶段。

### 行为原则

1. **按计划顺序执行**（不能跳步）
2. **每步完成后验证**（运行测试/检查结果）
3. **遇到阻塞立即上报**（不要自己改计划）
4. **记录进度**（标记已完成的任务）

### 执行流程

```markdown
1. Read plan → 理解所有步骤
2. Execute task 1 → 完成第一个任务
3. Verify → 测试/验证结果
4. Mark complete → 标记完成
5. Proceed next → 验证通过后才继续
6. Handle blockers → 阻塞时更新计划或请求帮助
```

---

## Phase 6: Verification Loop（验证阶段）

### 触发条件

**必须触发**：
- 完成功能或重要代码变更后
- 创建 PR 前
- 重构后

**可选触发**：
- 长会话中每 15 分钟
- 完成每个函数/组件后

### 验证流程（6个Phase）

#### Phase 1: Build Verification

```bash
# 检查项目构建
npm run build 2>&1 | tail -20
# OR
pnpm build 2>&1 | tail -20
```

**规则**：构建失败 → **STOP**，修复后继续。

#### Phase 2: Type Check

```bash
# TypeScript 项目
npx tsc --noEmit 2>&1 | head -30

# Python 项目
pyright . 2>&1 | head -30
```

**规则**：报告所有类型错误，修复关键错误后继续。

#### Phase 3: Lint Check

```bash
# JavaScript/TypeScript
npm run lint 2>&1 | head -30

# Python
ruff check . 2>&1 | head -30
```

#### Phase 4: Test Suite

```bash
# 运行测试 + 覆盖率
npm run test -- --coverage 2>&1 | tail -50

# 检查覆盖率阈值（目标：80% minimum）
```

**报告**：
- Total tests: X
- Passed: X
- Failed: X
- Coverage: X%

#### Phase 5: Security Scan

```bash
# 检查敏感信息泄露
grep -rn "sk-" --include="*.ts" --include="*.js" . 2>/dev/null | head -10
grep -rn "api_key" --include="*.ts" --include="*.js" . 2>/dev/null | head -10

# 检查 console.log
grep -rn "console.log" --include="*.ts" --include="*.tsx" src/ 2>/dev/null | head -10
```

#### Phase 6: Diff Review

```bash
# 查看变更
git diff --stat
git diff HEAD~1 --name-only
```

**审查每个变更文件**：
- 无意变更？
- 缺少错误处理？
- 潜在边界情况？

### Verification Report 输出格式

```markdown
VERIFICATION REPORT
==================

Build:     [PASS/FAIL]
Types:     [PASS/FAIL] (X errors)
Lint:      [PASS/FAIL] (X warnings)
Tests:     [PASS/FAIL] (X/Y passed, Z% coverage)
Security:  [PASS/FAIL] (X issues)
Diff:      [X files changed]

Overall:   [READY/NOT READY] for PR

Issues to Fix:
1. [问题描述]
2. [问题描述]
```

---

## 强制执行规则

### ❌ 禁止跳过 Brainstorming

当用户提出需求时，**不能直接开始编码**：
- 必须先 Phase 1-3（Understanding → Exploration → Design）
- 必须获得用户确认后才进入 Planning

### ❌ 禁止跳过 Verification

完成重要变更后，**不能直接结束会话或创建 PR**：
- 必须运行 Verification Loop Phase 1-6
- 必须报告结果，修复所有 FAIL 问题

### ❌ 禁止跳步执行

在 Execution 阶段，**不能跳过计划中的任务**：
- 必须按顺序执行
- 必须每步验证
- 阻塞时必须上报，不能自己改计划

---

## 特殊情况处理

### 简单任务（无需 Brainstorming）

以下任务可以跳过 Brainstorming，但仍需 Verification：
- 单行代码修改（bug fix）
- 配置文件更新
- 文档 typo 修复
- 明确的单文件重构

判断标准：**30分钟内可完成，影响范围明确**。

### 紧急修复（部分流程）

生产环境紧急问题：
- 可跳过 Brainstorming（Phase 1-3）
- 仍需 Planning（Phase 4）— 但可以简化（列出关键步骤）
- 必须 Verification（Phase 6）

### 探索性任务（全流程）

当用户说"我不确定怎么做"、"帮我想想"：
- **必须完整 Brainstorming**
- Phase 1 需要更深入理解
- Phase 2 需要更多方案探索

---

## 实施检查清单

### Before Coding

- [ ] Phase 1: Understanding 完成？用户意图清晰？
- [ ] Phase 2: Exploration 完成？至少提出 2 个方案？
- [ ] Phase 3: Design 完成？获得用户确认？
- [ ] Phase 4: Planning 完成？计划获得认可？

### During Coding

- [ ] 按计划顺序执行？
- [ ] 每步完成后验证？
- [ ] 遇到阻塞上报？
- [ ] 进度已记录？

### After Coding

- [ ] Phase 6: Verification Loop 完成？
- [ ] Build: PASS？
- [ ] Types: PASS（或关键错误已修复）？
- [ ] Tests: PASS（覆盖率达标）？
- [ ] Security: PASS（无敏感信息泄露）？
- [ ] Verification Report 已生成？

---

## 相关 Skills

| Skill | 用途 | Phase |
|-------|------|-------|
| Brainstorming Ideas Into Designs | 思考阶段 | Phase 1-3 |
| Writing Plans | 创建计划 | Phase 4 |
| Executing Plans | 实施阶段 | Phase 5 |
| Verification Loop | 验证阶段 | Phase 6 |
| agentic-engineering | Eval-first execution | 全流程 |
| council | 多视角决策 | Phase 2（复杂决策） |

---

## 参考

- Brainstorming Skill: `C:\Users\admin\.claude\skills\superpowers\collaboration\brainstorming\SKILL.md`
- Verification Loop Skill: `C:\Users\admin\.opencode\skills\verification-loop\SKILL.md`
- Writing Plans Skill: `C:\Users\admin\.claude\skills\superpowers\collaboration\writing-plans\SKILL.md`
- Executing Plans Skill: `C:\Users\admin\.claude\skills\superpowers\collaboration\executing-plans\SKILL.md`