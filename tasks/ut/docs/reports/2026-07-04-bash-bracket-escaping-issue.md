# Bash Bracket Escaping Issue - UT Workflow执行问题

**Date**: 2026-07-04  
**Issue Type**: Bug - Critical  
**Severity**: High  
**Status**: Diagnosed, Root cause identified, multiple fixes attempted, pending final resolution

## 问题概述
terminal-workflow从昨晚至今天上午运行了82个batch, 大部分测试被标记为`ignored`状态。
**实际执行测试数**: 0

## 根本原因
**Bash方括号转义问题**导致pytest无法识别参数化测试节点。

### 命令执行链分析
```
batch_config.json (test_node)
  ↓ 包含方括号: ✅ tests/...::test_paged_attention[cuda:1-0...]
  
execute_batch.py (pytest_full_cmd构建)
  ↓ 包含方括号: ✅ pytest tests/...::test_paged_attention[...]
  
WATCHDOG_TEMPLATE (base64编码)
  ↓ 编码watchdog_script
  
agent.py (run方法)
  ↓ **关键问题**: 直接将命令嵌入shell
  ↓ 执行: echo START; {cmd}; echo END
  ↓ 单引号在某个shell层被重新解释
  
远程shell (bash解释)
  ↓ 方括号被解释为glob pattern
  ↓ pytest接收缺少参数化的test_node
  ↓ pytest报错: ERROR: not found: test_paged_attention
  ↓ tests="0"
  
batch_results.json (status="ignored")
```

### 具体错误信息
**batch执行日志**:
```
ERROR: not found: /gpfs/gcsp/M2.7_verify/vllm/tests/kernels/attention/test_attention.py::test_paged_attention
(no match in any of [<Module test_attention.py>])

collected 0 items
Running 0 items in this shard:
```

**batch结果**:
```json
{
  "status": "ignored",
  "error_type": "timeout",
  "error_message": "JUnit XML unparseable (watchdog SIGKILL mid-flush?)"
}
```

## 尝试的修复方案

### 1. 转义的双引号（方案A）
**修改**: execute_batch.py第907-909行
```python
pytest_full_cmd = f"... pytest '{node}' ..."
```
**结果**: Python语法错误（原始字符串转义问题）

### 2. 转义方括号（方案B）
**修改**: execute_batch.py第907行
```python
node_escaped = node.replace('[', r'\[').replace(']', r'\]')
pytest_full_cmd = f"... pytest {node_escaped} ..."
```
**结果**: 方括号仍然丢失（bash仍然解释）

### 3. 单引号包裹node（方案C）
**修改**: WATCHDOG_TEMPLATE改用单引号
```python
WATCHDOG_TEMPLATE = "bash -c '{pytest_full_cmd}' ..."
```
**结果**: 方括号仍然丢失（agent.py重新解释单引号）

### 4. 不转义方括号（方案D）
**修改**: pytest_full_cmd中不转义方括号
```python
pytest_full_cmd = f"... pytest {node} ..."
```
**结果**: 方括号仍然丢失（bash仍然解释）

## 根本问题
**agent.py的run方法**直接将命令嵌入shell, 导致所有引号转义策略失效。

**关键代码**（tools/agent.py line 258）:
```python
self.channel.send(f"echo {start}; {cmd}; echo ''; echo {end}\n")
```

**问题**: 
- `cmd`被直接嵌入shell命令字符串
- 如果`cmd`包含单引号（如bash -c '...'），单引号在远程shell会被重新解释
- 方括号在某个shell层被解释为glob pattern

## 验证过程
手动bash测试（不通过agent.py）显示： 即使直接使用bash -c单引号, 方括号仍然在某些情况下丢失。
这表明问题可能在于：
1. 多层shell嵌套导致引号转义失效
2. docker exec的shell处理机制
3. SSH连接中的shell转义规则

## 影响范围
- **影响batch数量**: 82个batch（从昨晚至今天上午）
- **影响测试数量**: 82 * 8 = 656个测试（理论值）
- **实际执行测试**: 0个（全部被ignored）
- **损失的工作时间**: ~10小时

## 建议解决方案

### 方案1: Base64编码pytest命令本身
**修改位置**: execute_batch.py
**修改内容**:
- 在构建pytest_full_cmd之前, base64编码整个命令
- 修改_wrap_with_docker_exec_b64, 在编码前传递原始命令

**优势**: 绕过所有shell层, 保护所有特殊字符

### 方案2: 改进agent.py的命令传递
**修改位置**: tools/agent.py
**修改内容**:
- 改进run方法, 使用更安全的命令传递机制
- 例如使用文件传递命令而不是直接嵌入shell字符串

**优势**: 解决根本问题, 但需要更深入的改动

### 方案3: pytest参数转义
**修改位置**: execute_batch.py
**修改内容**:
- 使用pytest的特殊参数转义语法
- 例如使用--co语法或其他pytest专用机制

**优势**: pytest原生支持, 不依赖bash引号

## 下一步行动建议
1. **评估方案**: 选择最适合的修复方案（建议方案1）
2. **修复代码**: 修改execute_batch.py或agent.py
3. **测试验证**: 手动测试修复是否生效
4. **重新运行workflow**: 修复后重新执行batch验证

## 相关文件
- **问题文件**: skills/ut/unit-test-executor/scripts/execute_batch.py
- **根本问题文件**: tools/agent.py
- **测试batch**: runs/ut-20260630-163959/batches/batch_test_fix_001/
- **执行日志**: /gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_test_fix_001/

## 附录
### test_node示例
```
tests/kernels/attention/test_attention.py::test_paged_attention[cuda:1-0-fp8-dtype0-16-True-80-num_heads1-7-v2]
```

### pytest错误示例
```
ERROR: not found: /gpfs/gcsp/M2.7_verify/vllm/tests/kernels/attention/test_attention.py::test_paged_attention
```

### batch结果示例
```json
{
  "total": 1,
  "passed": 0,
  "failed": 0,
  "error": 0,
  "skipped": 0,
  "retriable_error": 0,
  "ignored": 1
}
```