# Agent Classify Prompt (L5)

判断断言失败的问题来源：test vs vllm

## Prompt Template

```
分析断言失败，判断问题来源：

测试节点: {test_node}
断言信息: {failure_message}
Traceback: {traceback}

代码上下文:
测试代码: {test_code}
vLLM源码: {vllm_code}

判断问题来源:
- test: 测试代码有问题
- vllm: vLLM源码有问题
- both: 双方都有问题
- uncertain: 需更多信息

输出 JSON:
{"problem_source": "...", "reason": "...", "confidence": "high|medium|low", "fix_target": "...", "fix_description": "..."}
```