# ut_common — UT 通用库

> UT workflow 各 skill 共享的通用模块与可执行脚本（2026-08-06 重组后）。

---

## 📂 结构

```
ut_common/
├── *.py                  # 通用模块（import 使用）
│   ├── config_loader.py      # 配置/路径加载
│   ├── workflow_state_manager.py  # workflow_state 读写 + lock
│   ├── update_test_load_two_phase.py  # 重试结果回写 test_load
│   ├── migrate_manifest.py   # manifest 迁移
│   ├── validate_schema.py    # JSON/YAML schema 校验
│   ├── load_filter_rules.py  # 过滤规则加载（filter_rules.yaml）
│   ├── path_setup.py / ut_runner.py / bastion_signals.py
├── scripts/              # 通用可执行脚本（subprocess/CLI 调用）
│   ├── check_expected.py        # run-vs-expected 比较器（2026-08-06 迁入）
│   ├── generate_test_load.py    # manifest → test_load（2026-08-06 迁入）
│   ├── check_hf_cache_refs.py   # HF 缓存预检（2026-08-06 迁入）
│   ├── feishu_api.py            # 飞书 API
│   └── ...（其他 skill 共享脚本）
├── schemas/               # JSON Schema（manifest/handled_tests 等）
├── two-phase-handler/     # Phase 1/2 处理脚本（phase2_stage1/2 等）
└── tests/                 # 单元测试
```

## 迁移约定（2026-08-06）

- **多 skill 引用的通用脚本** → `scripts/`（原 `tasks/ut/scripts/`）
- **run 专用脚本** → 留在 `tasks/ut/scripts/`（见其 README）
- 迁移后引用方统一指向本目录，勿改回旧路径

*更新时间: 2026-08-06*
