#!/usr/bin/env python3
"""monitor_kanban.py - 监控 Hermes Kanban 任务状态"""

import subprocess, sys, time, argparse, yaml, json
from pathlib import Path

def run_cmd(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

def get_stats(board):
    r = run_cmd(f"hermes kanban stats --board {board}")
    if r.returncode != 0:
        return {"error": r.stderr}
    try:
        return json.loads(r.stdout)
    except:
        stats = {}
        for line in r.stdout.split("\n"):
            if ":" in line:
                k, v = line.split(":")
                stats[k.strip()] = v.strip()
        return stats

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-yaml", required=True)
    parser.add_argument("--poll-interval", type=int, default=60)
    parser.add_argument("--max-wait", type=int, default=3600)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.workflow_yaml).read_text(encoding='utf-8'))
    board = config.get("kanban", {}).get("board", {}).get("slug", "apmm-ut")

    print(f"Monitoring board: {board}")
    start = time.time()

    while time.time() - start < args.max_wait:
        stats = get_stats(board)
        if "error" in stats:
            print(f"ERROR: {stats['error']}")
            sys.exit(1)

        pending = stats.get("pending", 0)
        running = stats.get("running", 0)
        print(f"Stats: done={stats.get('done')}, pending={pending}, running={running}")

        if pending == 0 and running == 0:
            print("All tasks completed")
            result = {"status": "completed", "board": board, "stats": stats}
            print(f"JSON_OUTPUT: {json.dumps(result)}")
            sys.exit(0)

        time.sleep(args.poll_interval)

    print("WARN: Max wait exceeded")
    sys.exit(2)

if __name__ == "__main__":
    main()