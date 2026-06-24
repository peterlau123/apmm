#!/usr/bin/env python3
"""completion_watcher.py — P3: send single "✅ Run finished" Feishu card.

Design (per 2026-06-23 fabricated-run postmortem P3):
  - Read .agents/current_run.json to locate the active run's
    workflow_state.json.
  - Inspect workflow.status. If in TERMINAL_STATES {completed, stopped,
    failed}, send ONE Feishu card summarising the run, then write a
    marker file so a re-fire is idempotent.
  - On any error (missing config, daemon unreachable), print and exit 0
    — never block; this is purely an out-of-band notifier.

The cron that calls this script should be session-only (in-memory) and
self-deleting on first successful notification, but we ALSO use a
marker file so a same-second double-fire is harmless.

Usage:
  python tasks/ut/scripts/completion_watcher.py [--current-run PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TERMINAL_STATES = {"completed", "stopped", "failed"}


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_card(run_dir: str, state: dict) -> dict:
    """Build the simplified ``card_data`` that ``FeishuAPI.send_card`` expects:
    ``{"header": {"title", "template"}, "content": "<lark_md>"}``.
    The FeishuAPI wrapper adds the full ``config / elements / note`` skeleton
    around this on send.
    """
    wf = (state or {}).get("workflow") or {}
    stats = (state or {}).get("stats") or {}
    status = wf.get("status", "unknown")
    iteration = (state or {}).get("iteration", 0)

    emoji = {"completed": "✅", "stopped": "⏹️", "failed": "❌"}.get(status, "ℹ️")
    title = f"{emoji} UT Run {status.upper()}"

    fields = [
        ("Run dir", run_dir),
        ("Status", status),
        ("Iterations", str(iteration)),
        ("Passed", str(stats.get("passed", "?"))),
        ("Failed", str(stats.get("failed", "?"))),
        ("Error", str(stats.get("error", "?"))),
        ("Pending", str(stats.get("pending", "?"))),
        ("Sent at", _utc_now_z()),
    ]
    md_body = "\n".join(f"**{k}**: {v}" for k, v in fields)
    template = {"completed": "green", "stopped": "grey",
                "failed": "red"}.get(status, "blue")

    return {
        "header": {"title": title, "template": template},
        "content": md_body,
    }


def _send_card(card: dict) -> tuple[bool, str]:
    """Send via FeishuAPI. Returns (ok, message)."""
    cfg = REPO_ROOT / ".agents" / "feishu_config.json"
    if not cfg.exists():
        return False, f"feishu config not found: {cfg}"
    try:
        from skills.ut.workflow.scripts.feishu_api import FeishuAPI
    except Exception as e:  # pragma: no cover
        return False, f"import FeishuAPI failed: {e}"
    try:
        api = FeishuAPI(str(cfg))
        resp = api.send_card(card)
        ok = bool(resp) and (resp.get("code") == 0 if isinstance(resp, dict) else True)
        return ok, json.dumps(resp, ensure_ascii=False) if not ok else "ok"
    except Exception as e:  # pragma: no cover
        return False, f"send_card raised: {e}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-run",
                        default=str(REPO_ROOT / ".agents" / "current_run.json"))
    parser.add_argument("--force", action="store_true",
                        help="Resend even if marker exists (for testing)")
    args = parser.parse_args()

    current_run_path = Path(args.current_run)
    current_run = _read_json(current_run_path)
    if not current_run:
        print(f"[watch] no current_run.json or unreadable: {current_run_path}")
        return

    run_dir = current_run.get("run_dir")
    state_path = current_run.get("workflow_state_path")
    if not run_dir or not state_path:
        print("[watch] current_run.json missing run_dir / workflow_state_path")
        return

    state = _read_json(Path(state_path))
    if state is None:
        print(f"[watch] workflow_state.json unreadable: {state_path}")
        return

    status = ((state.get("workflow") or {}).get("status") or "").lower()
    if status not in TERMINAL_STATES:
        print(f"[watch] status={status!r} not terminal; skipping")
        return

    # Marker idempotency is keyed on (run_dir, started_at) — NOT just the
    # marker file's existence. Reusing a run_dir for a fresh run (manual
    # recovery: operator deletes current_run.json and reuses the directory)
    # would otherwise be silently swallowed by a stale marker from the
    # previous run. The marker content holds the started_at it witnessed;
    # if current_run.started_at differs we know we're a new run and re-fire.
    marker = Path(run_dir) / ".completion_card_sent"
    current_started_at = current_run.get("started_at") or ""
    if marker.exists() and not args.force:
        try:
            prev = marker.read_text(encoding="utf-8").strip()
        except OSError:
            prev = ""
        # Legacy markers (no `started_at:` prefix) are also short-circuited so
        # the migration is loss-less for runs already notified.
        if (
            not current_started_at
            or "started_at:" not in prev
            or prev.endswith(f"started_at:{current_started_at}")
        ):
            print(f"[watch] already notified (marker exists): {marker}")
            return

    card = _build_card(run_dir, state)
    ok, info = _send_card(card)
    if ok:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                f"sent_at:{_utc_now_z()} started_at:{current_started_at}",
                encoding="utf-8",
            )
        except OSError:
            pass
        # ASCII-only print: Windows GBK terminals choke on the ✅ glyph.
        print(f"[watch] OK completion card sent ({status}); marker={marker}")
    else:
        print(f"[watch] send failed: {info}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)  # never block — out-of-band notifier
