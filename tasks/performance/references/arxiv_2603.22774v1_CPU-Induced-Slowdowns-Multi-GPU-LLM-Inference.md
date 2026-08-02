# Characterizing CPU-Induced Slowdowns in Multi-GPU LLM Inference

**Authors:** Euijun Chung, Yuxiao Jia, Aaron Jezghani, Hyesoon Kim
**arXiv:** 2603.22774v1 [cs.AR] 24 Mar 2026
**Source:** https://arxiv.org/html/2603.22774v1

---

## Abstract

Large-scale machine learning workloads increasingly rely on multi-GPU systems, yet their performance is often limited by an overlooked component: the CPU. Through a detailed study of modern large language model (LLM) inference and serving workloads, we find that multi-GPU performance frequently degrades not because GPUs are saturated, but because CPUs fail to keep the GPUs busy. Under limited CPU allocations, systems exhibit symptoms such as delayed kernel launch, stalled communication, and increased tokenization latency, leading to severe GPU underutilization even when ample GPU resources are available. This work presents a systematic analysis of CPU-induced slowdowns in multi-GPU LLM inference. We show that these bottlenecks persist even in serving stacks that employ process-level separation and modern GPU-side optimizations such as CUDA Graphs. Since the marginal cost of additional CPU cores is small relative to GPU instance pricing, our evaluation indicates that increasing the number of CPU cores can substantially improve performance and stability at minimal additional cost. Under moderate serving load, we observe that CPU-starved configurations frequently time out, while providing adequate CPU resources restores responsiveness and reduces time-to-first-token (TTFT) latency by 1.36–5.40× across configurations, all without requiring additional GPUs. This work shows that CPU provisioning is a crucial factor in multi-GPU LLM inference configuration, helping prevent control-side bottlenecks.

---

## I Introduction

Modern ML workloads require massive computational power, driving the widespread adoption of multi-GPU servers, such as the DGX H100 and DGX B200. GPU servers are expensive to purchase and operate. To ensure efficient use of valuable resources, organizations operate them in a shared, multi-tenant manner, allowing multiple users to work on their own allocated virtual instances. Through resource schedulers like Slurm or cloud platforms (e.g., AWS and Azure), users request manual and static allocations (e.g., 4 GPUs and 8 CPU cores) at a given cost per unit time. While this approach improves GPU utilization across many users, it creates a critical blind spot: the CPU is often underallocated to users. This paper reveals that this imbalance between CPU and GPU can silently make the CPU a significant bottleneck in multi-GPU systems.

In multi-GPU ML workloads, contrary to the common assumption that GPUs are the primary bottleneck, CPUs perform numerous critical tasks:
- Data I/O and processing
- Inter-GPU synchronization
- Request scheduling
- Kernel launches

A significant portion of a CPU's job involves feeding sufficient data to GPUs, i.e., retrieving data from host memory and performing preprocessing steps such as tokenization for language models, or image decoding and augmentation for vision models. Such input-processing stages demand substantial CPU computation, especially for long input sequences and large batched inputs in LLM serving.

**Key contributions:**
1. Detailed characterization of CPU-intensive components in multi-GPU LLM inference and serving, quantifying how they induce CPU-side bottlenecks that propagate into end-to-end performance degradation.
2. LLM-serving experiments illustrating how CPU tokenization overhead degrades end-to-end performance and demonstrating that additional CPU resources effectively mitigate this slowdown.
3. Root cause analysis of CPU slowdowns: CPU oversubscription compounds with barrier-based GPU synchronization to leave GPUs idle, and contention on the lock-free shared-memory broadcast queue scales with tensor parallelism degree.
4. Analysis of real-world cluster allocation logs demonstrating the prevalence of CPU under-provisioning, with practical insights for CPU resource allocation.

---

## II Background & Motivation

### II-A CPU's Job in LLM Inference

The CPU is responsible for three latency-sensitive operations:

1. **Tokenization:** Converts raw text strings into integer token IDs. This process occurs at the beginning of every inference request for prompt processing. Tokenization consumes substantial CPU cycles, particularly for long prompts or batched requests. HuggingFace Tokenizers library enables Rust-based multithreaded tokenizer with TOKENIZERS_PARALLELISM=true by default.

2. **HTTP Server Request Handling:** Connection management, request parsing, and batched scheduling. Overhead scales with query rate rather than model size.

3. **Kernel Launch Overhead:** The CPU schedules and dispatches CUDA kernels for each model layer. Each launch traverses the CUDA runtime and driver stack, culminating in a PCIe MMIO write to the GPU's doorbell register. CUDA Graphs can avoid most repeated launch calls but cannot merge all kernel calls due to dynamic control flow (EOS detection, stop-condition checks, agent tool-call dispatches).

Multi-GPU frameworks (vLLM, DeepSpeed, HuggingFace Accelerate) allocate at least one process per GPU to isolate kernel launch responsibilities.

### II-B Real-World CPU Under-Provisioning in HPC Clusters

Analysis of 4.65 million salloc records from two institutional clusters during calendar year 2024:

- **Instructional cluster:** Median (P50) CPU-to-GPU ratio lies around 1–2 for both A100 and H100 nodes. P25 percentile falls at or below 2. H100 nodes show cases where users request as little as 1 CPU core for 4 or 8 GPUs (P25 ratio of 0.25).
- **Research cluster:** Scheduler enforces proportional CPU allocation, but ~60% of jobs still exhibit CPU-to-GPU ratios below 8.

