# 错误统计分类流程

> **用途**: 从远程服务器 ut_logs 目录统计 pytest 日志中的错误类型，分类 vLLM+PyTorch 兼容性问题
> **更新时间**: 2026-06-08

---

## 一、前提条件

### pytest 参数配置

pytest 命令必须包含以下参数，才能正确生成可统计的日志：

```python
# skills/ut/unit-test-runner/scripts/pytest_config.py
PYTEST_ARGS = {
    "verbosity": "-q",        # quiet模式，适合批量测试
    "tb_style": "--tb=long",  # 详细回溯，便于问题分类
}
```

**参数说明**：
- `-q`: 减少输出冗余，只显示 FAILED/ERROR 摘要
- `--tb=long`: 详细回溯信息，便于提取错误类型和位置

---

## 二、统计脚本模板

以下 Python 脚本可直接在远程服务器执行，统计 ut_logs 目录下的所有日志：

```python
#!/usr/bin/env python3
import re
from pathlib import Path
from collections import defaultdict

LOG_DIR = Path("/gpfs/gcsp/M2.7_verify/vllm/ut_logs")

# 错误分类规则（按优先级排列）
CATEGORY_RULES = [
    # C类：vLLM+PyTorch兼容性问题（重点分析）
    ("C-LoRA-Type", r"infer_schema.*unsupported type list\[torch\.Tensor\]"),
    ("C-wrap_triton", r"cannot import.*wrap_triton"),
    ("C-fp32_precision", r"fp32_precision.*not exist"),
    ("C-recompile_limit", r"recompile_limit.*not exist"),
    ("C-auto_functionalized", r"auto_functionalized.*not exist"),
    ("C-Triton-Version", r"triton\.language\.target_info"),
    ("C-DeepSeek-Compile", r"dynamic_arg_dims.*input_ids"),
    
    # A类：HuggingFace网络/模型问题（环境限制，不修复）
    ("A-HF-Offline", r"huggingface\.co|Could not connect.*Hub|LocalEntryNotFoundError"),
    ("A-HF-Model", r"model.*not found|offline|FileNotFoundError.*Hub"),
    
    # B类：验证/依赖问题
    ("B-ValidationError", r"ValidationError"),
    ("B-Dependency", r"No module named|ImportError"),
    
    # D类：测试逻辑问题
    ("D-Assert", r"AssertionError"),
    
    # 其他
    ("Timeout", r"Timeout.*pytest"),
    ("Network-Connect", r"ConnectTimeout"),
]

def analyze_logs():
    """分析所有日志文件"""
    logs = list(LOG_DIR.glob("*.log"))
    err_pat = re.compile(r"(FAILED|ERROR)\s+(\S+)\s+-\s+(.+)")
    
    stats = defaultdict(lambda: {"n": 0, "tests": [], "exc_types": defaultdict(int)})
    
    for lf in logs:
        try:
            content = open(lf, errors="ignore").read()
            # 提取 short test summary info 部分
            m = re.search(r"short test summary info.*?\n(.*?)(?:==|$)", content, re.DOTALL)
            if m:
                for line in m.group(1).split("\n"):
                    if line.startswith("FAILED") or line.startswith("ERROR"):
                        match = err_pat.search(line)
                        if match:
                            test_name = match.group(2)
                            error_msg = match.group(3)
                            
                            # 分类错误
                            category = "Other"
                            for cat, pattern in CATEGORY_RULES:
                                if re.search(pattern, error_msg, re.I):
                                    category = cat
                                    break
                            
                            # 提取错误类型
                            exc_match = re.search(r"(\w+Error|\w+Exception):", error_msg)
                            exc_type = exc_match.group(1) if exc_match else "Unknown"
                            
                            stats[category]["n"] += 1
                            stats[category]["tests"].append(test_name)
                            stats[category]["exc_types"][exc_type] += 1
        except Exception:
            pass
    
    return stats, logs

def print_report(stats, logs):
    """打印统计报告"""
    total = sum(s["n"] for s in stats.values())
    print(f"Total errors: {total}, Logs: {len(logs)}")
    print("\n=== Category Statistics ===")
    print("| Category | Count | % | Error Types |")
    print("|:--------:|:-----:|:-:|:-----------:|")
    
    for cat in sorted(stats.keys()):
        s = stats[cat]
        pct = round(s["n"] * 100 / total, 1)
        excs = list(s["exc_types"].keys())[:3]
        print(f"| {cat} | {s['n']} | {pct}% | {excs} |")

if __name__ == "__main__":
    stats, logs = analyze_logs()
    print_report(stats, logs)
```

