# Hermes Workflow Deployment Implementation Plan (Plan 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Hermes production channel on top of the Plan 1 foundation: close the 4 integration gaps found in Plan 1's smoke test, wire the supervisor loop to the v5 Worker functions, add the `hermes_workflow` skill + `ut-supervisor` profile (Feishu-subscribing, OTP auto-recovery), and enable Kanban mode where `ut-orchestrator` owns Stage 2+5.

**Architecture:** A long-running `ut-supervisor` Hermes Agent profile subscribes to Feishu and drives `loop_core`. Three independent `hermes-gateway@<profile>` systemd units handle Kanban worker dispatch. The supervisor never runs Stage logic in Kanban mode — it monitors. In linear mode it drives Stage 2-5 through the v5 Worker functions. All remote calls reuse the Plan 1 Bastion-aware `run_remote`.

**Tech Stack:** Python 3.10+, pytest, Hermes Agent/Gateway, systemd, Feishu webhook + message API, JSON Schema, Markdown.

**Reference Spec:** `docs/superpowers/specs/2026-06-18-hermes-workflow-dual-channel-design.md` (v5)

**Depends on:** Plan 1 (`docs/superpowers/plans/2026-06-19-hermes-workflow-foundation.md`) — MERGED to master. All v5 Worker functions (`select_batch`, `write_batch_config`, `execute_batch`, `analyze_failed_tests_v5`, `update_manifest`) and `hermes_runner` API exist.

---

## ⚠️ Phase 0 First: Close Plan 1 Integration Gaps

Plan 1's end-to-end smoke (`tests/integration/run_linear_smoke.py`) proved the pipeline wires together but surfaced 4 contract gaps. These MUST be closed before supervisor wiring, because the supervisor chains exactly these functions.

| Gap | Symptom | Fix location |
|-----|---------|--------------|
| G1 | `config_loader.get_config` returns nested `{remote:{server,docker,vllm_dir}}` but `execute_batch` reads flat `config["remote_server"]` etc. → silently uses hardcoded defaults | Standardize on ONE config shape |
| G2 | `write_batch_config` output lacks `remote_server`/`docker_container`/`timeout`/`pytest_args` that `execute_batch` needs from workflow_state | Define the workflow_state→execute_batch config contract |
| G3 | `analyze_failed_tests_v5` calls `ensure_on_branch` unconditionally (network) | Make branch-check injectable/skippable |
| G4 | selector emits `test_id`, executor reads `test_node` | Align field name across the two functions |

