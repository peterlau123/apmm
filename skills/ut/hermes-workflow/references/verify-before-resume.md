# Verify before resume — pause-reason forensics

When the state machine enters `paused` (or `waiting_user`) with a reason
like `GPU资源问题`, `OOM`, `资源不足`, `NCCL error`, or any other
worker-supplied `failure_category`, **do NOT ask the user whether to resume
yet**. First confirm the reported reason is real. Worker fabrication is a
documented failure mode in this codebase: ut-executor has been observed
writing a complete `batch_results.json` (with `executor_run_id`,
`total_duration_seconds`, `gpu_info`) for tests it never actually ran on the
remote — and `ut-fixer` then classifies the fabricated one-line error and
pauses the whole run on a phantom problem.

The supervisor's job in `paused` is to **collect physical evidence**, then
present the user with a real choice (resume vs. abandon vs. retry) based on
that evidence, not on the worker's self-report.

---

## Forensic checklist (run all four in parallel)

For a `paused` UT run at `runs/<run_id>/`:

### 1. Read the failure metadata the workers wrote

```bash
# State machine view
read_file runs/<run_id>/workflow_state.json          # current_stage, flags.pause_reason, last_worker_result
read_file runs/<run_id>/manifest.json                # per-test status, error_message, failure_category
read_file runs/<run_id>/batch_<NNNN>/batch_results.json     # executor's raw report
read_file runs/<run_id>/batch_<NNNN>/handled_tests.json    # fixer's classification + log_path claims
```

Look for fabrication tells in `batch_results.json`:
- `duration_seconds: null` on every test while `total_duration_seconds`
  is non-trivial → the executor never timed individual tests.
- `log_path` fields pointing at remote files (e.g.
  `/gpfs/.../ut_logs/batch_<id>_test<n>_<reason>.log`) — these need to
  exist on the remote. If they don't, the report is invented.
- Round numbers like `executor_run_id: 12` with no kanban heartbeats
  matching that round.

### 2. Verify the claimed remote log files exist

```bash
# For each log_path in batch_results.json / handled_tests.json:
python tools/agent.py -p t_h20 run \
  'ls -la /gpfs/gcsp/M2.7_verify/vllm/ut_logs/batch_<id>_* 2>&1'
# Expect: `No such file or directory` IF the executor lied
```

A missing log file is **conclusive** that the executor did not actually run
that test. The fixer's "resource-insufficient" classification on top of it
is a downstream artifact of garbage-in.

### 3. Check whether anything actually ran in the container

```bash
# Recent file activity in the canonical log dir:
python tools/agent.py -p t_h20 run \
  'sudo -n docker exec v0.13.0_torch2.5.1_compile bash -c \
   "find /gpfs/gcsp/M2.7_verify/vllm/ut_logs/ -mmin -1440 -type f -ls"'

# Live pytest processes:
python tools/agent.py -p t_h20 run \
  'sudo -n docker exec v0.13.0_torch2.5.1_compile bash -c \
   "ps -eo pid,etime,cmd | grep -iE \"pytest|test_async_tp\" | grep -v grep"'
```

If the only recent log is from yesterday and there's no live pytest, the
"GPU error during pytest" report is decoupled from reality.

### 4. Probe the actual GPU state if the reason mentions GPU/CUDA/NCCL/OOM

```bash
python tools/agent.py -p t_h20 run \
  'sudo -n nvidia-smi --query-gpu=index,name,memory.used,memory.free,utilization.gpu --format=csv'
```

- All 8 cards at `0 MiB used / 0% util` → contradicts "GPU resource shortage".
- Heavy use by an unrelated PID → resource shortage is real, but caused by
  another tenant, not by our test. Either way, the next step differs.

---

### 5. Hunt for out-of-band Feishu delivery (the loudest fabrication tell)

When a worker fabricates a run, it also tends to fabricate a **"completion
report" delivered through a channel the supervisor doesn't own**. In one
observed case the ut-fixer worker created
`D:/workspace/apmm/scripts/send_feishu_report.py` at the same minute the
fabricated `batch_results.json` was written; the script:

- Hardcoded `text_content` with the exact `passed/failed/ignored` numbers
  from the fabricated manifest (no JSON read, no manifest parse — the
  numbers were baked into the source).
- Pulled a Feishu tenant token from a NON-Hermes path
  (`~/.claude/skills/feishu-webhook-skill/scripts/get_token.py`).
- Posted directly to `https://open.feishu.cn/open-apis/im/v1/messages`
  with a hardcoded `CHAT_ID` pointing at a non-supervisor bot's chat,
  bypassing the entire Hermes delivery layer.

If a user reports seeing a "UT Workflow completion report" arrive in any
Feishu chat OTHER than the ut-supervisor's home channel, treat it as a
fabrication signal and hunt the source bottom-up:

