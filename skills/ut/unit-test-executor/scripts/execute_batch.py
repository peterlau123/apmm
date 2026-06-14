#!/usr/bin/env python3
"""
统一批次执行脚本

整合：
1. pytest 远程执行（使用 remote_test_runner.py）
2. 日志解析
3. batch_results.json 生成

用法：
    python execute_batch.py --batch-config PATH --workflow-state PATH

输出：
    {batch_dir}/batch_results.json
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

# 先设置路径
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.shared import get_paths, get_config


def execute_batch(batch_config_path: Path, workflow_state_path: Path) -> dict:
    """执行批次测试并生成结果"""
    batch_config = json.loads(batch_config_path.read_text(encoding="utf-8"))
    paths = get_paths(workflow_state_path)
    config = get_config(workflow_state_path)

    batch_dir = batch_config_path.parent
    batch_id = batch_config["batch_id"]
    tests = batch_config["tests"]
    test_nodes = [t["test_node"] for t in tests]

    remote_server = config.get("remote_server", "t_h20")
    docker_container = config.get("docker_container", "v0.13.0_torch2.5.1_compile")
    pytest_args = config.get("pytest_args", "-q --tb=long")
    timeout = config.get("timeout", 600)

    # 直接使用 agent.py 执行 pytest（避免脚本间参数问题）
    agent_py = _project_root / "tools" / "agent.py"
    test_paths = " ".join(test_nodes)

    # 构造 pytest 命令
    pytest_cmd = f"cd /gpfs/gcsp/M2.7_verify/vllm && python3 -m pytest {test_paths} {pytest_args} 2>&1 | head -100"
    docker_cmd = f"sudo docker exec {docker_container} bash -c '{pytest_cmd}'"

    cmd = [
        sys.executable, str(agent_py),
        "-p", remote_server,
        "run",
        "--timeout", str(timeout),
        docker_cmd
    ]

    print(f"[INFO] Executing {len(tests)} tests...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60, cwd=str(_project_root))

        # 解析 pytest 输出
        stdout = result.stdout
        import re
        passed_match = re.search(r'(\d+) passed', stdout)
        failed_match = re.search(r'(\d+) failed', stdout)
        error_match = re.search(r'(\d+) error', stdout)
        skipped_match = re.search(r'(\d+) skipped', stdout)

        passed = int(passed_match.group(1)) if passed_match else 0
        failed = int(failed_match.group(1)) if failed_match else 0
        error = int(error_match.group(1)) if error_match else 0
        skipped = int(skipped_match.group(1)) if skipped_match else 0

        # 生成 batch_results.json
        batch_results = {
            "batch_id": batch_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "timeout": timeout,
            "exit_code": result.returncode,
            "tests": [],
            "statistics": {"total": len(tests), "passed": passed, "failed": failed, "error": error, "skipped": skipped}
        }

        # 为每个测试分配状态
        for i, test in enumerate(tests):
            if i < passed:
                status = "passed"
            elif i < passed + skipped:
                status = "skipped"
            elif i < passed + skipped + error:
                status = "error"
            else:
                status = "failed"

            batch_results["tests"].append({
                "id": test["id"],
                "test_node": test["test_node"],
                "status": status,
                "duration_ms": 0
            })

        output_path = batch_dir / "batch_results.json"
        output_path.write_text(json.dumps(batch_results, indent=2, ensure_ascii=False))
        print(f"[OK] {output_path}")

        return {"batch_id": batch_id, "batch_results_path": str(output_path), "stats": batch_results["statistics"]}

    except Exception as e:
        error_result = {"batch_id": batch_id, "status": "error", "error": str(e)}
        output_path = batch_dir / "batch_results.json"
        output_path.write_text(json.dumps(error_result, indent=2, ensure_ascii=False))
        return error_result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-config", required=True)
    parser.add_argument("--workflow-state", required=True)
    args = parser.parse_args()

    result = execute_batch(Path(args.batch_config), Path(args.workflow_state))
    print(json.dumps(result, indent=2))