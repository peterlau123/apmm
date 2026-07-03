# NUMA-aware Allocation总结

**日期：2026-06-30 | 适用场景：LLM推理多核CPU优化**

---

## 核心概念

**NUMA（Non-Uniform Memory Access）架构**：
- 现代多核CPU的内存组织方式
- 每个NUMA node有local memory + local cores
- **访问延迟差异**：
  - Local memory：50-100ns
  - Remote memory（跨NUMA）：75-200ns（**1.5-2×延迟**）
- **关键问题**：跨NUMA访问是LLM推理的性能杀手

---

## 为什么LLM推理需要NUMA-aware

### 问题本质

LLM推理两个阶段都对内存访问敏感：

| 阶段 | 内存访问模式 | 跨NUMA影响 |
|------|-------------|-----------|
| **Prefill** | 顺序读取weight tensor | 每次矩阵分块计算都有延迟penalty |
| **Decode** | KV cache频繁读写 | 每token生成累积延迟，放大效应 |

### 实测数据

**llama.cpp（Neoverse N2，64核/NUMA node）**：
```
默认flat mmap（跨NUMA混乱）：
- 32 threads: 26.52 tok/s

NUMA-aware优化：
- 40 threads: 41.15 tok/s
提升：55%
```

**POWER8 S824（4 NUMA nodes）**：
```
Memory bandwidth utilization：
- Flat mmap: ~60%
- NUMA-sharded: ~85-90%（+25-30%）
```

**关键洞察**：跨NUMA内存访问导致30-40%吞吐下降，NUMA-aware可恢复大部分性能。

---

## 三大优化策略

### 策略1：Thread Binding + Memory First-Touch（P0，最简单有效）

**原理**：Linux kernel默认first-touch policy → 首次访问内存的线程所在NUMA node获得该内存页。

**实现**：
```bash
# 方法1：numactl绑定
numactl --cpunodebind=0 --membind=0 ./llama-cli

# 方法2：llama.cpp选项
llama-bench --numa isolate  # 单NUMA node运行
llama-bench --numa distribute  # NUMA-aware distribute
```

**代码逻辑**：
```cpp
// 线程绑定到NUMA node
for (int i = 0; i < num_threads; i++) {
    int numa_node = i / threads_per_node;
    pthread_setaffinity_np(thread[i],
        sizeof(cpu_set_t), &cpusets[numa_node]);
}

// First-touch内存分配
// 线程i只访问属于其NUMA node的tensor segment
float* segment_i = tensor + (i * segment_size);
for (int j = 0; j < segment_size; j++) {
    segment_i[j] = init_value;  // 首次写入 → 内存页绑定到node_i
}
```

### 策略2：Per-Layer Tensor Placement（P1，精细优化）

**原理**：根据layer访问频率和带宽需求，将tensor放到合适的NUMA node。

**Layer分配逻辑**：
```
GPT-2（12 layers）NUMA Node分配示例：
Layer 0-3  (early layers)     → NUMA Node 3 (fastest)
Layer 4-7  (attention layers) → NUMA Node 3 (highest bandwidth)
Layer 8-11 (late layers)      → NUMA Node 0-2 (less latency-sensitive)
```

**优化依据**：
- Early layers：prefill时最先访问，频率最高 → fastest node
- Attention layers：带宽需求最大（QKV矩阵） → highest bandwidth node
- Late layers：依赖链下游，延迟敏感度降低 → slower node可接受

### 策略3：Split Buffers + NUMA-local Barrier（P2，极端优化）

**问题**：传统全局barrier → 所有线程跨NUMA atomic竞争。

**优化方案**：两阶段barrier。
```cpp
// Stage 1: NUMA-local barrier（node内部）
barrier_local[node].wait();  // 12 threads in node

// Stage 2: Cross-NUMA barrier（仅last thread）
if (thread_id == last_thread_of_node) {
    pthread_barrier_wait(&cross_numa_barrier);  // 4 threads
}
```

**效果**：减少跨NUMA atomic操作从N threads → 只需num_numa_nodes threads。

---

## 实际应用案例

