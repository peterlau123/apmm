# Sample Test Logs

pytest 测试日志样本，用于验证解析逻辑。

## 文件

| 文件 | 说明 |
|------|------|
| `20260602_compile_full.log` | compile 测试 (32 passed, 570 failed, 692 error) |
| `config_ut.log` | UT 配置测试 |
| `config_tools_cuda.log` | CUDA 工具测试 |

## pytest -v 格式

```
tests/xxx.py::test_name[param1] FAILED [ 10%]
```

正则: `r"(tests/[^\s]+)\s+(PASSED|FAILED|ERROR)\s+\[\s*\d+%\]"`

*Created: 2026-06-11*