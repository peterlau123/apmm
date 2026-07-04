# Bash Bracket Escaping Issue - UT Workflow执行问题

**Date**: 2026-07-04  
**Issue Type**: Bug - Critical  
**Severity**: High  
**Status**: ✅ RESOLVED (2026-07-04) - Fixed with base64 encoding

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

## 尝试的修复方案（已废弃）

### ❌ 方案1-4: execute_batch.py层的引号转义
**结果**: 全部失败（agent.py重新解释引号，方括号仍然丢失）

---

## ✅ 成功修复方案：agent.py base64编码

**实施时间**: 2026-07-04  
**Commit**: 177c25f  
**修改位置**: tools/agent.py line 258-268

### 核心修改
```python
# 原代码（问题根源）
self.channel.send(f"echo {start}; {cmd}; echo ''; echo {end}\n")

# 新代码（base64编码）
import base64
cmd_b64 = base64.b64encode(cmd.encode('utf-8')).decode('ascii')
self.channel.send(f"echo {start}; eval $(base64 -d <<< '{cmd_b64}'); echo ''; echo {end}\n")
```

### 原理
- 绕过所有shell解释层
- 保护所有特殊字符（方括号、引号、反斜杠等）
- 命令在远程shell被精确还原

### execute_batch.py 简化（配合agent.py修复）
**修改位置**: skills/ut/unit-test-executor/scripts/execute_batch.py  
**修改内容**:
- 恢复双引号WATCHDOG_TEMPLATE（agent.py已保护）
- 移除冗余的单引号检查
- 恢复直接使用完整test_node（不使用 -k 绕过）
- 添加注释说明agent.py base64保护
- 保留Force GPU mode（独立改进）

---

## 验证结果

### 测试test_node
```
tests/kernels/attention/test_attention.py::test_paged_attention[cuda:1-0-fp8-dtype0-16-True-80-num_heads1-7-v2]
```

### pytest输出
```
collected 1 item
Running 1 items in this shard: tests/...::test_paged_attention[cuda:1-0-fp8-dtype0-16-True-80-num_heads1-7-v2]
PASSED [100%]
======================== 1 passed, 3 warnings in 12.09s ========================
```

### 验证成功指标
- ✅ `collected 1 item`（pytest正确识别参数化测试）
- ✅ test_node完整传递（方括号未丢失）
- ✅ `PASSED [100%]`（测试成功执行）
- ❌ 无"ERROR: not found"或"collected 0 items"

---

## 根本问题回顾

**关键代码**（tools/agent.py line 258）:
```python
self.channel.send(f"echo {start}; {cmd}; echo ''; echo {end}\n")
```

**问题**: 
- `cmd`被直接嵌入shell命令字符串
- 如果`cmd`包含单引号（如bash -c '...'），单引号在远程shell会被重新解释
- 方括号在某个shell层被解释为glob pattern

---

## 影响范围

- **影响batch数量**: 82个batch（从昨晚至今天上午）
- **影响测试数量**: 82 * 8 = 656个测试（理论值）
- **实际执行测试**: 0个（全部被ignored）
- **损失的工作时间**: ~10小时
- **根本原因定位时间**: ~2小时（systematic debugging流程）
- **修复验证时间**: ~30分钟（最小测试验证）

---

## 经验总结

### 根本教训

1. **多层shell嵌套时，引号转义策略会失效**
   - agent.py直接嵌入shell → 远程shell → docker exec → pytest
   - 每层shell都会重新解释引号和特殊字符

2. **Base64编码是最可靠的解决方案**
   - 绕过所有shell解释层
   - 保护所有特殊字符（方括号、引号、反斜杠等）
   - 命令在远程shell被精确还原

3. **不要在execute_batch.py层做引号转义**
   - 应该在agent.py层（最底层）统一保护
   - 上层转义会被下层重新解释，导致失效

### 修复方案对比

| 方案 | 位置 | 结果 | 原因 |
|---|---|---|---|
| 单引号包裹 | execute_batch.py | ❌ 失败 | agent.py重新解释 |
| 方括号转义 | execute_batch.py | ❌ 失败 | bash仍然解释 |
| pytest -k参数 | execute_batch.py | ❌ 失败 | 绕过策略不精确 |
| base64编码 | agent.py | ✅ 成功 | 绕过所有shell层 |

---

## 相关文件

- **修复文件**: tools/agent.py (line 258-268)
- **简化文件**: skills/ut/unit-test-executor/scripts/execute_batch.py
- **Commit**: 177c25f

---

*Last updated: 2026-07-04 (RESOLVED)*