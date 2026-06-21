# Frozen Hermes profiles for L4 test

These are the **behavior-defining** files of the 4 Hermes agent profiles the L4
Kanban test depends on. They are frozen here so L4 is reproducible — the live
profiles under `~/AppData/Local/hermes/profiles/` are otherwise unversioned and
can drift.

| Profile | Role in L4 |
|---------|-----------|
| `ut-orchestrator` | Stage 2 select + Stage 5 reconcile; decomposes into batches, assigns to executor, spawns fixer tasks |
| `ut-executor` | Runs pytest batches on remote t_h20 via Bastion/Docker |
| `ut-fixer` | Analyzes failures, classifies, attempts fixes (delegates download/network to dependency-resolver) |
| `ut-supervisor` | Long-running Feishu-subscribing agent driving the hermes_workflow loop |

## What is frozen (and what is NOT)

Each `<profile>/` dir here holds **only 3 files**:

| File | Why frozen |
|------|-----------|
| `SOUL.md` | The agent persona/instructions — the real behavioral contract |
| `profile.yaml` | Hermes profile description (minimal schema) |
| `channel_directory.json` | Feishu chat binding (`platforms.feishu[].id`) |

**Intentionally excluded** (do not snapshot these):

- `auth.json`, `*.lock` — secrets / locks
- `config.yaml` — machine-specific provider config with `${ENV}` API-key refs and
  Hermes defaults; **not** L4-specific behavior (its `channel_skill_bindings` is `[]`;
  skill loading comes from repo skills + `x-deploy` wiring)
- `state.db*`, `sessions/`, caches, logs, `gateway*` — runtime state

## Deploy / verify

```powershell
# diff frozen vs live (no write)
python tests/ut/integration/deploy_l4_profiles.py --check
# install frozen files into live Hermes profiles (preserves auth/state)
python tests/ut/integration/deploy_l4_profiles.py
# then confirm readiness
python tests/ut/integration/start_l4_test.py --status
```

If a live profile dir is absent, create it first: `hermes profile create <name>`,
then re-run the deploy script.

> Source of truth captured: 2026-06-21 from the live Hermes install on this machine.
