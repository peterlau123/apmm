# Kanban-mode operations — concrete `hermes kanban` recipe

Companion to §6 (Kanban mode). §6 says *what* the supervisor does abstractly;
this file is the *how*, using the actual CLI. Board slug for UT is **`apmm-ut`**.

All workflow python must run with `export PYTHONPATH=` (see §3.1 pitfall).

## 0. Reconnect Bastion first (almost always needed)

`agent.py ping` OK ≠ usable. Probe with a real round-trip, reconnect if dead:

```bash
cd /d/workspace/apmm
python tools/agent.py -p t_h20 run --timeout 25 "echo REMOTE_OK && hostname"
# "Socket is closed" → session dead → reconnect with a fresh user OTP.
```

**Do NOT launch `serve` as a plain foreground terminal call.** `agent.py serve`
holds the SSH session for the lifetime of the daemon — it does not exit. If
you run it from the supervisor's `terminal` tool with the default ~180s
timeout, the tool will SIGKILL the process at 180s, leaving the daemon in a
half-broken state: `ping` keeps reporting `[OK] Daemon is running` (the listener
socket survives) but every subsequent `run` returns `Socket is closed` because
the SSH channel was torn down mid-handshake. This bit us in three consecutive
resume attempts (runs #9–#11 of `ut-20260621-234651`, 2026-06-22) before the
pattern was identified.

**Correct re-serve sequence**:

```bash
# 1. Drain any half-dead daemon FIRST. Otherwise serve's stop_running_daemon
#    step races with your new process.
python tools/agent.py -p t_h20 stop      # returns "[OK] Daemon stopped" or "[--] was not running"

# 2. Launch serve as a TRUE long-lived background process via the terminal
#    tool's background=true (NOT shell `&` / `nohup`). This is one of the
#    legitimate uses of background=true documented in the terminal tool: a
#    long-lived process that never exits, so notify_on_complete=false is
#    correct (there is no exit to notify on). Example call:
#
#      terminal(
#        command="cd /d/workspace/apmm && export PYTHONPATH= && \
#                 python tools/agent.py serve t_h20 --otp <6-digit>",
#        background=True,
#        notify_on_complete=False,
#      )
#
# 3. Wait ~25s for SSH handshake + 2nd-password negotiation, then probe.
#    SSH negotiation can take 15–30s; probing too early reports "not running".
sleep 25
python tools/agent.py -p t_h20 ping       # expect [OK] Daemon is running

# 4. STABILITY GATE — verify across a real time window before trusting the
#    daemon enough to unblock workers. Two-point check spaced ≥60s apart:
python tools/agent.py -p t_h20 run --timeout 25 "echo OK1 && hostname && date"
sleep 90
python tools/agent.py -p t_h20 run --timeout 25 "echo STILL_OK && date"
# Both must return real stdout, not "Socket is closed". A daemon that passes
# only the first probe is the classic 180s-foreground-kill half-broken state
# from above — go back to step 1.
```

Note: `agent.py stop` takes no positional argument (errors with `t_h20`).
Pass the profile only via `-p`.

## 1. Preflight (matches §3 step 6)

```bash
cd /d/workspace/apmm && export PYTHONPATH= && python -c "
import sys; sys.path.insert(0,'skills/ut/workflow/scripts'); sys.path.insert(0,'skills/ut')
import yaml, json
from hermes_runner import validate_required_config, check_gateways_alive
cfg = yaml.safe_load(open('.agents/workflow.yaml', encoding='utf-8'))
ok, missing = validate_required_config(cfg)
g = check_gateways_alive()
print('CONFIG_OK', ok, 'MISSING', missing)
print('KANBAN', (cfg.get('kanban') or {}).get('enabled'))
print('GATEWAYS', json.dumps(g), 'ALL_UP', all(g.values()))
"
```
All-`True` gateways → Kanban viable. `hermes gateway status` cross-checks PIDs.

## 2. Init the run

```bash
cd /d/workspace/apmm && export PYTHONPATH= && \
  python skills/ut/workflow/scripts/init_workflow_state.py --workflow-yaml .agents/workflow.yaml
# Writes runs/<test_name>-<ts>/ (manifest.json, test_list.txt, workflow_state.json)
# and updates .agents/current_run.json. Read run_dir back from current_run.json.
```

## 3. Clean stale board + create the first orchestrator task

```bash
# Inspect — stale runs leave blocked orchestrator/executor tasks behind:
hermes kanban --board apmm-ut list
hermes kanban --board apmm-ut show <id>        # read the blocker comment
# A common legacy blocker: "t_h20 daemon needs p2 / interactive password" —
# that is the SSH-session-dead problem; fixed by the OTP re-serve in step 0.
hermes kanban --board apmm-ut archive <stale_id>   # clear stale tasks

# Create the round-1 orchestrator task. `create` takes TITLE as a POSITIONAL arg
# (NOT --title) and these flags: --assignee --priority --workspace --body
# --idempotency-key --skill (repeatable) --max-runtime.
hermes kanban --board apmm-ut create "UT Workflow: Orchestrate run <run_id>" \
  --assignee ut-orchestrator \
  --priority 1 \
  --workspace "dir:D:/workspace/apmm" \
  --idempotency-key "ut-orch-<run_id>" \
  --body "Orchestrate UT run for run_dir=<run_dir>. Use .agents/workflow.yaml.
Remote exec MUST use: python tools/agent.py -p t_h20 run (NOT plain ssh).
Container v0.13.0_torch2.5.1_compile. Bastion t_h20 VERIFIED LIVE (REMOTE_OK).
Run all workflow python with PYTHONPATH empty. distributed tests -> executor
verifies remote GPU>=2. Each round: call hermes_runner.orchestrator_round(
run_dir, manifest_path, prev_batch_dir, batch_size) to reconcile prev batch
(Stage5) + select next (Stage2), then create ut-executor + ut-fixer(depends on
executor) + next orchestrator(depends on fixer). Complete when pending_count==0."
```
- Use `--workspace dir:<project_root>` so the worker can reach `.agents/`,
  `tools/`, `skills/`, `runs/`. (Default `scratch` would isolate it from these.)
- `--idempotency-key` prevents duplicate orchestrator tasks if you re-fire.

The gateway dispatcher (default 60s tick, often faster) claims the task →
status flips `ready → running`. Round 1 emits the chain:
`ut-executor: batch_0001` + `ut-fixer: handle batch_0001 failures` (depends on
executor) + `ut-orchestrator: Continue after batch_0001` (depends on fixer),
then the round-1 orchestrator task goes `done`.

## 4. Poll progress (read-only — supervisor never touches the manifest)

```bash
hermes kanban --board apmm-ut list                 # task graph + statuses
hermes kanban --board apmm-ut show <id> | grep -E "^\s+\[2026"   # heartbeat notes
# manifest stats (read-only):
cd /d/workspace/apmm && export PYTHONPATH= && python -c "
import json; m=json.load(open('<run_dir>/manifest.json',encoding='utf-8'))
print(json.dumps(m.get('statistics',{}),ensure_ascii=False))"
```
Terminal: manifest `statistics.pending == 0` AND no running/todo executor tasks.

## 5. Hand off to an async monitor — don't block the turn

These runs are long (remote distributed GPU pytest, multi-minute per test).
Instead of polling turn-by-turn, create a `cronjob` (every ~10min, capped
repeat, deliver=origin, toolsets [terminal,file]) that reports manifest stats +
board state, surfaces any `blocked`/`failed` task or Bastion-ping failure as
"NEEDS ATTENTION", and on completion reports final counts + the auto-fix log
`git -C /d/workspace/apmm log master..2.5.1_ut_verify --oneline`. The monitor is
strictly read-only — it must never create/modify/archive tasks or edit configs.

## Gotchas seen in practice
- `hermes kanban create` rejects `--title`; the title is positional.
- `agent.py` has no `status` subcommand; valid: serve/stop/ping/run/shell/
  upload/download/send/cancel/setcreds/profiles.
- Gateway logs (`.agents/logs/gateway_<profile>.log`) show benign Feishu
  WebSocket drop+reconnect (DNS `open.feishu.cn`); not a workflow failure.

## 6. Resuming a `blocked` worker task (Bastion-loss path)

When a worker (typically ut-executor) returned `next_action=wait` because the
Bastion daemon dropped, the supervisor's loop is to: (a) restore Bastion per
§0 with the stability gate, (b) post a precise resume comment, (c) unblock,
(d) confirm dispatcher re-claim within ~10s.

CLI cadence:

```bash
# After §0's stability gate passes:
hermes kanban --board apmm-ut comment <task_id> "$(cat .agents/_resume_comment.txt)"
# Use `comment <task_id> <text...>` — NOT `--body`. Title/body live on create only.

hermes kanban --board apmm-ut unblock <task_id> \
  --reason "Daemon re-launched as background process; 2x round-trip verified over 90s. Resuming."

# Verify within ~10s — dispatcher tick is fast:
sleep 10
hermes kanban --board apmm-ut list   # task should flip to ● running
```

### Worker self-recovery anti-pattern

Stop the worker from burning OTP attempts on its own. The ut-executor SOUL.md
authorises it to call `request_daemon_approval.py` when `ping`/`run` fail,
but in practice the worker can spend 10–15 minutes spinning through
`serve --otp` attempts that never receive a code (the human OTP is delivered
to the supervisor's Feishu channel, not the worker's). Observed in
`ut-20260621-234651` runs #10 (886s wasted) and #11 (316s wasted).

The resume comment **must** include explicit guidance the worker can follow:

> If `agent.py run` returns `Socket is closed` or commands time out
> mid-batch: comment `next_action=wait` with `blocked_reason="bastion
> daemon dropped"` and STOP. Do NOT loop on `serve --otp` —
> supervisor owns OTP recovery on the Feishu channel.

This is in addition to (not a replacement for) the `sudo -n docker exec`
reminder and the `bash -c` allowlist note.

### Diagnosing repeated blocks on the same task

If the same task blocks 2+ times in one session, the runs log shows the
pattern. `hermes kanban --board apmm-ut show <id>` ends with a `Runs (N):`
section — read it before unblocking again, because three different blocker
strings can mean the same underlying problem (e.g. all three of
"Socket is closed", "ping OK but run timeout", and "needs fresh OTP" are
the half-broken-daemon symptom from §0). Track which root cause you've
addressed; if the next failure has the same shape, the fix wasn't durable.
