# UT Workflow Integration Tests

测试hermes-workflow各Stage链路集成。

## 测试范围

| 测试文件 | 测试内容 |
|----------|----------|
| `test_batch_flow.py` | batch-selector → executor → manifest-updater链路 |
| `test_kanban_mode.py` | Kanban模式完整链路（supervisor + workers） |

## 运行方式

```bash
pytest tests/ut/workflow/integration/ -v
```

## Fixtures

- `sample_batch_config.json`: 标准batch配置模板

---

*创建日期: 2026-06-26*