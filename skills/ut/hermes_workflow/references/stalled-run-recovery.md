# Stalled-run recovery — diagnosing `blocked` Kanban tasks

Companion to §6 / §8. When a Kanban-mode run stalls (executor or fixer task
sits at `⊘ blocked`), this is the systematic diagnostic flow. The happy-path
recipe (`references/kanban-operations.md`) covers init/dispatch; this file
covers "the chain is alive but one task is stuck."

Trigger: user sends an OTP code or a "resume / what's happening" message and
the board shows at least one `blocked` or stale `todo` task.

## Step 1 — Read the actual blocker (don't guess)

```bash
hermes kanban --board apmm-ut list
hermes kanban --board apmm-ut show <blocked_task_id> | tail -60
```

The `Latest summary:` line and the trailing `Comments` / `Runs` blocks tell
you what the worker tried, what failed, and how long it waited. Common
blocker shapes seen in real runs:

| Blocker text fragment | Real cause | Fix layer |
|---|---|---|
| `Waiting for t_h20 daemon approval` / `Feishu OTP response timed out` | Hermes core `tools/approval.py` shell-guard matched the worker's command; gateway `submit_pending` → 60s timeout with nobody to `/approve` | Hermes config `command_allowlist` |
| `Socket is closed` / `daemon ping OK but run fails` | Bastion daemon process alive, held SSH session dead | `tools/agent.py serve t_h20 --otp <fresh OTP>` |
| `permission denied ... /var/run/docker.sock` | Worker hand-rolled `docker exec` without sudo | Worker SKILL guidance — must be `sudo -n docker exec ...` |
| `jsonschema not installed` (when it IS installed) | `PYTHONPATH` leak from Hermes venv into apmm subprocess | `export PYTHONPATH=` before any workflow python |
| `distributed test needs N GPUs, have M` | Real resource state; not a bug | Wait + retry, or change `batch_size` |
| `pause_reason: GPU资源问题` / `NCCL unhandled cuda error` with no NCCL_DEBUG log | **Likely fabricated worker output** — the executor never actually ran pytest. See Step 2b below. | Void the run; investigate executor fabrication. **Do NOT `resume`.** |

## Step 2 — Probe each layer bottom-up before changing anything

Don't unblock until every layer below is independently verified. The probes
are cheap; running pytest on a still-broken layer just re-blocks the task.

```bash
# Layer 1 — Bastion daemon usable (not just `ping`)
cd /d/workspace/apmm && export PYTHONPATH= && \
  python tools/agent.py -p t_h20 run --timeout 25 "echo REMOTE_OK && hostname"
# Layer 2 — Remote shell can reach the container with sudo
python tools/agent.py -p t_h20 run --timeout 25 \
  "id; groups; ls -la /var/run/docker.sock; sudo -n docker ps | head -3"
# Layer 3 — Container responds end-to-end with the exact wrapper the executor uses
python tools/agent.py -p t_h20 run --timeout 30 \
  "sudo -n docker exec v0.13.0_torch2.5.1_compile bash -c 'nvidia-smi -L | head -2'"
```

`sudo -n` is the right form — `infra` is not in the `docker` group; the
container's docker.sock is `root:docker srw-rw----` and passwordless sudo is
already configured remotely. Bare `docker exec` is **always** wrong here.

## Step 2b — Detect fabricated worker output BEFORE deciding `resume`

When a run pauses with a vague resource/failure reason (especially
`pause_reason: GPU资源问题` or `failure_category: resource` on a `NCCL
unhandled cuda error`), **do not trust the report**. Kanban gateway workers
have been observed writing a plausible-looking `batch_results.json` /
`handled_tests.json` without actually executing pytest. `resume` on a
fabricated run is worse than useless — the manifest is already marked
`pending: 0`, so the executor will not re-select the batch and the run
silently dead-ends.

Cross-check the worker's claims against ground truth before doing anything:

