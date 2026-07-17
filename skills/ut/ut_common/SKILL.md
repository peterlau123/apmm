---
name: ut-common
description: "Shared infrastructure for the UT workflow: schema validation, config loading, workflow state management, Bastion/Feishu integration, and the two-phase handler. Imported by all UT workflow skills."
version: 1.0.0
when_to_use: "Imported automatically by other UT skills. Not invoked directly."
---

# ut-common

Shared Python library and infrastructure for the UT workflow. All other UT skills
import from this package via `from skills.ut.ut_common import ...`.

## Structure

```
ut_common/
├── __init__.py                  # Package exports
├── ut_runner.py                 # UT runner API
├── validate_schema.py           # Schema validation
├── workflow_state_manager.py    # workflow_state.json CRUD
├── config_loader.py             # workflow.yaml loader
├── load_filter_rules.py         # filter_rules.yaml loader
├── bastion_signals.py           # Bastion disconnect tokens
├── path_setup.py                # sys.path bootstrap
├── update_test_load_two_phase.py
├── migrate_manifest.py
├── filter_rules.yaml            # Test filter rules
├── scripts/                     # Standalone scripts
│   ├── bastion_manager.py
│   ├── feishu_api.py
│   ├── start_gateway.py
│   ├── check_environment.py
│   └── migrate_manifest.py
├── schemas/                     # Schema definitions
│   ├── manifest_schema.json
│   ├── workflow_schema.yaml
│   ├── workflow_state_schema.json
│   └── dependency_stall_schema.json
├── assets/
│   └── manifest_example.json
├── tests/
│   └── test_workflow_state_manager.py
└── two-phase-handler/
    ├── SKILL.md
    └── scripts/
        ├── phase2_stage1.py
        └── phase2_stage2.py
```

## Key APIs

```python
from skills.ut.ut_common import validate_and_write, get_paths, get_config, is_distributed
from skills.ut.ut_common.ut_runner import BastionManager, FeishuAPI
```
