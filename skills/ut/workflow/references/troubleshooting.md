# workflow 问题解决手册

## 常见问题分类

| 问题类别 | 典型场景 | 处理方式 |
|---------|---------|---------|
| **飞书卡片通过率错误** | 显示0.0% | 修改 pass_rate 计算 |
| **failed测试未被处理** | batch-selector不选 | 增加 failed 选择 |
| **execution配置未使用** | 有配置但不读 | 删除冗余配置 |

---

## 飞书卡片通过率显示 0.0%

**解决方案**：
修改 `send_progress_card.py:63`，动态计算 pass_rate。

---

## failed 测试未被处理

**解决方案**：
修改 `batch-selector/SKILL.md`，增加 failed 状态选择逻辑。

---

## execution 配置未被使用

**解决方案**：
删除 `.agents/workflow.yaml` 的 execution 配置块。

---

*创建日期: 2026-06-14*