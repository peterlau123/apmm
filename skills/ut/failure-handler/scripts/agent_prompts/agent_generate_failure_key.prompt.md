# Agent Generate Failure Key Prompt (L6)

生成标准化 failure_key

## Prompt Template

```
分析断言失败，生成 failure_key。

测试文件: {test_file}
断言信息: {failure_message}

格式: {test_file}:{bug_type}
示例:
- test_load:shape_mismatch
- test_inference:wrong_output_shape

只输出 failure_key，不要其他内容。
```