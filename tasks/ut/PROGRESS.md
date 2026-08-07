# 单元测试进度追踪

> **只记录测试用例运行进度**，每周更新一次，每次标记时间戳。
> 兼容性问题/事故/工作记录见 [docs/incidents/](docs/incidents/) 与 [docs/reports/](docs/reports/)。

---

## 2026-08-06（run ut-20260806-103121：8000 cases 全量）

| 指标 | 数值 |
|------|:----:|
| 总测试用例数 | 8,000 |
| ✅ passed | 6,871 |
| ❌ failed | 1,129 |
| ⚠️ error | 0 |
| ⏸️ ignored | 0 |
| **通过率** | **85.9%** |

**本周进展**：8000 cases 全量执行完成（0 ignored——排除坏卡 GPU1 + 7 卡并行）。
**marlin 算子修复成功**（2026-08-07）：`_moe_C` 扩展 JIT 完整重编译（11 个编译
blocker 攻破），2,638 个用例救回，通过率 **52.9% → 85.9%**。剩余 1,129 确定性
失败（inductor 编译 402 + FP8 cat 208 + DeepGEMM 127 + float8_e8m0fnu 72 + 其他）。
manifest 同步：progress 35.1% → **59.4%**（executed 19,562 / passed 17,398 /
pending 12,505）。详见
[docs/reports/2026-08-06-vllm-0.13.0-torch2.5.1-8000cases-compat-issues.md](docs/reports/2026-08-06-vllm-0.13.0-torch2.5.1-8000cases-compat-issues.md)。

---

## 2026-08-05（run ut-20260718-164107 收官）

| 指标 | 数值 |
|------|:----:|
| 总测试用例数 | 4,000 |
| ✅ passed | 3,454 |
| ❌ failed | 251 |
| ⚠️ error | 8 |
| ⏸️ ignored | 287 |
| **通过率** | **86.4%** |

**本周进展**：Phase 2 三轮重跑（全量 727 batch / kernel 556 / fql 403）完成，
通过率 35.5% → 86.4%（+2,036 用例）。详见
[docs/reports/2026-08-05-phase2-retry-final-summary.md](docs/reports/2026-08-05-phase2-retry-final-summary.md)。

---

<!-- 每周更新模板：
## YYYY-MM-DD（本周）

| 指标 | 数值 |
|------|:----:|
| 总测试用例数 | {TOTAL} |
| ✅ passed | {PASSED} |
| ❌ failed | {FAILED} |
| ⚠️ error | {ERROR} |
| ⏸️ ignored | {IGNORED} |
| **通过率** | **{PCT}%** |

**本周进展**：{一句话总结}。详见 {报告链接}。
-->