### 案例1：vLLM Multi-GPU NUMA Pinning

**场景**：2 GPU系统，每个GPU绑定到不同NUMA node。

```bash
# GPU Worker 0 → NUMA Node 0
export CUDA_VISIBLE_DEVICES=0
numactl --cpunodebind=0 --membind=0 \
    python -m vllm.entrypoints.api_server

# GPU Worker 1 → NUMA Node 1
export CUDA_VISIBLE_DEVICES=1
numactl --cpunodebind=1 --membind=1 \
    python -m vllm.entrypoints.api_server
```

**原理**：GPU与NUMA node物理绑定（PCIe topology）→ Worker在nearest node减少CPU-GPU通信延迟。

### 案例2：ArcLight Tensor Parallelism

**场景**：64核many-core CPU，跨NUMA tensor parallelism。

**方案**：模型分4 parts，每个NUMA node负责连续layers。
```
NUMA Node 0: Layer 0-3
NUMA Node 1: Layer 4-7
NUMA Node 2: Layer 8-11
NUMA Node 3: Layer 12-15

Cross-node communication：仅layer transition时
（Layer 3 → Layer 4）transfer activation tensor
```

**效果**：大部分计算在local memory，跨NUMA访问从every-operation → only-at-boundary。

### 案例3：Sandwich系统（Prefill/Decode分离）

**场景**：prefill/decode阶段对NUMA需求不同。

**TopoTree抽象**：
```
AMD EPYC 7H12:
root
├── NUMA Node 0
│   ├── LLC Slice 0 (4 cores)
│   ├── LLC Slice 1 (4 cores)
│   └── LLC Slice 2 (4 cores)
├── NUMA Node 1...

Prefill：使用所有cores，最大化compute
Decode：部分LLC slice allocation，避免memory controller竞争
```

---

## NUMA工具速查

### 1. 查看拓扑
```bash
numactl --hardware

# 输出：
available: 2 nodes (0-1)
node 0 cpus: 0-11
node 0 size: 65536 MB
node 1 cpus: 12-23
node 1 size: 65536 MB
node distances:
node   0   1
  0:  10  21  # local=10, remote=21
  1:  21  10
```

### 2. 内存统计
```bash
numastat -p <pid>

# 输出：
Per-node memory usage (MBs)
           Node 0  Node 1  Total
Heap       2048    1024    3072
Stack         2       2       4
```

### 3. 运行方式推荐
```bash
# 单NUMA node（最高性能，但只用1个node）
numactl --cpunodebind=0 --membind=0 ./llama-cli

# NUMA distribute（利用所有nodes，NUMA-aware）
numactl --interleave=all ./llama-cli --numa distribute

# vLLM NUMA isolate
python launch_vllm.py --numa isolate
```

### 4. 禁用automatic NUMA balancing
```bash
# 手动控制更精确（推荐）
echo 0 > /proc/sys/kernel/numa_balancing
```

---

## 关键洞察总结

| 维度 | 结论 |
|------|------|
| **必要性** | NUMA-aware不是可选，而是必须（跨NUMA延迟1.5-2×） |
| **优先级** | P0：Thread binding + first-touch；P1：Per-layer placement；P2：Split buffers |
| **实测收益** | 55% throughput提升，25-30% bandwidth utilization改善 |
| **适用场景** | 所有内存密集型LLM推理（单GPU、多GPU、纯CPU） |
| **工具支持** | numactl、numastat、llama.cpp --numa、vLLM NUMA pinning |

**一句话定义**：NUMA-aware allocation = 让每个线程只访问离它最近的内存，避免跨NUMA的高延迟开销，对LLM推理这种内存密集型workload至关重要。

---

## 参考资料

1. **ArcLight论文** (2026) — NUMA-aware tensor parallelism，46% throughput提升
2. **llama.cpp NUMA-shard PR** (#11580) — Per-layer placement，55%提升实测
3. **Sandwich论文** (2025) — TopoTree硬件抽象，prefill/decode分离
4. **Arm Community Blog** (2026) — Neoverse N2实测数据
5. **vLLM Optimization Docs** (2026) — Worker NUMA pinning配置指南