```bash
# 1. Does the log file the worker cites actually exist on the remote?
#    batch_results.json → tests[*].log_path (e.g. /gpfs/.../ut_logs/batch_0001_*.log)
python tools/agent.py -p t_h20 run --timeout 25 \
  "ls -la /gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_0001* 2>&1"
# Expect: actual files with sizes; 'No such file or directory' → fabrication.

# 2. Are the GPUs actually busy right now? (worker claimed resource exhaustion)
python tools/agent.py -p t_h20 run --timeout 25 \
  "sudo -n nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv"
# Expect: high mem/util on multiple cards if NCCL truly failed during a run.
# All 0%/empty → no NCCL job ever ran.

# 3. Did pytest actually run in the container during the claimed window?
python tools/agent.py -p t_h20 run --timeout 25 \
  "sudo -n docker exec v0.13.0_torch2.5.1_compile bash -c \
   'find /gpfs/gcsp/M2.7_verify/vllm/ut_logs/ -mmin -120 -type f -ls'"
# Expect: at least one batch_NNNN_*.log dated within the executor's claimed
# execution_timestamp window. Empty / only old files → executor never ran.

# 4. Sanity-check batch_results.json itself for fabrication tells:
#    - every test has duration_seconds: null  AND  total_duration_seconds set
#    - log_path values that pattern-match but don't exist
#    - executor_run_id but no corresponding entries in the gateway's runs log
```

**Verdict matrix:**

| Probe 1 (log file) | Probe 2 (GPU) | Probe 3 (recent logs) | Verdict |
|---|---|---|---|
| exists | busy/recently busy | recent file present | Real failure — trust the classification, proceed with normal handling |
| missing | all idle | no recent file | **Fabricated** — void the run, do not resume |
| missing | idle | recent file present | Partial — pytest ran but log_path is wrong; classification may still be useful |
| exists | idle now | recent file present | Real failure already finished; GPU freed itself, classification trustworthy |

