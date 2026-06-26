# 混合并发执行策略

> 本文档从 SKILL.md 移出，详细描述并发执行策略

## 执行模式分类

| 测试类型 | 并发策略 | GPU分配 | 命令模板 |
|----------|----------|---------|----------|
| **普通测试** | pytest-xdist | 单GPU轮询 | `pytest -n 4 --tb=long` |
| **distributed测试** | GPU分区并行 | 多GPU分配 | `CUDA_VISIBLE_DEVICES=0,1 pytest` |
| **Model测试** | 顺序执行 | 单GPU独占 | `pytest -n 1 --tb=long` |

## 并发参数配置

```yaml
concurrency_config:
  # 普通测试并发参数
  normal_tests:
    xdist_workers: 4          # pytest-xdist worker数量
    max_batch_size: 50        # 每批次测试数量
    
  # distributed测试并发参数
  distributed_tests:
    min_gpus_required: 2      # 最少GPU数量
    gpu_allocation_strategy: "exclusive"  # GPU独占分配
    
  # Model测试参数
  model_tests:
    sequential: true          # 顺序执行，避免模型加载冲突
```

## 普通测试并发执行

**使用 pytest-xdist 多进程并行**：

```bash
# 在容器内执行
sudo docker exec v0.13.0_torch2.5.1_compile bash -c '
cd /gpfs/gcsp/M2.7_verify/vllm && 
pytest -n 4 -q --tb=long \
  tests/basic_correctness/test_basic_correctness.py \
  tests/basic_correctness/test_cpu_offload.py \
  2>&1 | tee ut_logs/batch_<batch_id>.log
'
```

**参数说明**：
- `-n 4`：4个worker进程并行执行
- `-q`：简洁输出模式
- `--tb=long`：完整错误回溯

**优点**：
- pytest原生支持，无需额外协调逻辑
- worker进程共享测试收集结果，减少启动开销
- 失败测试不影响其他worker

**注意**：
- worker进程内存占用约 2-3GB 每个
- H20-3e GPU显存充足，可支持 4-8 workers

---

## distributed 测试 GPU分区并行

### GPU分配策略

```python
def allocate_gpus_for_distributed(available_gpus, distributed_tests):
    """为 distributed 测试分配 GPU"""
    
    # 检测可用GPU
    available = check_available_gpus()  # 返回 [0, 1, 2, 3, 4, 5, 6, 7]
    
    # 分配策略：每组distributed测试分配2-4个GPU
    allocations = []
    for i, test in enumerate(distributed_tests):
        gpu_group = available[i*2 : (i+1)*2]  # 每2个GPU一组
        if len(gpu_group) >= 2:
            allocations.append({
                "test": test,
                "gpus": gpu_group,
                "env": {
                    "CUDA_VISIBLE_DEVICES": ",".join(map(str, gpu_group)),
                    "MASTER_ADDR": "localhost",
                    "MASTER_PORT": str(29500 + i),
                    "WORLD_SIZE": str(len(gpu_group))
                }
            })
    
    return allocations
```

### 并行执行命令

```bash
# 同时启动多个 distributed 测试（不同GPU组）
# GPU组1: 0,1 → 测试A
CUDA_VISIBLE_DEVICES=0,1 MASTER_PORT=29500 pytest tests/distributed/test_pp.py &

# GPU组2: 2,3 → 测试B  
CUDA_VISIBLE_DEVICES=2,3 MASTER_PORT=29501 pytest tests/distributed/test_tp.py &

# GPU组3: 4,5 → 测试C
CUDA_VISIBLE_DEVICES=4,5 MASTER_PORT=29502 pytest tests/distributed/test_dp.py &

wait  # 等待所有后台进程完成
```

---

## Distributed 测试检测脚本

### GPU 可用性检测

```bash
# 检查 GPU 显存使用率
sudo docker exec <container> bash -c '
nvidia-smi --query-gpu=index,memory.used,memory.total --format csv,noheader | \
while IFS=, read idx used total; do
  usage=$(echo "scale=2; $used/$total" | bc)
  if [ $(echo "$usage < 0.1" | bc) -eq 1 ]; then
    echo "GPU $idx: available (usage: $usage)"
  fi
done
'
```

### 分布式环境变量设置

```bash
export MASTER_ADDR=localhost
export MASTER_PORT=29500
export WORLD_SIZE=<available_gpu_count>
export LOCAL_RANK=<gpu_index>
```

---

## 并发执行监控

```python
def monitor_parallel_batches(batch_processes):
    """监控并行批次执行状态"""
    
    while any(p["status"] == "running" for p in batch_processes):
        for p in batch_processes:
            if p["status"] == "running":
                # 检查进程存活
                alive = check_process_alive(p["pid"])
                # 检查日志进度
                progress = parse_log_progress(p["log_file"])
                
                if not alive or progress["completed"]:
                    p["status"] = "completed"
                    p["results"] = parse_results(p["log_file"])
        
        sleep(10)  # 每10秒轮询
    
    return batch_processes
```

## 并发执行流程图

```
[Step 4] 执行批次测试
│
├─ 判断测试类型
│   ├─ distributed 测试 → GPU分区并行
│   │   │
│   │   ├─ allocate_gpus_for_distributed()
│   │   ├─ 启动多个 pytest 进程（后台）
│   │   ├─ 监控多个进程状态
│   │   └─ wait + 结果收集
│   │
│   └─ 普通测试 → pytest-xdist
│       │
│       ├─ pytest -n 4 --tb=long
│       ├─ 单进程，多worker
│       └─ 直接等待完成
│
└─ 输出 tee 到日志文件
```

---

*创建日期: 2026-06-09*
*来源: skills/ut/unit-test-executor/SKILL.md*