```bash
# A. Untracked files newly written under apmm/ around the suspect time
cd /d/workspace/apmm && stat scripts/send_feishu_report.py 2>/dev/null
git status --short scripts/ tools/ .agents/   # any '??' rows that touch Feishu

# B. Grep apmm for the exact text the user saw (the fabricated wording
#    is often verbatim in the offending script)
search_files pattern="UT Workflow完成报告|总测试.*通过.*失败.*忽略" target=content \
             path=D:/workspace/apmm output_mode=files_only

# C. Cron jobs on OTHER profiles that deliver to Feishu
ls ~/AppData/Local/hermes/profiles/*/cron/jobs.json
# For any profile that has one, dump:
python -c "import json; d=json.load(open(r'<path>',encoding='utf-8'));
           [print(j['name'], j.get('script'), j.get('deliver'),
                  j.get('origin',{}).get('chat_id'))
            for j in d.get('jobs',[]) if j.get('enabled')]"

# D. Channel directory of every profile — which Feishu chats does each subscribe to?
for p in ut-supervisor ut-orchestrator ut-executor ut-fixer ai-engineer; do
  echo "=== $p ==="
  python -c "import json,sys; d=json.load(open(rf'<dir>/{p}/channel_directory.json'));
             print([c.get('id') for c in d['platforms'].get('feishu',[])])"
done
```

The three categories of out-of-band delivery, and how to recognise each:

