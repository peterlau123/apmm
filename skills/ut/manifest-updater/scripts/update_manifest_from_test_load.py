#!/usr/bin/env python3
"""update manifest from test_load once post-loop."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _calc_stats(tests):
    """Statistics inlined (manifest-updater has hyphen, avoid dotted import)."""
    stats = {"pending": 0, "passed": 0, "failed": 0, "error": 0,
             "ignored": 0, "retriable_error": 0, "fixed_pending_verify": 0, "total": len(tests)}
    for test in tests:
        s = test.get("status", "pending")
        if s in stats:
            stats[s] += 1
    stats["executed"] = sum(stats[k] for k in ("passed", "failed", "error", "retriable_error", "fixed_pending_verify"))
    stats["progress"] = round(stats["executed"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
    return stats


calculate_statistics = _calc_stats


def update_manifest_from_test_load(manifest_path: Path, test_load_path: Path):
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        msg = "Invalid JSON in manifest: " + str(manifest_path) + " " + str(e)
        raise ValueError(msg)

    manifest_tests = {t["test_node"]: t for t in manifest["tests"]}

    try:
        test_load = json.loads(test_load_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        msg = "Invalid JSON in test_load: " + str(test_load_path) + " " + str(e)
        raise ValueError(msg)

    pending_count = test_load.get("statistics", {}).get("pending", 0)
    if pending_count > 0:
        raise ValueError("test_load incomplete: %d pending" % pending_count)

    print("[INFO] Syncing test_load -> manifest")
    updated_count = 0
    for tl_test in test_load["tests"]:
        tn = tl_test["test_node"]
        if tn in manifest_tests:
            mt = manifest_tests[tn]
            mt["status"] = tl_test.get("status", "pending")
            for field in ("retry_count", "ignore_reason", "error_type", "error_message",
                          "last_batch_id", "commit", "errors", "failures",
                          "duration_ms", "exit_code", "log_file", "run_at"):
                if field in tl_test:
                    mt[field] = tl_test[field]
            if "batch_id" in tl_test:
                mt.setdefault("batch_history", []).append({
                    "batch_id": tl_test["batch_id"],
                    "status": tl_test["status"],
                    "executed_at": tl_test.get("executed_at", datetime.now().isoformat()),
                })
            updated_count += 1

    manifest["statistics"] = _calc_stats(manifest["tests"])
    manifest["generated_at"] = datetime.now().isoformat()
    manifest["test_load_source"] = str(test_load_path)

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[OK] Manifest updated: %d tests" % updated_count)
    print("     Statistics: %s" % manifest["statistics"])


def main():
    parser = argparse.ArgumentParser(description="Sync test_load -> manifest")
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--test-load-path", required=True)
    args = parser.parse_args()
    update_manifest_from_test_load(Path(args.manifest_path), Path(args.test_load_path))


if __name__ == "__main__":
    main()
