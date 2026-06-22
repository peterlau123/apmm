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

Each `<profile>/` dir here holds **2 frozen files**:

| File | Why frozen |
|------|-----------|
| `SOUL.md` | The agent persona/instructions — the real behavioral contract |
| `profile.yaml` | Hermes profile description (minimal schema) |

`channel_directory.json` is **not** frozen — it lives in the live profile dir
as user-owned data (machine-specific Feishu chat binding) and is preserved
across deploys.

**Intentionally excluded** (do not snapshot these):

- `auth.json`, `*.lock` — secrets / locks
- `channel_directory.json` — Feishu chat binding, machine-specific (user-owned)
- `config.yaml` — machine-specific provider config with `${ENV}` API-key refs and
  Hermes defaults; preserved across deploys (user-owned)
- `state.db*`, `sessions/`, caches, logs, `gateway*` — runtime state

Skills are **not** frozen here either — they are owned by the repo root
`skills/ut/<skill>/` (the authoritative source) and assembled into each
profile's distribution by `deploy_tier.py` per the profile's skills subset.

## Deploy / verify

`deploy_tier.py` ships each profile as a Hermes **profile distribution**:
it assembles a distribution source (`.dist/<profile>/` — gitignored build
artifact) from the fixture files + repo skills, then runs
`hermes profile install --force` (user data preserved, only distribution-owned
files overwritten).

```powershell
# diff repo sources vs live Hermes profiles (no write)
python tasks/ut/scripts/deploy_tier.py --tier L4 --check
# install distributions into live Hermes profiles (preserves auth/state/config)
python tasks/ut/scripts/deploy_tier.py --tier L4
# one profile only
python tasks/ut/scripts/deploy_tier.py --tier L4 --profile ut-supervisor
# then confirm readiness
python tasks/ut/scripts/start_hermes_ut_runtime.py --status
```

After deploy, `hermes profile info <name>` should report the profile
**is a distribution** (has `distribution.yaml`). To re-sync after editing repo
sources, re-run the deploy command — or `hermes profile update <name>` (re-pulls
from the recorded `.dist/<name>/` source, so re-run deploy first to refresh
that directory).

If a live profile dir is absent, create it first: `hermes profile create <name>`,
then re-run the deploy script.

## Profile -> skills subset

Per `hermes_workflow` SKILL §3 step 3 (supervisor load list) + §6 (worker Stage
ownership):

| Profile | skills/ut/<subset> |
|---------|--------------------|
| `ut-supervisor` | hermes_workflow, workflow_loop_core, batch-selector, unit-test-executor, failure-handler, manifest-updater |
| `ut-orchestrator` | batch-selector, manifest-updater |
| `ut-executor` | unit-test-executor |
| `ut-fixer` | failure-handler, dependency-resolver |

`ut-test-collector` (Stage 1) and `workflow` (linear-channel scheduler) are NOT
hermes profile skills — they belong to the linear channel / one-shot collection.
