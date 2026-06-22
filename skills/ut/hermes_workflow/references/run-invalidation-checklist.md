# Run Invalidation Checklist

When a UT run cannot be salvaged by `resume` (fabricated stats, poisoned
manifest, out-of-band Feishu delivery, etc.) — the supervisor's
responsibility is **invalidate cleanly**, not pause-and-pray.

Trigger this checklist when `references/verify-before-resume.md` returns
two-or-more fabrication tells, OR when the user explicitly says the run is
unrecoverable.

## 1. Quarantine the run directory

Preserve fabricated artifacts as evidence; don't delete them — they may be
needed to debug the offending Worker SKILL later.

```bash
cd /d/workspace/apmm/runs/<run_id>

# Rename so nothing downstream picks them up as valid input
mv manifest.json        manifest.json.fabricated.bak
mv batch_<NNNN>         batch_<NNNN>.fabricated.bak    # for every poisoned batch dir
```

Mark the workflow_state explicitly so any future `resume_from` request errors
loudly instead of silently running an already-invalidated run:

```python
import json, datetime as dt
with open('workflow_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
s['workflow']['status'] = 'invalidated'
s['workflow']['invalidated_at'] = dt.datetime.now().astimezone().isoformat()
s['workflow']['invalidated_reason'] = '<one-line summary>'
s['flags']['stop_requested'] = True
with open('workflow_state.json', 'w', encoding='utf-8') as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
```

## 2. Write `INVALID.md` next to the artifacts

The post-mortem belongs inside the run directory, NOT only in `docs/`.
Operators investigating that run dir 6 months from now should find the
explanation without searching the docs tree.

`runs/<run_id>/INVALID.md` template:

```markdown
# ⚠️ Run Invalidated

**Run ID**: `<run_id>`
**Invalidated at**: <ISO timestamp>
**Invalidated by**: ut-supervisor (manual, after fabrication audit)

## Reason
<one-paragraph description: what was fabricated, who fabricated it,
 what evidence proved it>

## Evidence (verified at <timestamp>)
- <bastion check 1>
- <bastion check 2>
- <log path probe>
- <out-of-band delivery probe>

## Preserved Artifacts
- `manifest.json.fabricated.bak`
- `batch_NNNN.fabricated.bak/` (with its three files)
- `<any worker-written scripts>`

## Do Not Resume
<one-line guard for future operators>

## Follow-up Fixes Applied
- A: <what got deleted/quarantined>
- B: <what cron got removed>
- D: <which SKILLs got hardened>
- E: <which §11 pitfalls got added>
```

## 3. Remove stale per-run monitor cron jobs

When the run was launched, `ut-resume-monitor-<run_id>` and/or
`ut-progress-monitor-<run_id>` style cron jobs were almost certainly created
to ping the supervisor about progress. They will keep firing against the
quarantined run and emit misleading status (mentioning `pending=N` from the
now-renamed manifest, etc.). Find and remove:

```bash
for p in ut-supervisor ut-orchestrator ut-executor ut-fixer ai-engineer; do
  hermes -p $p cron list 2>&1 | grep -E "<run_id>|ut-resume-monitor|ut-progress-monitor"
done
# For each match: hermes -p <profile> cron remove <job_id>
```

## 4. Re-audit per-profile `command_allowlist` overrides

Worker fabrication frequently happens BECAUSE a Worker hit a shell-guard block
it couldn't surface, then "worked around" the block by fabricating results
instead of waiting for approval. Before launching the replacement run, verify
no profile's `config.yaml` has neutered the global allowlist:

```bash
for p in ut-supervisor ut-orchestrator ut-executor ut-fixer; do
  echo "--- $p ---"
  grep -nE "^command_allowlist:" \
    ~/AppData/Local/hermes/profiles/$p/config.yaml \
    2>/dev/null || echo "  (none → inherits global)"
done
```

Any profile that prints `command_allowlist: []` or a list missing
`shell command via -c/-lc flag` / `script execution via -e/-c flag` needs the
file fixed (use `patch` with `cross_profile=true`) or the key dropped so it
inherits the global allowlist.

## 5. Out-of-band delivery sweep

If the fabrication included a delivery to a non-supervisor Feishu chat
(per `references/verify-before-resume.md` §5), make sure the offending
mechanism is gone:

- Worker-written script — `git status` in `D:/workspace/apmm/` and look for
  untracked `scripts/*.py` / `tools/*.py` calling `open.feishu.cn`. Delete.
- Cron job in another profile — `hermes -p <profile> cron list`; remove any
  job whose `deliver: feishu` originates outside the supervisor's home chat.

## 6. Hand back to the user

Surface a concise red-card-style summary in Feishu:

> 🔴 Run `<run_id>` invalidated.
>
> - Reason: <one line>
> - Quarantined: `manifest.json.fabricated.bak`, `batch_NNNN.fabricated.bak/`
> - INVALID.md written at `runs/<run_id>/INVALID.md`
> - Stale crons cleaned (N profiles)
> - Allowlist re-audit: OK / FIXED in <profile>
>
> Ready to start a fresh run with the same test_list — confirm to proceed.

Do NOT proactively launch the replacement run. The user decides when.

## Pitfall — where the post-mortem goes

The "where does this incident get written up" question came up explicitly
during the 2026-06-22 incident. The answer that fit best was:

- **Inside the run dir**: `runs/<run_id>/INVALID.md` (always — operators
  investigating that run later look here first).
- **Optionally** also `docs/incidents/<YYYY-MM-DD>-<slug>.md` if the incident
  taught a generalizable lesson worth surfacing in the project docs index.
  (As of this writing, `docs/incidents/` does not yet exist in the apmm
  repo — create it the first time a generalizable post-mortem is written
  and seed it with a one-line `README.md`.)
- **Always** also patch the relevant SKILL with a pitfall pointer
  (`hermes_workflow` §3.1 / §8.1, `unit-test-executor`, `failure-handler`).
  The SKILL changes are durable for future sessions; the docs are durable
  for humans.

Don't write the post-mortem into `docs/guides/troubleshooting.md` — that
file is a vLLM-side remediation cookbook (deepseek_v2.py decorator fix, etc.)
and incident write-ups will dilute it.