(G4's pytest `-q`→`-v` half was already fixed in Plan 1 commit `974c860`. The remaining G4 here is the `test_id` vs `test_node` field-name mismatch.)

---

## File Structure (Plan 2 scope)

### Created
- `skills/ut/hermes_workflow/SKILL.md` — Hermes-channel supervisor skill
- `skills/ut/hermes_workflow/profile.yaml` — ut-supervisor profile config (Feishu subscribe + auto-load skill)
- `skills/ut/hermes_workflow/ut-orchestrator-SOUL.md` — repo-tracked SOUL template (copied to profile dir at deploy)
- `docs/guides/hermes-supervisor-service.md` — `hermes-agent@ut-supervisor` systemd deploy guide
- `docs/guides/hermes-gateway-service.md` — `hermes-gateway@.service` template (3 instances)
- `tests/skills/ut/test_config_contract.py` — config shape contract tests (G1/G2)
- `tests/skills/ut/test_field_alignment.py` — test_id/test_node alignment (G4)
- `tests/skills/ut/test_otp_resend.py` — OTP progressive resend schedule
- `tests/skills/ut/test_kanban_orchestrator.py` — ut-orchestrator Stage 2+5 cycle

### Modified
- `skills/ut/unit-test-executor/scripts/execute_batch.py` — injectable exec_config (G1/G2), accept test_id (G4)
- `skills/ut/failure-handler/scripts/analyze_failures.py` — injectable ensure_on_branch (G3)
- `skills/ut/workflow/scripts/hermes_runner.py` — get_execute_config, parse_command, refresh_manifest_stats, orchestrator_round
- `skills/ut/workflow/scripts/bastion_manager.py` — OTP progressive resend schedule
- `tests/integration/run_linear_smoke.py` — remove harness shims now gaps closed
- `tasks/ut/README.md` — link Plan 2 deliverables

---

## Phase 0: Close Integration Gaps

### Task 0.1: Single config contract (G1/G2)

**Files:**
- Modify: `skills/ut/workflow/scripts/hermes_runner.py`
- Modify: `skills/ut/unit-test-executor/scripts/execute_batch.py`
- Test: `tests/skills/ut/test_config_contract.py` (new)

**Decision:** `execute_batch` reads a FLAT config dict. The supervisor/runner flattens `workflow.yaml`'s nested config. Adaptation lives in one place (`get_execute_config`).

- [ ] **Step 1: Write the failing test**

```python
import json
def test_get_execute_config_flattens_nested(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"config": {
        "remote": {"server": "t_h20", "docker": "v0.13.0_torch2.5.1_compile",
                   "vllm_dir": "/gpfs/gcsp/M2.7_verify/vllm"},
        "batch_size": 8, "timeout": 600, "pytest_args": "-v --tb=long"}}))
    from skills.ut.workflow.scripts.hermes_runner import get_execute_config  # adapt to importlib if needed
    cfg = get_execute_config(state_path)
    assert cfg["remote_server"] == "t_h20"
    assert cfg["docker_container"] == "v0.13.0_torch2.5.1_compile"
    assert cfg["timeout"] == 600
    assert cfg["pytest_args"] == "-v --tb=long"
    assert cfg["remote_log_dir"].endswith("/ut_logs")
```

- [ ] **Step 2: Run test → FAIL.** `cd D:/workspace/apmm && python -m pytest tests/skills/ut/test_config_contract.py -v`

- [ ] **Step 3: Implement `get_execute_config` in hermes_runner.py**

```python
def get_execute_config(state_path) -> dict:
    """Flatten workflow_state nested config into the flat keys execute_batch expects."""
    import json
    from pathlib import Path
    c = json.loads(Path(state_path).read_text()).get("config", {})
    remote = c.get("remote", {})
    vllm_dir = remote.get("vllm_dir", "/gpfs/gcsp/M2.7_verify/vllm")
    return {
        "remote_server": remote.get("server", "t_h20"),
        "docker_container": remote.get("docker", "v0.13.0_torch2.5.1_compile"),
        "timeout": c.get("timeout", 600),
        "pytest_args": c.get("pytest_args", "-v --tb=long"),
        "remote_log_dir": c.get("remote_log_dir", f"{vllm_dir}/ut_logs"),
    }
```

- [ ] **Step 4: Make execute_batch accept injected config**

In `execute_batch.py`:
```python
def execute_batch(batch_config_path, workflow_state_path, *, exec_config: dict | None = None) -> dict:
    ...
    config = exec_config if exec_config is not None else get_config(workflow_state_path)
    remote_server = config.get("remote_server", "t_h20")
    # ... rest unchanged
```

- [ ] **Step 5: Run tests → PASS.** `python -m pytest tests/skills/ut/test_config_contract.py tests/skills/ut/test_execute_batch_v5.py -v`

- [ ] **Step 6: Commit**

```bash
git add skills/ut/workflow/scripts/hermes_runner.py skills/ut/unit-test-executor/scripts/execute_batch.py tests/skills/ut/test_config_contract.py
git commit -m "fix(G1/G2): get_execute_config flattener + injectable exec_config in execute_batch"
```

---

### Task 0.2: Injectable branch check (G3)

**Files:**
- Modify: `skills/ut/failure-handler/scripts/analyze_failures.py`
- Test: `tests/skills/ut/test_analyze_failures_v5.py` (extend)

- [ ] **Step 1: Failing test** (use existing importlib loading pattern in that test file)

```python
def test_analyze_skips_branch_check_when_disabled(monkeypatch):
    af = _load_analyze_failures()  # reuse the module-load helper in this test file
    calls = {"n": 0}
    monkeypatch.setattr(af, "ensure_on_branch", lambda *a, **k: calls.__setitem__("n", calls["n"]+1))
    af.analyze_failed_tests_v5([{"test_id": "t1", "status": "failed"}], run_dir=None, check_branch=False)
    assert calls["n"] == 0
```

- [ ] **Step 2: Run → FAIL** (no check_branch param).

- [ ] **Step 3: Add `check_branch` param**

```python
def analyze_failed_tests_v5(tests, *, run_dir=None,
                            vllm_repo_path="/gpfs/gcsp/M2.7_verify/vllm",
                            expected_branch="2.5.1_ut_verify",
                            check_branch: bool = True):
    if check_branch:
        ensure_on_branch(expected_branch, vllm_repo_path)
    processable = filter_processable(tests)
    # ... rest unchanged
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add skills/ut/failure-handler/scripts/analyze_failures.py tests/skills/ut/test_analyze_failures_v5.py
git commit -m "fix(G3): make ensure_on_branch injectable via check_branch flag"
```

---

### Task 0.3: Align test_id / test_node (G4)

**Files:**
- Modify: `skills/ut/unit-test-executor/scripts/execute_batch.py`
- Test: `tests/skills/ut/test_field_alignment.py` (new)

**Decision:** `execute_batch` accepts either `test_node` or `test_id` (prefer `test_node`, fall back to `test_id`).

- [ ] **Step 1: Failing test** (mock run_remote like test_execute_batch_v5.py does)

```python
def test_execute_batch_accepts_test_id_field(tmp_path):
    import json
    from pathlib import Path
    batch_dir = tmp_path / "batch_x"; batch_dir.mkdir()
    cfg = {"batch_id": "batch_x", "iteration": 1, "run_id": "ut",
           "tests": [{"test_id": "tests/test_a.py::test_x", "selected_reason": "pending"}]}
    (batch_dir / "batch_config.json").write_text(json.dumps(cfg))
    # mock run_remote → PASSED, assert no KeyError on test_node, batch_results.json written
```

- [ ] **Step 2: Run → FAIL** (KeyError 'test_node').

- [ ] **Step 3: Tolerate both fields**

```python
def _node(t: dict) -> str:
    return t.get("test_node") or t["test_id"]
test_nodes = [_node(t) for t in tests]
# and in classification:
status, error_type = _classify_for_test(summary_text, _node(t))
```

- [ ] **Step 4: Run → PASS.** `python -m pytest tests/skills/ut/test_field_alignment.py tests/skills/ut/test_execute_batch_v5.py -v`

- [ ] **Step 5: Commit**

```bash
git add skills/ut/unit-test-executor/scripts/execute_batch.py tests/skills/ut/test_field_alignment.py
git commit -m "fix(G4): execute_batch accepts test_id or test_node"
```

---

### Task 0.4: Re-run smoke without harness shims

**Files:**
- Modify: `tests/integration/run_linear_smoke.py`

- [ ] **Step 1: Replace manual key injection** with `get_execute_config` + raw selector output:

```python
from skills.ut.workflow.scripts.hermes_runner import get_execute_config
exec_cfg = get_execute_config(state_path)
result = execute_batch(batch_config_path, state_path, exec_config=exec_cfg)
```

- [ ] **Step 2: Run smoke (requires live bastion)**

```bash
python tools/agent.py -p t_h20 ping
timeout 600 python tests/integration/run_linear_smoke.py 2>&1 | tail -20
```

Expected: PIPELINE PASS, 3/3 passed, no shims.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/run_linear_smoke.py
git commit -m "test(integration): smoke uses get_execute_config + raw selector output"
```

---

## Phase 1: OTP Progressive Resend

### Task 1.1: OTP resend schedule

**Files:**
- Modify: `skills/ut/workflow/scripts/bastion_manager.py`
- Test: `tests/skills/ut/test_otp_resend.py` (new)

- [ ] **Step 1: Failing test**

```python
from skills.ut.workflow.scripts.bastion_manager import otp_resend_delay, otp_should_at_user
def test_resend_schedule():
    assert [otp_resend_delay(i) for i in (1,2,3,4,5,99)] == [5,15,30,60,60,60]
def test_resend_at_user_marker():
    assert otp_should_at_user(3) is True
    assert otp_should_at_user(2) is False
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
_OTP_SCHEDULE = {1: 5, 2: 15, 3: 30, 4: 60}
def otp_resend_delay(attempt: int) -> int:
    return _OTP_SCHEDULE.get(attempt, 60)
def otp_should_at_user(attempt: int) -> bool:
    return attempt >= 3
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add skills/ut/workflow/scripts/bastion_manager.py tests/skills/ut/test_otp_resend.py
git commit -m "feat(bastion): OTP progressive resend schedule (5/15/30/60min, @user from 3rd)"
```

---

## Phase 2: Feishu Command Parsing + manifest_stats

### Task 2.1: parse_command

**Files:**
- Modify: `skills/ut/workflow/scripts/hermes_runner.py`
- Test: `tests/skills/ut/test_hermes_runner_api.py` (extend)

- [ ] **Step 1: Failing tests**

```python
from skills.ut.workflow.scripts.hermes_runner import parse_command
def test_parse_stop(): assert parse_command("结束")["type"] == "stop"
def test_parse_pause(): assert parse_command("暂停")["type"] == "pause"
def test_parse_resume(): assert parse_command("继续")["type"] == "resume"
def test_parse_otp():
    c = parse_command("123456"); assert c["type"]=="otp" and c["payload"]["code"]=="123456"
def test_parse_change_config():
    c = parse_command("改 batch_size=4"); assert c["type"]=="change_config" and c["payload"]["batch_size"]=="4"
def test_parse_change_config_whitelist_only():
    assert "unknown_key" not in parse_command("改 unknown_key=9")["payload"]
def test_parse_non_command(): assert parse_command("这个测试为什么失败") is None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
import re
_WHITELIST = {"batch_size", "pytest_args", "max_retry_per_test", "timeout"}
_STOP = ("结束", "终止", "停止"); _PAUSE = ("暂停",); _RESUME = ("继续",)
_OTP_RE = re.compile(r"^\s*(\d{6})\s*$"); _KV_RE = re.compile(r"(\w+)\s*=\s*(\S+)")
def parse_command(text: str):
    t = text.strip()
    if any(k in t for k in _STOP): return {"type": "stop", "payload": {}}
    if any(k in t for k in _PAUSE): return {"type": "pause", "payload": {}}
    if any(k in t for k in _RESUME): return {"type": "resume", "payload": {}}
    m = _OTP_RE.match(t)
    if m: return {"type": "otp", "payload": {"code": m.group(1)}}
    if t.startswith("改"):
        return {"type": "change_config",
                "payload": {k: v for k, v in _KV_RE.findall(t) if k in _WHITELIST}}
    return None
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add skills/ut/workflow/scripts/hermes_runner.py tests/skills/ut/test_hermes_runner_api.py
git commit -m "feat(hermes_runner): parse Feishu commands with config whitelist"
```

---

### Task 2.2: refresh_manifest_stats

**Files:**
- Modify: `skills/ut/workflow/scripts/hermes_runner.py`
- Test: `tests/skills/ut/test_hermes_runner_api.py` (extend)

- [ ] **Step 1: Failing test**

```python
def test_refresh_manifest_stats(tmp_path):
    import json
    from pathlib import Path
    mp = tmp_path/"manifest.json"; mp.write_text(json.dumps({"version":"2.0","tests":[
        {"test_id":"t1","status":"passed"},{"test_id":"t2","status":"pending"},
        {"test_id":"t3","status":"running"}],"statistics":{}}))
    sp = tmp_path/"state.json"; sp.write_text(json.dumps({"config":{}}))
    from skills.ut.workflow.scripts.hermes_runner import refresh_manifest_stats
    refresh_manifest_stats(sp, mp)
    s = json.loads(sp.read_text())["manifest_stats"]
    assert s["pending"]==1 and s["running"]==1 and s["passed"]==1
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
def refresh_manifest_stats(state_path, manifest_path) -> dict:
    import json
    from pathlib import Path
    manifest = json.loads(Path(manifest_path).read_text())
    stats = {}
    for t in manifest["tests"]:
        stats[t["status"]] = stats.get(t["status"], 0) + 1
    state = json.loads(Path(state_path).read_text())
    state["manifest_stats"] = stats
    Path(state_path).write_text(json.dumps(state, indent=2))
    return stats
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add skills/ut/workflow/scripts/hermes_runner.py tests/skills/ut/test_hermes_runner_api.py
git commit -m "feat(hermes_runner): refresh_manifest_stats feeds check_stop_conditions"
```

---

## Phase 3: Kanban orchestrator (Stage 2+5)

### Task 3.1: orchestrator_round

**Files:**
- Modify: `skills/ut/workflow/scripts/hermes_runner.py`
- Test: `tests/skills/ut/test_kanban_orchestrator.py` (new)

- [ ] **Step 1: Failing test**

```python
def test_orchestrator_round_reconciles_then_selects(tmp_path):
    import json
    from pathlib import Path
    run_dir = tmp_path/"run"; run_dir.mkdir()
    mp = run_dir/"manifest.json"; mp.write_text(json.dumps({"version":"2.0","tests":[
        {"test_id":"t1","status":"pending","retry_count":0,"max_retry":3,"last_batch_id":None},
        {"test_id":"t2","status":"pending","retry_count":0,"max_retry":3,"last_batch_id":None}],
        "statistics":{}}))
    prev = run_dir/"batch_prev"; prev.mkdir()
    (prev/"batch_results.json").write_text(json.dumps({"batch_id":"batch_prev",
        "tests":[{"test_id":"t1","status":"passed"}]}))
    from skills.ut.workflow.scripts.hermes_runner import orchestrator_round
    r = orchestrator_round(run_dir=run_dir, manifest_path=mp, prev_batch_dir=prev, batch_size=8)
    m = json.loads(mp.read_text())
    assert next(t for t in m["tests"] if t["test_id"]=="t1")["status"]=="passed"
    assert r["next_batch"]["selected_count"]==1
    assert r["next_batch"]["tests"][0]["test_id"]=="t2"
    assert r["completed"] is False
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** (use importlib helper to load v5 functions from hyphenated skill dirs)

```python
def orchestrator_round(*, run_dir, manifest_path, prev_batch_dir, batch_size):
    """Kanban ut-orchestrator round: Stage 5 (reconcile prev) then Stage 2 (select next)."""
    import json
    from pathlib import Path
    update_manifest = _load_fn("manifest-updater", "update_manifest", "update_manifest")
    select_batch = _load_fn("batch-selector", "generate_batch", "select_batch")
    write_batch_config = _load_fn("batch-selector", "generate_batch", "write_batch_config")
    manifest = json.loads(Path(manifest_path).read_text())
    if prev_batch_dir is not None:
        br = Path(prev_batch_dir)/"batch_results.json"
        if br.exists():
            batch_results = json.loads(br.read_text())
            hp = Path(prev_batch_dir)/"handled_tests.json"
            handled = json.loads(hp.read_text()) if hp.exists() else {"tests": []}
            manifest = update_manifest(manifest, batch_results, handled)
            Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    pending_like = [t for t in manifest["tests"]
                    if t["status"] in ("pending","fixed_pending_verify")
                    or (t["status"] in ("retriable_error","failed") and t["retry_count"]<t["max_retry"])]
    if not pending_like:
        return {"completed": True, "next_batch": None}
    selected = select_batch(manifest, batch_size)
    nb = f"batch_{len(list(Path(run_dir).glob('batch_*')))+1:04d}"
    nd = Path(run_dir)/nb; nd.mkdir(exist_ok=True)
    write_batch_config(path=nd/"batch_config.json", batch_id=nb, iteration=0,
                       run_id=Path(run_dir).name, selected=selected)
    return {"completed": False, "next_batch": json.loads((nd/"batch_config.json").read_text())}
```

Add `_load_fn(skill_dir, module, fn_name)` importlib helper if absent.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add skills/ut/workflow/scripts/hermes_runner.py tests/skills/ut/test_kanban_orchestrator.py
git commit -m "feat(kanban): orchestrator_round combines Stage 5 reconcile + Stage 2 select"
```

---

### Task 3.2: ut-orchestrator SOUL template

**Files:**
- Create: `skills/ut/hermes_workflow/ut-orchestrator-SOUL.md` (repo-tracked; copied to profile dir at deploy)

- [ ] **Step 1: Write the SOUL content**

```markdown
## UT Orchestrator (Stage 2 + Stage 5)

Each round, when claimed by Gateway:
1. Read previous batch's batch_results.json + handled_tests.json
2. Run manifest-updater logic → update manifest.json (Stage 5)
3. Check pending_count; if zero → mark workflow complete
4. Otherwise run batch-selector (Stage 2) → create:
   - new batch task (assignee=ut-executor)
   - fix task (assignee=ut-fixer, depends_on=executor)
   - next orchestrator task (depends_on=fixer)

Loads SKILLs: batch-selector + manifest-updater.
Uses hermes_runner.orchestrator_round() for reconcile+select.
```

- [ ] **Step 2: Commit**

```bash
git add skills/ut/hermes_workflow/ut-orchestrator-SOUL.md
git commit -m "docs(kanban): ut-orchestrator SOUL template (Stage 2+5)"
```

---

## Phase 4: hermes_workflow skill + profile

### Task 4.1: hermes_workflow/SKILL.md

**Files:**
- Create: `skills/ut/hermes_workflow/SKILL.md`

- [ ] **Step 1: Write the skill** (frontmatter name: hermes_workflow). Cover (from spec §14, §8, §9, §10):
  - Channel: Hermes Agent (ut-supervisor profile), Feishu bidirectional, auto Bastion recovery, full state machine
  - Startup (§14.2): Feishu msg → load this + workflow_loop_core + 4 Worker SKILLs → param-confirm card → validate required config (incl 3 Gateway active when kanban.enabled) → init_or_resume → ensure_bastion (OTP progressive resend via otp_resend_delay) → start_heartbeat → loop_core.run
  - Callbacks: handle_checkpoint (refresh_manifest_stats + progress card + parse_command); handle_bastion_disconnect (waiting_otp + progressive resend); check_user_commands (read Feishu group, parse_command)
  - State machine (§8): running/paused/waiting_otp/completed/stopped/failed; command matrix; priority stop>pause>change_config>resume; daemon-restart-fail stays waiting_otp
  - Linear vs Kanban loop (§14.3): Kanban uses check_gateways_alive + orchestrator-driven rounds; supervisor never touches manifest in Kanban
  - resume mapping (§9); pending_config apply/discard (§10)
  - Reference spec path

- [ ] **Step 2: Commit**

```bash
git add skills/ut/hermes_workflow/SKILL.md
git commit -m "feat(hermes_workflow): create Hermes-channel supervisor skill"
```

---

### Task 4.2: ut-supervisor profile.yaml

**Files:**
- Create: `skills/ut/hermes_workflow/profile.yaml`

- [ ] **Step 1: Inspect a real profile** under `~/AppData/Local/hermes/profiles/ut-orchestrator/` to learn the actual profile format. Adapt the keys below to match.

- [ ] **Step 2: Write profile config**

```yaml
# ut-supervisor — long-running Hermes Agent profile for hermes_workflow
name: ut-supervisor
description: UT Workflow production supervisor (Feishu-subscribing, OTP auto-recovery)
feishu:
  subscribe: true
  chat_id: "<feishu_chat_id>"          # set at deploy
  trigger_keywords: ["跑 ut workflow", "启动测试", "开始 UT"]
auto_load_skills:
  - ut/hermes_workflow
  - ut/workflow_loop_core
  - ut/batch-selector
  - ut/unit-test-executor
  - ut/failure-handler
  - ut/manifest-updater
```

- [ ] **Step 3: Commit**

```bash
git add skills/ut/hermes_workflow/profile.yaml
git commit -m "feat(hermes_workflow): ut-supervisor profile config"
```

---

## Phase 5: Deployment guides

### Task 5.1: hermes-supervisor-service.md

**Files:**
- Create: `docs/guides/hermes-supervisor-service.md`

- [ ] **Step 1: Write systemd guide**: `hermes-agent@ut-supervisor.service` unit; enable/start/status/logs; Feishu chat_id + bastion creds prerequisites; relationship to 3 Gateway services.

- [ ] **Step 2: Commit**

```bash
git add docs/guides/hermes-supervisor-service.md
git commit -m "docs(deploy): hermes-agent@ut-supervisor systemd guide"
```

---

### Task 5.2: hermes-gateway-service.md

**Files:**
- Create: `docs/guides/hermes-gateway-service.md`

- [ ] **Step 1: Write systemd template guide**: `hermes-gateway@.service` template; 3 instances (ut-orchestrator/ut-executor/ut-fixer); `systemctl enable --now hermes-gateway@ut-{orchestrator,executor,fixer}`; mapping to `check_gateways_alive()`; board `apmm-ut` prerequisite.

- [ ] **Step 2: Commit**

```bash
git add docs/guides/hermes-gateway-service.md
git commit -m "docs(deploy): hermes-gateway@ systemd template guide (3 instances)"
```

---

## Phase 6: README navigation

### Task 6.1: Link Plan 2 deliverables

**Files:**
- Modify: `tasks/ut/README.md`

- [ ] **Step 1: Add nav rows** for hermes_workflow skill, ut-supervisor service guide, gateway service guide, under existing Skills/docs tables. Keep existing rows intact.

- [ ] **Step 2: Commit**

```bash
git add tasks/ut/README.md
git commit -m "docs(readme): link hermes_workflow skill + deployment guides"
```

---

## Self-Review Checklist

- [ ] Spec coverage:
    - §14.0 process model → Tasks 4.1, 4.2, 5.1, 5.2
    - §14.2 startup → Task 4.1
    - §14.3 main loop linear+kanban → Tasks 4.1 + 3.1
    - §16.6 ut-orchestrator Stage 2+5 → Tasks 3.1, 3.2
    - §7/§8.5 OTP progressive resend → Task 1.1 + 4.1
    - §8 state machine + command matrix → Tasks 2.1 + 4.1
    - §10 pending_config → Task 2.1 (parse) + Plan 1 apply_pending_config
    - Integration gaps G1-G4 → Tasks 0.1-0.4
- [ ] No placeholders: clean
- [ ] Method consistency: get_execute_config / orchestrator_round / parse_command / refresh_manifest_stats / otp_resend_delay spelled consistently

---

## Out of Scope (Plan 2)

- Real Hermes Agent runtime testing (requires Hermes install + Feishu bot + 3 live Gateways) — deploy-time verification, documented in guides, not automatable here
- ut-bastion Worker (spec §19)
- Test file-level granularity (spec §19)
- generate_report.py (spec §19)
- OOM-targeted adaptive batch_size (spec §19)

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-20-hermes-workflow-deployment.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task/batch; review between.

**2. Inline Execution** — Execute via `executing-plans`; batch with checkpoints.

Which approach? (Note: Phase 0-3 are pure-code/TDD, verifiable now; Phase 0.4 re-smoke needs live bastion; Phases 4-6 skill/profile/docs need deploy-time verification on a real Hermes host.)