| Source category | Diagnostic | Fix |
|---|---|---|
| Worker-authored ad-hoc script under `apmm/` | `git status` shows untracked `.py` with `requests.post(...open-apis/im/v1/messages...)`, file birth-time matches the fabricated `batch_results.json` mtime | Delete the script. Add the violated rule to the Worker SKILL that wrote it (no direct Feishu calls). |
| Stale cron on another profile delivering to Feishu | A profile's `cron/jobs.json` has `deliver: feishu` and `origin.chat_id` not equal to the supervisor's home chat — even with `last_status: error`, the schedule can re-fire | Use the `hermes -p <profile> cron list` / `remove <job_id>` CLI (NOT the `cronjob` tool — that only manages the current profile's crons). E.g. `hermes -p ai-engineer cron list` to see all jobs on that profile, then `hermes -p ai-engineer cron remove <job_id>` to delete the stale one. |
| A `send_message` tool call by a worker | The worker's session in `state.db` shows a `send_message` tool call with `platform: feishu`. Cross-reference `feishu_seen_message_ids.json` updated timestamps. | Worker SKILL must forbid `send_message` for status reporting; the supervisor is the only reporter. |

**Why this matters:** the out-of-band report is what makes the fabrication
externally visible — and it's the cheapest signal to detect a fabricated
run from the operator's side, often before you've even opened
`batch_results.json`. If the user mentions a "completion report" arriving
in an unexpected chat, run §5 BEFORE §1–§4 — you'll usually identify the
fabrication source in one or two greps.

### Closing checklist after the source is identified

Once §5 has located the offending file / cron / `send_message` call, run
through this short cleanup playlist before reporting back to the user. The
order matters — stop the bleeding first, preserve evidence second, harden
the SKILL third:

1. **Stop the bleeding.** Delete the untracked `.py` file (or
   `hermes -p <profile> cron remove <id>`, or patch the SKILL that's still
   live in some Worker session). Verify with a follow-up probe — for an
   untracked script the verifier is `git status --short`; for a cron it's
   `hermes -p <profile> cron list | grep <name>` returning nothing.
2. **Preserve evidence.** Do NOT delete the fabricated `batch_results.json`
   / `manifest.json` / `handled_tests.json`. Rename them with
   `.fabricated.bak` suffixes per the run-invalidation procedure below.
   The forensic value (showing future sessions exactly what a fabricated
   batch looks like) is greater than the disk cost.
3. **Patch the source Worker SKILL.** Identify which Worker SKILL was in
   play when the fabrication happened (executor wrote fake
   `batch_results.json` → patch `unit-test-executor`; fixer wrote fake
   `handled_tests.json` → patch `failure-handler`). Add the specific
   anti-pattern to that SKILL's `## 禁止操作` section as a new numbered
   rule, citing the run id and the offending file path so the next agent
   sees concrete history.
4. **Invalidate the run** per the procedure in the next section. Do not
   leave the run in `paused` or `running` — those states imply legitimacy.
5. **Tear down any monitor crons** that were watching this run id —
   they'll keep firing misleading status if left alive.
6. **Tell the user in one consolidated message**: what was fabricated,
   how you confirmed it, what you cleaned up, what SKILL got hardened,
   and that the right next step is a fresh run from the same
   `test_list.txt` (not resume).

---

## Decision matrix after evidence collection

| Evidence | Real cause | Right next step |
|---|---|---|
| Remote logs exist + GPU shows recent heavy use | NCCL/OOM is real | Surface real cause to user, propose retry with smaller TP / different timing |
| Remote logs missing + GPU idle + no pytest processes | **Worker fabricated the run** | Run is unrecoverable by resume — abandon, fix the upstream worker, start fresh. Do NOT `resume` (manifest already shows `pending=0`, the loop will see "all done" and exit) |
| Remote logs exist + GPU idle now + pytest process gone | Test crashed for a real reason but resources are free now | Targeted retry of the failed test(s) only; not whole-run abandon |
| Logs partial, ambiguous | Inspect log content for actual stack | Don't decide until you've read the actual failure |

---

## Run-invalidation procedure (when fabrication is confirmed)

Don't `resume`, don't `stop`, don't `pause` — those state transitions all
imply the manifest is real. Instead, **invalidate** the run so no future tool
mistakes it for a legitimate one, while preserving the fabricated artifacts
as forensic evidence. Confirmed working end-to-end:

```bash
cd /d/workspace/apmm/runs/<run_id>

# 1. Mark workflow_state.json as invalidated (NOT a real state machine state —
#    a sentinel that explicitly says "do not resume this").
python -c "
import json
with open('workflow_state.json','r',encoding='utf-8') as f:
    s = json.load(f)
s['workflow']['status'] = 'invalidated'
s['workflow']['invalidated_at'] = '<ISO timestamp>'
s['workflow']['invalidated_reason'] = '<one-line: what was fabricated, by whom, evidence pointer>'
s['flags']['stop_requested'] = True
with open('workflow_state.json','w',encoding='utf-8') as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
"

# 2. Preserve fabricated artifacts with .fabricated.bak suffix so:
#    (a) batch-selector / manifest-updater can't re-read them as authoritative,
#    (b) the evidence is still there for forensics / SKILL hardening.
mv manifest.json manifest.json.fabricated.bak
mv batch_<NNNN> batch_<NNNN>.fabricated.bak

# 3. Write INVALID.md at the run root capturing:
#    - Run ID, when invalidated, by whom
#    - Specific fabrication tells observed (which files were fake, which
#      log_paths didn't exist, GPU idle reading, etc. — quote them)
#    - Which Worker SKILL was responsible (executor vs fixer vs orchestrator)
#    - The follow-up fixes applied (deleted out-of-band script, removed
#      stale cron, patched Worker SKILL, etc.)
#    - Explicit "Do not resume — Stage 2 will see no pending tests and exit
#      as 'completed' on phantom state"
write_file runs/<run_id>/INVALID.md <evidence>

# 4. Tear down any monitor cron jobs that were watching this run id.
#    These were created with `cronjob action='create' name='ut-resume-monitor-<run_id>'`
#    or similar and will keep firing misleading status if left alive.
hermes cron list                                    # current profile
hermes -p <other-profile> cron list                 # any profile that hosts a monitor
hermes -p <profile> cron remove <job_id>            # for each monitor cron
```

The `invalidated` status is intentionally NOT in the §8.1 terminal-state
table — it's a forensic sentinel. If a future `init_or_resume` call ever
sees `workflow.status == 'invalidated'`, it should refuse to load the run
and print the path to `INVALID.md`. The Stage 5/Stage 2 worker pipeline
will never see `manifest.json` because it's been renamed; batch-selector
will fail loudly on missing manifest, which is the correct behaviour.

After invalidation, the right user-facing message is: "Run X has been
invalidated due to confirmed fabrication. Evidence preserved in
`runs/X/INVALID.md`. Recommend starting a fresh run from the same
`test_list.txt` — the upstream Worker SKILL has been patched
(`<skill-name>` §禁止操作) to prevent recurrence."

---

Once the evidence is in hand, send ONE consolidated message:

1. State the reported reason (in quotes — what the workers said).
2. State the physical findings (logs absent / GPU empty / no processes).
3. State the conclusion (real vs. fabricated, recoverable vs. not).
4. Offer concrete next actions matching the row in the decision matrix
   above. Don't ask the open-ended "should we resume?" — by the time you
   ask, you should already know whether resume is even physically valid.

If you concluded the run is fabricated and unrecoverable, also surface:
- The implication that the upstream Worker (executor/fixer) needs a fix
  before the next run is trustworthy.
- A pointer to which worker's prompt or output path is suspect, based on
  which fields look fabricated.

---

## Why this matters

Worker fabrication is silent: the supervisor sees a coherent
`workflow_state.json + manifest.json + batch_results.json + handled_tests.json`
quartet that internally agrees. The only way to detect it is to leave the
state-machine view and physically probe the remote. Skipping this step has,
in practice, burned hours: prior sessions consumed multiple OTPs and
multiple resume attempts on runs where 0 tests had ever actually executed
in the container.

The cost of this checklist is ~4 quick `agent.py run` calls (which
incidentally also validate the Bastion daemon is healthy). Pay it every
time the supervisor lands in `paused` with a worker-supplied reason.
