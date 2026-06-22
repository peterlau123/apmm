# Incident archival in the apmm repo

When something goes wrong during a UT workflow run and the fix is non-trivial,
the user expects a **post-mortem document** + **导向性链接** (navigation pointers)
from every reasonable entry point. Stub docs without cross-links are not
acceptable — the user explicitly required this ("得有导向性链接指向它").

## Where the post-mortem lives

```
D:/workspace/apmm/docs/incidents/
├── README.md                          ← index, reverse-chronological
└── YYYY-MM-DD-<class-level-slug>.md   ← one file per incident
```

Slug format: `YYYY-MM-DD-<short kebab-case noun phrase>`, e.g.
`2026-06-22-l4-fabrication.md`. Don't use run IDs as the slug (incidents
generalise; runs don't).

## Required sections in the post-mortem

1. **Header**: incident ID, run ID, timestamp range, severity, status.
2. **任务背景** — what was being attempted.
3. **实际发生（事实链）** — timestamped events.
4. **根因分析** — separate触发因素 (T1…Tn, contributing) from真正的根因.
5. **证据链** — table of `命令 / 文件 → 结果`, machine-verifiable.
6. **修复动作** — step labels (A, B, C…), each with verification command.
7. **防回归措施** — table mapping each lesson to its permanent location (SKILL §, config file, memory entry).
8. **关键教训** — 3–5 generalisable lessons, NOT incident-specific.
9. **相关链接** — back-links to物证 dir, every SKILL that absorbed a lesson, and the incidents index.

## Required navigation cross-links (DO NOT SKIP — user has rebuked me for this)

When archiving a new incident, patch FOUR files in addition to creating the
post-mortem:

| File | What to add | Why |
|---|---|---|
| `docs/incidents/README.md` | New row in the 索引 table (newest at top) | The incident index itself |
| `docs/README.md` | Update the "事故复盘 Incidents" section's table | Project-level random-access entry |
| `tasks/ut/README.md` | The "我想... \| 看这里" table must point at `../../docs/incidents/README.md` (already wired as of 2026-06-22; verify still present) | UT task's唯一随机访问入口 — user reads this first |
| `runs/<run_id>/INVALID.md` (or whatever artefact marks the failed run) | "Full Post-mortem" section linking back to `docs/incidents/<slug>.md` | Anyone pulling up the run dir gets to the analysis |

If the incident touches the troubleshooting guide's subject matter, also drop
a one-line pointer at the top of `docs/guides/troubleshooting.md`.

## Verification step (do this LAST)

```bash
for f in tasks/ut/README.md docs/README.md docs/guides/troubleshooting.md \
         runs/<run_id>/INVALID.md; do
  echo "--- $f ---"
  grep -nE "incident|事故|复盘|Post-mortem" /d/workspace/apmm/$f | head -3
done
```

Every file should show a hit. If any is empty, the navigation is broken — fix
it before declaring archival complete.

## Reverse-direction check

The post-mortem's §相关链接 must back-link to every file that absorbed a
lesson (SKILLs, configs, memory targets, the INVALID.md). Run a sanity ls on
each link target to confirm it exists.

## Naming pitfalls

- Don't put the run ID in the slug. Slugs name the **class of failure**
  (`l4-fabrication`, `bastion-otp-loop`, `gateway-config-overlay`) so future
  similar incidents land in the same conceptual neighbourhood.
- Don't title sections by tool. "ut-fixer 越权" is okay inside the body, but
  the post-mortem name should describe the failure class, not the actor.
- Don't omit §防回归措施. Without it, the post-mortem is a narrative, not a fix.
