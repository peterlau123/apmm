# Code Review: UT Workflow 数据流一致性修复

**审查日期**: 2026-07-12
**审查范围**: 11 个文件变更（202 insertions, 806 deletions）
**审查方法**: code-review skill 双轴审查（Standards + Spec）
**审查基准**: CLAUDE.md 编码规范 + Fowler 代码异味基线 + 用户原始需求

---

## Standards 轴

### HARD 违规

#### S1. SKILL.md Markdown 损坏

位置: terminal-workflow/SKILL.md:13 和 hermes-workflow/SKILL.md:45

问题: PowerShell here-string 处理时转义字符被写入文件，tab 字符吞噬了 test_load 中的 t，渲染为 est_load。三重反引号 bash 代码围栏被破坏为 反引号 + backspace + ash。

根因: 通过 PowerShell here-string + python 方式写入文件时，三重反引号和 tab 字符被转义处理污染。

修复方案: 直接用 Python write_text 写入纯文本，不经过 here-string 转义。

#### S2. generate_test_load.py 注释在 shebang 之前

位置: tasks/ut/scripts/generate_test_load.py:1-2

问题: Unix 系统要求 shebang (#!) 在文件第 1 行。注释在 shebang 之前会导致直接执行失败。

修复方案: 将两行注释移到 shebang 和 module docstring 之后。

### 判断性发现

#### S3. Duplicated Code - calculate_statistics 双重调用

merge_batch_results() 和 save_manifest() 都调用 calculate_statistics。冗余但幂等。

建议: 从 merge_batch_results() 中移除统计重算，让 save_manifest() 统一负责。

#### S4. 单元测试流程规范_v2.md 添加了 BOM 字符

建议: 用无 BOM 的 UTF-8 重写文件。

#### S5. manifest-updater/SKILL.md 重复版本行（既有问题）

末尾存在两个版本号: 3.3.0 和 3.0.0 并存。建议删除旧版本行。

---

## Spec 轴

### HARD 违规

#### P1. update_status.py 缺失 CLI 参数

被删除的 update_manifest.py 提供以下 CLI 接口，update_status.py 均不支持：

| 参数 | 功能 | update_status.py 对应 |
|------|------|----------------------|
| --report | 生成文本统计报告 | 无 |
| --daily-report | 生成 JSON 每日报告 | 无 |
| --recalc-stats | 重新计算 statistics | 无 |
| --test node | 更新单个测试 | --single node（名称不同） |
| --version-mismatch | 标记版本错配 | 无 |

同时丢失的函数: generate_report() 和 generate_daily_report()。

但 单元测试流程规范_v2.md 已被更新为引用 update_status.py --report 等不存在的命令。

影响: 运维人员按指南执行会直接报错。报告生成功能不可用。

修复方案: 将缺失的参数和函数从 update_manifest.py 迁入 update_status.py。

#### P2. --test vs --single 参数名不一致

指南写: update_status.py --test xxx --status failed
实际参数: --single 而非 --test

修复方案: 添加 --test 作为 --single 的别名，或修正指南。

### 判断性发现

#### P3. --batch 直接路径跳过 Type-B 审计

建议: 添加 --skip-audit flag 使跳过审计成为显式选择。

#### P4. SKILL.md State updates 描述与实际行为不一致

文档写道 update_status.py 更新 workflow_state.json batch completed，但实际不更新。

修复方案: 在 update_from_workflow_state() 末尾调用 update_batch_completed()，或修正文档。

---

## 汇总

| 轴 | 发现总数 | HARD | 判断性 | 最严重问题 |
|------|---------|------|--------|-----------|
| Standards | 5 | 2 | 3 | S1: SKILL.md Markdown 损坏 |
| Spec | 4 | 2 | 2 | P1: 删除脚本丢失 CLI 功能 |

### 需立即修复的 HARD 问题

| 优先级 | 编号 | 问题 | 修复工作量 |
|--------|------|------|----------|
| P0 | P1 | update_status.py 缺失 --report/--daily-report/--recalc-stats/--test/--version-mismatch | 中 |
| P0 | P2 | 指南引用 --test 但实际参数名是 --single | 小 |
| P1 | S1 | SKILL.md Markdown 损坏 | 小 |
| P1 | S2 | generate_test_load.py 注释在 shebang 之前 | 极小 |

---

## 审查结论

本次变更的核心方向正确（消除 test_load 架构断裂、合并重复脚本、统一数据流），但在执行层面存在 4 个 HARD 问题需立即修复：

1. CLI 功能丢失（P1/P2）- 删除 update_manifest.py 时未迁移 --report/--daily-report/--recalc-stats 等运维必需功能
2. Markdown 损坏（S1）- SKILL.md 文件内容被 PowerShell 转义字符污染
3. Shebang 位置（S2）- 注释在 shebang 之前

建议修复全部 HARD 问题后，再处理判断性问题。

---

*审查人: code-review skill (Standards + Spec 双轴)*
*审查时间: 2026-07-12*