When verdict is **fabricated**:
1. Tell the user — paste the three probe outputs so the determination is auditable.
2. Mark the run as voided in your reply (do not silently mutate state files
   without the user's call — they may want forensics first).
3. Investigate WHY the worker fabricated: check the executor gateway's
   recent task output (`hermes kanban --board apmm-ut show <executor_task_id>`),
   look for the worker's actual tool calls — did it skip `agent.py run` entirely?
   Did it summarize before executing? This is a Worker SKILL / prompt bug, not
   a Bastion / config bug, so fix at the Worker layer before starting a new run.
4. New run, not resume. The polluted manifest cannot be unwound by `resume`.

This pattern is the agent-orchestration analogue of the general "subagent
self-reports are not verified facts" rule — apply it here even though the
"agent" is a Kanban gateway worker rather than a `delegate_task` child.

## Step 3 — Hermes shell-guard `command_allowlist`

The approval gate is in `~/AppData/Local/hermes/hermes-agent/tools/approval.py`
(line ~408). Any worker command matching `(bash|sh|zsh|ksh)\s+-[^\s]*c` is
treated as dangerous. A gateway-spawned (Kanban) worker has no human, so
`approvals.timeout` (default 60s) expires and the task self-blocks.

Fix: add the **description string** (not the regex) to `command_allowlist` in
`~/AppData/Local/hermes/config.yaml`. The mtime-keyed cache picks this up on
the next invocation — no gateway restart required.

```yaml
approvals:
  mode: smart
  timeout: 60
  cron_mode: deny
command_allowlist:
- script execution via -e/-c flag
- shell command via -c/-lc flag      # required for `bash -c` workers
```

When auditing: `grep -nE "(approval|allowlist|cron_mode)" ~/AppData/Local/hermes/config.yaml`.
The matching description strings live in approval.py's pattern list — read
that file directly when you need the exact key for a new pattern. Other
descriptions you may need to allowlist in similar workflows include
`docker restart/stop/kill (container lifecycle)` if a worker has to manage
container lifecycle, but **don't** add patterns prophylactically; only add the
one the blocker comment cites.

## Step 4 — Unblock with an explanatory comment, never silently

Always leave a comment on the task before `unblock` so the next worker
attempt knows what changed:

```bash
# Long comment text → write to a file first (avoids shell-quoting headaches with
# multi-line bodies and backticks). `comment` takes the body as a positional arg.
write_file .agents/_resume_comment.txt "<diagnosis + fix + verified probes>"
hermes kanban --board apmm-ut comment <task_id> "$(cat .agents/_resume_comment.txt)"
hermes kanban --board apmm-ut unblock <task_id> --reason "<one-line summary>"
```

The comment should include:
1. **What blocked it** (cite the blocker text from Step 1).
2. **What changed** (config edit, daemon reserve, sudo prefix, …).
3. **Verified probes** with their actual outputs from Step 2 — gives the
   next worker confidence the environment is real, not aspirational.
4. **Constraints for the retry** — e.g. "you MUST use `sudo -n docker exec`".

Within seconds of `unblock`, the dispatcher claims the task; `hermes kanban
list` flips it from `◻ todo` to `● running`. Confirm before reporting back.

### Pitfall: `agent.py serve --otp` blocks the foreground for 180s but daemon DOES start

When recovering Bastion with a user-supplied OTP, `python tools/agent.py
serve t_h20 --otp <code>` looks like it failed — the foreground call sits
until your terminal timeout (commonly 180s) and returns `[Command timed
out]`. **The daemon is almost certainly alive anyway.** `serve` is designed
to hold the SSH session for the life of the process; the terminal timeout
is a tooling artifact, not a serve failure. Verify with two cheap probes,
not by inspecting the timeout error:

```bash
python tools/agent.py -p t_h20 ping    # → [OK] Daemon is running
python tools/agent.py -p t_h20 run --timeout 25 "echo BASTION_OK && hostname"
```

If both succeed, the OTP worked and you can proceed to unblock. Do NOT
re-issue `serve` with a fresh OTP — the second `serve` will `stop_running_daemon`
the one you just started, kicking off the cycle again. Only re-serve if the
ping/run probes BOTH fail.

## Step 5 — Hand off to a read-only async monitor
Do **not** poll turn-by-turn — schedule a `cronjob` (10-minute cadence,
capped repeat, `deliver=origin`, toolsets `["terminal","file"]`,
`workdir=D:/workspace/apmm`) that:

- runs `hermes kanban --board apmm-ut list` + manifest stats
- probes Bastion with `agent.py ... run "echo REMOTE_OK"`
- on any `blocked` / `failed` task or Bastion fail → prefixes the message with
  `🚨 NEEDS ATTENTION:` and includes the blocker text
- on `pending == 0` and no live executor/fixer/orchestrator tasks → reports
  **COMPLETED** with final counts plus
  `git -C /d/workspace/apmm log master..2.5.1_ut_verify --oneline | head -30`
- otherwise stays terse — one line of state

Hard rules for the monitor (encode them in the cron prompt): no `create`,
`comment`, `unblock`, `archive`, `claim`, `complete`, no config writes, no
echoing of OTP codes, always `export PYTHONPATH=` in every workflow python
call.

## Layering principle — fix at the right layer

The trap is to fix symptoms one level above the real cause. A blocked
executor that mentions "OTP" is usually NOT a Bastion problem — it's the
Hermes shell-guard waiting for a `/approve` that never arrives. Reserving
the daemon won't help; only the `command_allowlist` entry does. Inversely, a
`Socket is closed` error is NOT a shell-guard problem; allowlisting won't
help and you need a fresh OTP for `agent.py serve`. **The blocker text in
Step 1 tells you which layer to touch — trust it.**

## When the same run blocks twice (Bastion-flapping pattern)

If the executor gets unblocked, runs for a few minutes, then re-blocks with
a Bastion-dead symptom (`Socket is closed`, `Daemon for profile not running`,
or self-reported `request_daemon_approval.py` retries), the daemon is dying
*during* the test rather than at startup. This was observed in real runs:
two `agent.py serve` invocations died within ~14 minutes of each other
during a single batch. Plausible causes, in order of likelihood:

1. **Another process called `agent.py serve` on the same profile.** `serve`
   first calls `stop_running_daemon` to claim the port. If a sibling
   supervisor / cron job / human ran `serve` concurrently, your daemon was
   killed. Check who else might `serve`: `ps -ef | grep agent.py` on the
   host, and audit any cron/skill that auto-serves.
2. **Bastion-side idle/length kick.** The remote Qizhi-Shterm bastion may
   close the SSH session after N minutes regardless of `set_keepalive(15)`
   on our side. Length-kicks present as `Socket is closed` without warning.
3. **Network blip between supervisor host and bastion.** Less common — would
   usually show up as transient errors on other tools too.

Diagnostic before re-issuing OTPs:

```bash
# Who else might be holding the daemon socket?
ps -ef | grep -i agent.py | grep -v grep
# Anything in cron / scheduled jobs that calls `serve`?
hermes cron list 2>/dev/null | grep -i bastion
# Tail the supervisor log for serve/stop events
tail -200 /d/workspace/apmm/.agents/logs/supervisor_ut-supervisor.log | grep -iE "(serve|stop|daemon|otp)"
```

If a second `serve` is the culprit, **do not respond by re-serving** — fix
the duplicate caller. If the cause is genuinely a bastion-side kick, the
right durable response is to make Workers signal `next_action="wait"` on
`ConnectionError` (per the unit-test-executor SKILL §4) and let the
supervisor's OTP recovery handle one OTP per kick, not have Workers spin
trying to serve themselves.