---

## 三、执行方法

### 方法1：直接在远程执行脚本

```bash
# 通过 agent.py 执行
cd D:/workspace/apmm
python tools/agent.py -p t_h20 run --timeout 180 \
  "cd /gpfs/gcsp/M2.7_verify/vllm/ut_logs && python3 -c '...'"

# 注意：--timeout 需要足够长（建议180秒以上）
# 因为需要读取所有日志文件（可能超过100个）
```

### 方法2：创建脚本文件后执行

```bash
# 1. 在远程创建脚本
python tools/agent.py -p t_h20 run \
  "cat > /gpfs/gcsp/M2.7_verify/vllm/ut_logs/stats.py << 'EOF'
...脚本内容...
EOF"

# 2. 执行脚本
python tools/agent.py -p t_h20 run --timeout 180 \
  "cd /gpfs/gcsp/M2.7_verify/vllm/ut_logs && python3 stats.py"
```

---

## 四、错误分类标准

### C类：兼容性问题（必须修复）

| 类别 | 错误特征 | 根因 | 修复方案 |
|------|----------|------|----------|
| C-LoRA-Type | `infer_schema(func): Parameter has unsupported type list[torch.Tensor]` | PyTorch 2.5.1 不支持 Python 3.10+ 类型注解 | 使用 `typing.List` 或 `from __future__ import annotations` |
| C-wrap_triton | `cannot import name 'wrap_triton'` | PyTorch 2.5.1 无此API | 添加 shim 函数或版本限制 |
| C-fp32_precision | `fp32_precision does not exist` | PyTorch 2.5.1 无此属性 | 添加 `hasattr` 检查 |
| C-recompile_limit | `recompile_limit does not exist` | PyTorch 2.5.1 dynamo配置缺失 | 添加 `hasattr` 检查 |
| C-Triton-Version | `No module named 'triton.language.target_info'` | Triton版本不兼容 | 升级 Triton 或跳过相关测试 |

### A类：环境限制问题（记录不修复）

| 类别 | 错误特征 | 原因 |
|------|----------|------|
| A-HF-Offline | 无法连接 huggingface.co | 远程服务器无外网访问 |
| A-HF-Model | 模型文件本地缺失 | 未预先下载模型 |

### B类：验证/依赖问题（需分析）

| 类别 | 错误特征 | 原因 |
|------|----------|------|
| B-ValidationError | ModelConfig 验证失败 | 模型配置参数不匹配 |
| B-Dependency | No module named | 第三方依赖缺失 |

---

## 五、常见问题

### Q1: 命令超时是什么原因？

**超时发生在远程命令执行阶段**。原因：
- 读取大量日志文件（100+个）需要时间
- SSH 连接和文件 I/O 延迟
- 解决方案：增加 `--timeout` 参数值（建议 180-300 秒）

### Q2: 如何保存统计结果？

```bash
# 保存 JSON 数据
python3 -c "...脚本..." > /tmp/error_stats.json

# 或在脚本中添加保存逻辑
with open("/tmp/error_report.md", "w") as f:
    f.write(report_content)
```

### Q3: Other 分类如何进一步分析？

Other 分类通常包含：
- RuntimeError：Engine 初始化失败
- ValueError：分布式环境变量缺失
- AttributeError：torch._dynamo 相关

可单独提取分析：

```python
other_details = defaultdict(int)
for cat in ["Other"]:
    for err in errors:
        if err["cat"] == "Other":
            # 按错误类型细分
            xm = re.search(r"(\w+Error|\w+Exception):", err["msg"])
            if xm:
                other_details[xm.group(1)] += 1
```

---

## 六、相关文档

- [pytest_config.py](../../skills/ut/unit-test-runner/scripts/pytest_config.py) - pytest参数配置
- [2026-06-08.md](../compatibility/2026-06-08.md) - 本次统计结果
- [2026-06-01.md](../compatibility/2026-06-01.md) - 之前兼容性分析

---

*文档创建时间: 2026-06-08*