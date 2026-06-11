# UT Workflow - vLLM单元测试验证流程

## 简介

UT Workflow是一个自动化单元测试验证流程，用于批量执行vLLM单元测试并追踪进度。

## 快速开始

**步骤**：
1. 配置workflow.yaml（设置test_list_path等参数）
2. 加载skill：`加载 ut/workflow skill`
3. 指定workflow.yaml路径
4. skill自动执行并生成报告

**执行方式**：
- **Subagent-Driven（推荐）**：每个Task由独立subagent执行，两阶段review确保质量
- **Inline Execution**：在同一session中批量执行，checkpoint review

**提示**：加载skill后需要指定workflow.yaml位置

## 核心概念

**5阶段流程**：
- Stage 1: collect - 收集测试清单
- Stage 2: select_batch - 选择批次
- Stage 3: execute - 执行测试
- Stage 4: handle_failures - 处理失败
- Stage 5: update_status - 更新状态

**test list来源**：
- workflow.yaml配置指定
- 命令行参数指定

## 相关文档

- [workflow.yaml](../../.agents/workflow.yaml) - Workflow配置（需用户调整）
- [workflow SKILL.md](../../skills/ut/workflow/SKILL.md) - 详细执行逻辑