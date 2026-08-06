# 单元测试进度追踪

> **只记录测试用例运行进度**，每周更新一次，每次标记时间戳。
> 兼容性问题/事故/工作记录见 [docs/incidents/](docs/incidents/) 与 [docs/reports/](docs/reports/)。

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