Key finding: Many users remain unaware that inadequate CPU allocation can introduce severe bottlenecks in multi-GPU workloads. Ratios below 4–8 cores per GPU risk measurable slowdown for LLM inference workloads.

---

## III Multi-GPU System Evaluation Setup

| System (GPU) | Architecture | CPU Model | #CPU Cores | #GPUs per Node | Interconnect |
|---|---|---|---|---|---|
| H100 | Hopper (9.0) | Intel Xeon Platinum 8480CL | 64 | 8 | NVLink 4.0 (900 GB/s) |
| H200 | Hopper (9.0) | Intel Xeon Platinum 8480CL | 64 | 8 | NVLink 4.0 (900 GB/s) |
| RTX Pro 6000 | Blackwell (12.0) | Dual Intel Xeon 6737P | 64 | 8 | No NVLink (PCIe 5.0, 64 GB/s) |

- SMT disabled for all experiments
- vLLM v0.11.1 with V1 engine architecture
- V1 engine separates API server process (tokenization, request management) from EngineCore process (scheduling) via ZeroMQ IPC
- Optimizations enabled: CUDA Graphs (full-and-piecewise mode), chunked prefill, prefix caching, torch.compile with Inductor backend, custom all-reduce kernels

---

## IV CPU Bottleneck in LLM Inference

### IV-A Tokenization Latency Evaluation

- Tokenization accounts for up to **50% of total latency** in long-sequence configurations
- This fraction does not diminish at longer sequence lengths because modern serving stacks use chunked prefill and FlashAttention, causing prefill time to scale near-linearly rather than quadratically
- As context lengths grow (e.g., 1M-token prompt), tokenization overhead becomes increasingly significant
- Experiments: Llama 3.1 8B on 4×H200 system with 16 CPU cores

### IV-B Impact of Tokenization Load in LLM Serving

**Methodology:** "Victim-attacker" experiment — multiple concurrent "attacker" requests impose CPU load while measuring a single "victim" request's latency.

**Setup:**
- Llama 3.1 8B and Qwen 2.5 14B on 4- and 8-GPU configurations
- CPU levels: (#GPUs + 1), 2×#GPUs, 4×#GPUs, 8×#GPUs cores
- Attacker sequence length: 1.8k to 114k tokens
- Victim sequence length: 2.8k tokens
- Attacker RPS: 8 and 16

**Key Results:**
- Scaling from 5 CPU cores (least-CPU) to 32 cores (8 per GPU) consistently reduces victim request TTFT under load by over **5×**
- CPU-starved configurations frequently time out under moderate load
- Providing adequate CPU resources reduces TTFT latency by **1.36–5.40×** across configurations
- Speedup heatmap shows ∞ (timeout) for minimal-CPU configurations in many cases

---

## V Understanding the CPU Bottlenecks in Multi-GPU Systems

### V-A Synchronization and CPU Oversubscription in Communication Kernels

Two key root causes identified:

1. **Compounded contention between CPU overheads and communication coordination:** CPU oversubscription compounds with barrier-based GPU synchronization, leaving GPUs idle. When the CPU is late to dispatch on any rank, the entire device group stalls.

2. **Shared-memory broadcast contention:** Contention on the lock-free shared-memory broadcast queue used for inter-process coordination introduces additional delays on the critical path. This structural bottleneck scales with the degree of tensor parallelism.

### V-B Shared Memory Broadcast Contention

- vLLM V1 uses shared-memory broadcast for EngineCore → GPU worker communication
- Even under lock-free designs, contention introduces delays on the critical path
- This bottleneck scales with tensor parallelism degree — more GPUs = more broadcast consumers = more contention

---

## VI Discussion

### VI-A CPU Under-Provisioning in Cloud Compute Platforms

- CPU provisioning is a crucial factor in multi-GPU LLM inference configuration
- The marginal cost of additional CPU cores is small relative to GPU instance pricing
- Increasing CPU cores can substantially improve performance at minimal additional cost

### VI-B Emerging Trends That May Intensify CPU Bottlenecks

- Growing context lengths increase tokenization overhead
- Agentic AI workloads increase CPU-side dynamic control flow
- Multi-modal models add preprocessing complexity

### VI-C Limitations

- Experiments use physical cores (SMT disabled); production cloud instances expose vCPUs (hyperthreads)
- Results represent conservative baseline

---

## VII Related Work

### VII-A CPU Overhead in Agentic AIs
### VII-B GPU-Driven Control and Device-Initiated Communications
### VII-C LLM Serving Frameworks
### VII-D Mitigating the CPU Overhead in LLMs
### VII-E Mitigating Kernel Launch Overhead

---

## VIII Conclusion

CPU provisioning is a crucial factor in multi-GPU LLM inference configuration. Key findings:
- CPU bottlenecks persist even with process-level separation and CUDA Graphs
- CPU under-provisioning is prevalent in real-world HPC clusters
- Increasing CPU cores substantially improves performance at minimal additional cost
- TTFT latency improves 1.36–5.40× with adequate CPU resources
- Root causes: CPU oversubscription + barrier synchronization + shared-memory broadcast contention

---

*Note: This markdown was fetched from the arxiv HTML page. Some content at the end was truncated due to context limits. Refer to the [original paper](https://arxiv.org/html/2603.22774v1) for complete content including figures, references, and detailed experimental data.*
