# UT文档更新实施计划（遗留任务）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 更新UT子系统文档以反映新配置管理机制（移除.agents/workflow.yaml引用，说明deployment/production + runs/副本机制，标注deployment/test已删除）

**背景：**
- Session 2026-06-29完成配置管理实施（6个commits已推送）
- 成本达CRITICAL无法继续，遗留23个文档需更新
- 优先更新关键guides（hermes-runner.md、ut-channels-overview.md）

**变更内容：**
1. 移除所有`.agents/workflow.yaml`引用 → 说明配置副本在`runs/ut-{timestamp}/workflow.yaml`
2. 移除`deployment/test/`引用 → 标注"已删除，测试配置在tests/ut/integration/fixtures/"
3. 更新merge_batch_manifests示例 → `--input` deprecated，使用`--run-dir`
4. 说明新配置机制：deployment/production作为模板库，runtime副本到runs/

---

## Task 1: 更新hermes-runner.md（关键guide）

**Files:**
- Modify: `tasks/ut/docs/guides/hermes-runner.md`

**上下文：** hermes-runner.md是飞书触发UT workflow的核心guide，引用.agents/workflow.yaml 4处。

- [ ] **Step 1: 搜索.agents/workflow.yaml引用位置**

```bash
grep -n ".agents/workflow.yaml" tasks/ut/docs/guides/hermes-runner.md
```

- [ ] **Step 2: 替换引用为新机制**

对于每个引用，根据上下文替换：

**类型A（配置路径）：**
- 旧：`.agents/workflow.yaml`
- 新：`runs/ut-{timestamp}/workflow.yaml`（运行时副本）
- 添加注释：`# 配置副本，模板位于tasks/ut/deployment/production/config/workflow.yaml`

**类型B（配置编辑）：**
- 旧："编辑.agents/workflow.yaml"
- 新："编辑deployment/production/config/workflow.yaml（模板）或runs/ut-{timestamp}/workflow.yaml（当前run）"

**类型C（环境选择）：**
- 添加说明："环境选择：production模板 → AI确认 → 复制到runs/ut-{timestamp}/"

- [ ] **Step 3: 添加新配置机制章节**

在文档开头或配置章节添加：

```markdown
## 配置文件管理

UT workflow使用配置模板库机制：

- **模板库**：`tasks/ut/deployment/production/config/workflow.yaml`
- **测试环境**：`tests/ut/integration/fixtures/workflow.l{1-4}.yaml`
- **运行副本**：`runs/ut-{timestamp}/workflow.yaml`（每次运行独立配置实例）

触发workflow时，AI会引导选择环境（production或test），然后复制模板到run目录。
```

- [ ] **Step 4: 添加deployment/test删除说明**

如果文档引用`deployment/test/`：

```markdown
**注意：** `tasks/ut/deployment/test/`已删除（2026-06-29），测试环境配置已迁移至`tests/ut/integration/fixtures/`。
```

- [ ] **Step 5: Commit**

```bash
git add tasks/ut/docs/guides/hermes-runner.md
git commit -m "docs(ut): update hermes-runner.md to reflect new config management

- Remove .agents/workflow.yaml references
- Add config management mechanism explanation
- Note deployment/test deletion

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 更新ut-channels-overview.md（关键guide）

**Files:**
- Modify: `tasks/ut/docs/guides/ut-channels-overview.md`

**上下文：** ut-channels-overview.md是UT workflow触发渠道overview，引用.agents/workflow.yaml 5处。

- [ ] **Step 1: 搜索.agents/workflow.yaml引用位置**

```bash
grep -n ".agents/workflow.yaml" tasks/ut/docs/guides/ut-channels-overview.md
```

- [ ] **Step 2: 替换引用为新机制**

同Task 1替换策略，根据上下文调整。

- [ ] **Step 3: 更新触发渠道章节**

如果文档有"配置准备"章节：

```markdown
### 配置准备（更新）

UT workflow现在使用配置模板库机制：

1. **选择环境**（AI交互确认）：
   - production → `tasks/ut/deployment/production/config/workflow.yaml`
   - test → `tests/ut/integration/fixtures/workflow.l{level}.yaml`

2. **配置副本**（自动）：
   - 模板复制到 `runs/ut-{timestamp}/workflow.yaml`
   - 运行时可修改副本而不影响模板库

3. **手动编辑**（可选）：
   - 修改模板：`deployment/production/config/workflow.yaml`
   - 修改当前run：`runs/ut-{timestamp}/workflow.yaml`
