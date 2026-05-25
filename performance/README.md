# 性能测试模块

验证 vLLM 推理性能指标。

---

## 测试指标

| 指标 | 说明 |
|------|------|
| 吞吐量 | requests/s, tokens/s |
| 延迟 | TTFT (首包延迟), TPOT (每token延迟) |
| 内存占用 | GPU 显存使用 |
| 批处理效率 | 不同 batch size 下的性能 |

---

## 目录结构

```
performance/
├── v0.13.0/                # vLLM v0.13.0 性能验证
├── latest/                 # 最新版本性能验证
├── monitor.py              # 性能监控脚本
└── PROGRESS.md             # 进度记录
```

---

## 性能监控

### monitor.py

实时监控 GPU 使用情况：

```bash
python monitor.py --interval 1 --duration 60
```

输出：
- GPU 显存使用率
- GPU 计算利用率
- 功耗
- 温度

---

## 性能基准测试

### vLLM Benchmark

```bash
cd /gpfs/gcsp/M2.7_verify/vllm/benchmarks
python benchmark_latency.py --model /gpfs/gcsp/models/MiniMax-M2.7
python benchmark_throughput.py --model /gpfs/gcsp/models/MiniMax-M2.7
```

### 参数配置

```bash
# 不同 batch size
--max-num-batched-tokens 1024
--max-num-batched-tokens 4096

# 不同 tensor parallel
--tensor-parallel-size 1
--tensor-parallel-size 2
--tensor-parallel-size 4
--tensor-parallel-size 8
```

---

## 测试场景

### Prefill 阶段

- 输入长度: 128, 512, 1024, 2048, 4096
- 批处理大小: 1, 4, 8, 16, 32

### Decode 阶段

- 输出长度: 128, 256, 512, 1024
- 批处理大小: 1, 4, 8, 16, 32

---

## 远程路径

```
/gpfs/gcsp/M2.7_verify/performance_test/
```

本地 `performance/` 对应远程 `performance_test/`。

---

## 相关文档

- [PROGRESS.md](./PROGRESS.md) - 进度记录