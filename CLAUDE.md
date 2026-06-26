# CLAUDE.md

## ⚡ Superpowers Installed

You have **Superpowers** — a software development methodology framework 

**BEFORE responding to any request, you MUST:**
1. Check if any superpower skill might apply (even 1% chance → use it)
2. Read the relevant SKILL.md file from `skills/<skill>/SKILL.md` under the global storage path
3. Follow it exactly

**If multiple skills could apply, invoke them in this order:**
1. Process skills first (brainstorming, debugging)
2. Implementation skills second

---

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 5. 文档归位规则（hard rule）

判断标准：文档讨论的对象**只属于哪个 `tasks/<x>` 子系统**？

| 范围 | 收纳位置 | 示例 |
|---|---|---|
| 跨子系统 / 项目级 | `docs/` | bastion / environment / ai-workflow / superpowers 框架自身 spec |
| 仅 UT 子系统 | `tasks/ut/docs/` | hermes-workflow / manifest / ut-supervisor 部署 / UT 周报 / UT incident |
| 仅 accuracy 子系统 | `tasks/accuracy/docs/`（按需建） | GPQA/MMLU 评测脚本、精度报告 |
| 仅 performance 子系统 | `tasks/performance/docs/`（按需建） | 吞吐压测、roofline、调度对比 |
| 其它新子系统 | `tasks/<x>/docs/`（按需建） | 镜像同样的子目录骨架：`guides/`, `designs/`, `plans/`, `incidents/`, `reports/`, `discussions/` |

**判定流程**：
1. 文档主要对象命中**单个** `tasks/<x>/`（看标题、文件路径引用、SKILL 引用）→ 必须放 `tasks/<x>/docs/`。
2. 命中**多个** `tasks/<x>` → 放项目级 `docs/`，并在每个相关 `tasks/<x>/docs/README.md` 加导引链接。
3. 不命中任何 `tasks/<x>`（纯基础设施 / 跨项目工具）→ 项目级 `docs/`。

**项目级 `docs/` 禁止规则**：禁止接收任何只服务单一 `tasks/<x>` 的详细文档（spec / plan / incident / report / 运维 guide）。新写前请按上表自检；判断不准就**问用户**，不要默认丢 `docs/`。

**新建子系统时**：在 `tasks/<x>/docs/` 下复用与 `tasks/ut/docs/` 一致的子目录骨架（`README.md` + `guides/` + `designs/` + `plans/` + `incidents/` + `reports/` + `discussions/`），保持跨子系统目录结构一致。