```

- [ ] **Step 4: Commit**

```bash
git add tasks/ut/docs/guides/ut-channels-overview.md
git commit -m "docs(ut): update ut-channels-overview.md to reflect new config management

- Remove .agents/workflow.yaml references
- Update config preparation section
- Add environment selection flow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 更新merge_batch_manifests相关文档

**Files:**
- Search: 所有引用`merge_batch_manifests --input`的文档
- Modify: 相关使用示例

**上下文：** merge_batch_manifests.py添加backward compatibility shim（commit e1ca3c3），`--input` deprecated但仍可用。

- [ ] **Step 1: 搜索--input引用**

```bash
grep -rn "merge_batch_manifests.*--input" tasks/ut/docs/
```

- [ ] **Step 2: 更新示例**

替换所有`--input`为`--run-dir`（推荐）：

**旧示例：**
```bash
python tasks/ut/scripts/merge_batch_manifests.py --input runs/ut-test
```

**新示例：**
```bash
python tasks/ut/scripts/merge_batch_manifests.py --run-dir runs/ut-test
```

**添加说明：**
```markdown
**注意：** `--input`参数已deprecated（2026-06-29），推荐使用`--run-dir`或自动发现（无需参数）。
```

- [ ] **Step 3: Commit**

```bash
git add tasks/ut/docs/  # 所有更新的文件
git commit -m "docs(ut): update merge_batch_manifests usage examples

- Replace --input with --run-dir (deprecated parameter)
- Add deprecation notice

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 搜索并更新其他.agents/workflow.yaml引用

**Files:**
- Search: `tasks/ut/docs/`下所有.agents/workflow.yaml引用（除Task 1-2已处理的）

- [ ] **Step 1: 搜索剩余引用**

```bash
grep -rn ".agents/workflow.yaml" tasks/ut/docs/ --exclude-dir=guides
```

排除guides目录（Task 1-2已处理）

- [ ] **Step 2: 分类处理**

根据文档类型：

**designs/**：添加注释说明旧引用已废弃
```markdown
**注意：** `.agents/workflow.yaml`已废弃（2026-06-29），配置机制已迁移至deployment/production模板库 + runs/副本机制。
```

**plans/**：标注历史计划中的路径已变更
```markdown
**历史路径变更：** `.agents/workflow.yaml` → `runs/ut-{timestamp}/workflow.yaml`（配置副本）
```

**incidents/**、**reports/**：历史文档可选更新（标注时间戳）

- [ ] **Step 3: Commit**

```bash
git add tasks/ut/docs/
git commit -m "docs(ut): remove remaining .agents/workflow.yaml references

- Add deprecation notes in designs/plans
- Update historical docs with path change notes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 搜索并标注deployment/test删除

**Files:**
- Search: `tasks/ut/docs/`下所有deployment/test引用

- [ ] **Step 1: 搜索引用**

```bash
grep -rn "deployment/test" tasks/ut/docs/
```

- [ ] **Step 2: 添加删除说明**

对于每个引用：

```markdown
**注意：** `tasks/ut/deployment/test/`已删除（2026-06-29），测试环境配置已迁移至`tests/ut/integration/fixtures/workflow.l{1-4}.yaml`。
```

- [ ] **Step 3: Commit**

```bash
git add tasks/ut/docs/
git commit -m "docs(ut): note deployment/test deletion in all references

- Add deletion notes (2026-06-29)
- Point to tests/ut/integration/fixtures/

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 最终验证与合并commit

**Files:**
- Verify: 所有文档更新已commit

- [ ] **Step 1: 验证无遗漏引用**

```bash
grep -rn ".agents/workflow.yaml" tasks/ut/docs/
grep -rn "deployment/test" tasks/ut/docs/ --exclude="Co-Authored-By"
```

确认所有引用已标注或移除

- [ ] **Step 2: 检查commit历史**

```bash
git log --oneline -5
```

确认5个文档更新commit

- [ ] **Step 3: 可选合并为单个commit**

如果用户偏好单个commit：

```bash
git reset --soft HEAD~5
git commit -m "docs(ut): comprehensive update for new config management mechanism

- Remove .agents/workflow.yaml references (guides + other docs)
- Add config management mechanism explanation
- Update merge_batch_manifests usage (--input deprecated)
- Note deployment/test deletion
- Total: 23 documents updated

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

**实施计划完成。推荐使用Subagent-Driven执行（Task 1-5各1个implementer subagent + 2 reviewers）。**