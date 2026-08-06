# 单元测试兼容性问题检查报告（vLLM 0.13.0 + torch 2.5.1）

> 窗口：2026-07-31 17:00 ~ 2026-08-06 10:20｜生成：2026-08-06 10:20
> **相对上周增量**：新增报告/incident **8** 个，ut_logs 新增入库 runs **+2289** / test_cases **+8530**

## 目录
1. 本周增量发现
2. 新增报告 / incidents
3. ut_logs 入库增量
4. 兼容性问题清单
5. 结论与下周关注点

## 1. 本周增量发现（相对上周）
- **[2026-08-04-phase2-timeout-retry-fixes-and-resume](tasks/ut/docs/reports/2026-08-04-phase2-timeout-retry-fixes-and-resume.md)**: 全量重试稳定运行中：727 个 timeout batch、外部并发 2、per-test timeout 600s。
- **[2026-08-04-phase2-timeout-retry-fixes-and-resume](tasks/ut/docs/reports/2026-08-04-phase2-timeout-retry-fixes-and-resume.md)**: 2. 生成 `phase2_stage2_report.json`（哪些 batch 重试了、成功/失败）
- **[2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues](tasks/ut/docs/reports/2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md)**: cuda:1）→ 全部因卡 1 异常崩。
- **[2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues](tasks/ut/docs/reports/2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md)**: rendezvous timeout（torch timeout 参数）；③ 接受 failed（编译重活不适合本环境）。
- **[2026-08-05-gpu1-hardware-fault-incident](tasks/ut/docs/incidents/2026-08-05-gpu1-hardware-fault-incident.md)**: 任何 kernel 在 cuda:1 上执行都触发 illegal memory access（读悬垂内存）。
- **[2026-08-05-gpu1-hardware-fault-incident](tasks/ut/docs/incidents/2026-08-05-gpu1-hardware-fault-incident.md)**: NVRM: Xid (PCI:0000:18:00): 31, pid=1553988, name=python3
- **[2026-08-05-kernel-cuda-visible-devices-param-notfound-incident](tasks/ut/docs/incidents/2026-08-05-kernel-cuda-visible-devices-param-notfound-incident.md)**: → pytest ERROR: not found → 收集 0 items → 结果被标 ignored（超时/收集 0）
- **[2026-08-05-kernel-cuda-visible-devices-param-notfound-incident](tasks/ut/docs/incidents/2026-08-05-kernel-cuda-visible-devices-param-notfound-incident.md)**: 无 testcase → execute_batch 判 `JUnit XML has no <testcase>` → ignored（timeout 类）。

## 2. 新增报告 / incidents
| 文件 | 类型 | 时间 |
|---|---|---|
| [2026-08-04-phase2-timeout-retry-fixes-and-resume.md](tasks/ut/docs/reports/2026-08-04-phase2-timeout-retry-fixes-and-resume.md) | report | 08-04 15:02 |
| [2026-08-05-phase2-full-retry-summary.md](tasks/ut/docs/reports/2026-08-05-phase2-full-retry-summary.md) | report | 08-05 16:37 |
| [2026-08-05-phase2-retry-final-summary.md](tasks/ut/docs/reports/2026-08-05-phase2-retry-final-summary.md) | report | 08-06 07:00 |
| [2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md](tasks/ut/docs/reports/2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md) | report | 08-06 08:54 |
| [2026-08-03-test-list-count-loss-incident.md](tasks/ut/docs/incidents/2026-08-03-test-list-count-loss-incident.md) | incident | 08-03 21:38 |
| [2026-08-05-gpu1-hardware-fault-incident.md](tasks/ut/docs/incidents/2026-08-05-gpu1-hardware-fault-incident.md) | incident | 08-06 09:29 |
| [2026-08-05-kernel-cuda-visible-devices-param-notfound-incident.md](tasks/ut/docs/incidents/2026-08-05-kernel-cuda-visible-devices-param-notfound-incident.md) | incident | 08-05 13:59 |
| [2026-08-06-compat-check.md](tasks/ut/docs/reports/weekly/2026-08-06-compat-check.md) | report | 08-06 10:12 |

## 3. ut_logs 入库增量
| 指标 | 本周新增 |
|---|---|
| runs | +2289 |
| test_cases | +8530 |

## 4. 兼容性问题清单
完整清单见 [2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md](../2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md)。本周新增问题见 §2 列出的报告/incident。

## 5. 结论与下周关注点
- 待办：GPU 1 卡硬件维修（上报管理员）、慢测试 rendezvous timeout 优化

*更新时间: 2026-08-06*
