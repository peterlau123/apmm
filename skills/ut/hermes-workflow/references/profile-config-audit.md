# Cross-profile config audit (overlay hazards)

When the UT workflow runs in Kanban mode it spans 4 Hermes profiles:
`ut-supervisor` + `ut-orchestrator` + `ut-executor` + `ut-fixer`. Each has its
own `~/AppData/Local/hermes/profiles/<name>/config.yaml` that **overlays the
global** `~/AppData/Local/hermes/config.yaml`. A per-profile field can override
the global to a more restrictive value — this is the **overlay hazard**.

## The 2026-06-22 finding

After the L4 fabrication incident I added `shell command via -c/-lc flag` to
the global `command_allowlist`. Spot-checks on ut-supervisor / ut-orchestrator
/ ut-executor showed the allowlist was effective (no per-profile override).
But `ut-fixer/config.yaml:632` had:

```yaml
command_allowlist: []
quick_commands: {}
```

That **empty list** silently overrides the global, so the next ut-fixer worker
would have re-hit the 60s `submit_pending` block on the next `bash -c`. The
verification only caught it because I greped each profile config explicitly.

## Audit procedure (run before any new Kanban-mode L4 run)

```bash
for p in ut-supervisor ut-orchestrator ut-executor ut-fixer; do
  echo "--- $p ---"
  grep -nE "^command_allowlist:" \
    ~/AppData/Local/hermes/profiles/$p/config.yaml 2>/dev/null \
    || echo "  (none → inherits global)"
done
```

Expected: either every profile says `(none → inherits global)`, OR the explicit
value is `>=` the global set. An empty list `[]` on any profile is a bug.

## Fields to audit alongside `command_allowlist`

These all overlay-override and have hit us or are likely to:

| Field | Why it matters |
|---|---|
| `command_allowlist` | Restores `bash -c` / `python -c` from the dangerous-command guard |
| `approvals.mode` / `approvals.cron_mode` | If cron_mode is `deny` and a worker is spawned by a Gateway cron tick, every approval auto-rejects |
| `approvals.timeout` | 60s default; Kanban workers can't survive a longer prompt either |
| `hooks_auto_accept` | Per-profile false will block hooks that the user explicitly accepted globally |
| `feishu.channel_skill_bindings` | Worker profiles must be `'[]'` — they should NOT subscribe to Feishu (supervisor is the only subscriber per the §1 channel design) |

## Fix pattern

If a profile must override, override **upward** (more permissive than global for
worker autonomy on agreed-safe commands) — never downward into `[]` or stricter
than global without an explicit reason in a code comment.

```yaml
# ut-fixer/config.yaml:629-633
approvals:
  mode: manual
  timeout: 60
  cron_mode: deny
  mcp_reload_confirm: true
  destructive_slash_confirm: true
command_allowlist:           # MUST match or extend global; do NOT use []
- script execution via -e/-c flag
- shell command via -c/-lc flag
```

## When you add a NEW UT profile (or any subordinate profile)

1. Copy the relevant sections of the closest sibling profile (don't write from
   scratch — you'll forget `command_allowlist`).
2. Run the audit script above and confirm the new profile shows up correctly.
3. If you ever bump the global allowlist, re-run the audit because subordinate
   profiles **don't** retro-inherit additions.
