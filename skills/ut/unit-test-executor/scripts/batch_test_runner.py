#!/usr/bin/env python3
"""
batch_test_runner.py - Run tests in batches and update manifest

Enhanced version with:
- Background execution (nohup pytest on remote)
- Parallel execution (asyncio, N workers)
- Smart timeout based on HF dependency
- Log parsing and progress monitoring
- Integration with LogManager and IssuesTracker

Usage:
    python batch_test_runner.py --batch-size 10 --start-id 1
    python batch_test_runner.py --parallel 3 --background --phase 1
    python batch_test_runner.py --monitor --batch-id batch_20260605_1030
"""

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
MANIFEST_FILE = SCRIPT_DIR.parent / "test_manifest.json"
TEST_LIST_FILE = SCRIPT_DIR.parent / "ut_test_list.txt"
PROGRESS_FILE = SCRIPT_DIR.parent / "PROGRESS.md"
ISSUES_FILE = SCRIPT_DIR.parent / "issues.json"

REMOTE_CMD_PREFIX = ["python", "agent.py", "-p", "t_h20", "run", "--timeout", "300"]
CONTAINER_PREFIX = "sudo docker exec v0.13.0_torch2.5.1_compile"
VLLM_DIR = "/gpfs/gcsp/M2.7_verify/vllm"
UT_LOGS_DIR = f"{VLLM_DIR}/ut_logs"

# Default timeouts
DEFAULT_TIMEOUT_MODEL_FREE = 120  # seconds
DEFAULT_TIMEOUT_MODEL_DEPENDENT = 300  # seconds (HF tests need more time)
DEFAULT_TIMEOUT_HF_DOWNLOAD = 600  # seconds (if model needs download)

# HF model-dependent test patterns
HF_DEPENDENT_PATTERNS = [
    r"tests/models/",
    r"tests/lora/",
    r"tests/tokenizers_/",
    r"tests/evals/",
    r"test_.*_model",
    r"test_.*_generation",
    r"from transformers import",
    r"from huggingface_hub import",
]

# Import related modules (optional - graceful fallback if not available)
try:
    from log_manager import LogManager, TestLogMetadata, TestLogResult
    HAS_LOG_MANAGER = True
except ImportError:
    logger.warning("log_manager.py not found, using default log paths")
    HAS_LOG_MANAGER = False

try:
    from issues_tracker import IssuesTracker, ErrorCategory
    HAS_ISSUES_TRACKER = True
except ImportError:
    logger.warning("issues_tracker.py not found, skipping error categorization")
    HAS_ISSUES_TRACKER = False


def load_manifest():
    """Load test manifest from JSON file."""
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest):
    """Save test manifest to JSON file."""
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def run_test_on_remote(test_node, test_id, timeout=120):
    """
    Run a single test on remote server and save log.

    Returns: (exit_code, duration_ms, error_type, error_message)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"{UT_LOGS_DIR}/{timestamp}_test_{test_id}.log"

    # Construct pytest command
    pytest_cmd = f"cd {VLLM_DIR} && pytest '{test_node}' -v --tb=short -x 2>&1 | tee {log_file}"
    full_cmd = f"{CONTAINER_PREFIX} bash -c '{pytest_cmd}'"

    # Build remote command
    cmd_parts = REMOTE_CMD_PREFIX.copy()
    cmd_parts.extend([f"sudo docker exec v0.13.0_torch2.5.1_compile bash -c 'cd {VLLM_DIR} && timeout {timeout} pytest \"{test_node}\" -v --tb=short 2>&1 > {log_file}; echo EXIT_CODE:$?'"])

    start_time = datetime.now()

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            cwd=SCRIPT_DIR.parent.parent.parent  # workspace/apmm
        )

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Parse exit code from output
        output = result.stdout + result.stderr
        if "EXIT_CODE:" in output:
            exit_code = int(output.split("EXIT_CODE:")[-1].strip().split()[0])
        else:
            exit_code = result.returncode

        # Determine error type
        error_type = None
        error_message = None

        if exit_code == 0:
            status = "passed"
        elif exit_code == 124:
            status = "timeout"
            error_type = "timeout"
            error_message = f"Test exceeded {timeout}s timeout"
        elif exit_code == 1:
            status = "failed"
            error_type = "assertion"
        else:
            status = "error"
            error_type = "runtime"

        return status, exit_code, duration_ms, error_type, error_message, log_file

    except subprocess.TimeoutExpired:
        return "timeout", 124, timeout * 1000, "timeout", "Local command timeout", log_file
    except Exception as e:
        return "error", -1, 0, "execution", str(e), log_file


def update_manifest_status(manifest, test_id, status, exit_code, duration_ms, error_type, error_message, log_file):
    """Update a single test's status in manifest."""
    for test in manifest["tests"]:
        if test["id"] == test_id:
            test["status"] = status
            test["run_at"] = datetime.now().isoformat()
            test["duration_ms"] = duration_ms
            test["exit_code"] = exit_code
            test["error_type"] = error_type
            test["error_message"] = error_message
            test["log_file"] = log_file
            break

    # Update statistics
    stats = manifest["statistics"]
    stats["pending"] = sum(1 for t in manifest["tests"] if t["status"] == "pending")
    stats["passed"] = sum(1 for t in manifest["tests"] if t["status"] == "passed")
    stats["failed"] = sum(1 for t in manifest["tests"] if t["status"] == "failed")
    stats["error"] = sum(1 for t in manifest["tests"] if t["status"] == "error")
    stats["timeout"] = sum(1 for t in manifest["tests"] if t["status"] == "timeout")


def record_error_in_progress(test_id, test_node, error_type, error_message):
    """Record error in PROGRESS.md."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    error_entry = f"""
### 错误记录 ({timestamp})

| Test ID | 测试节点 | 错误类型 | 错误信息 |
|---------|----------|----------|----------|
| {test_id} | `{test_node}` | {error_type} | {error_message or 'N/A'} |

"""

    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(error_entry)


def run_batch(manifest, start_id, batch_size, timeout=120):
    """Run a batch of tests."""
    tests_to_run = [
        t for t in manifest["tests"]
        if t["id"] >= start_id and t["id"] < start_id + batch_size and t["status"] == "pending"
    ]

    if not tests_to_run:
        print(f"No pending tests in range {start_id}-{start_id + batch_size - 1}")
        return

    print(f"Running batch: tests {tests_to_run[0]['id']} to {tests_to_run[-1]['id']} ({len(tests_to_run)} tests)")

    for test in tests_to_run:
        test_id = test["id"]
        test_node = test["test_node"]

        print(f"  [{test_id}] {test_node[:60]}...")

        status, exit_code, duration_ms, error_type, error_message, log_file = run_test_on_remote(
            test_node, test_id, timeout
        )

        update_manifest_status(
            manifest, test_id, status, exit_code, duration_ms, error_type, error_message, log_file
        )

        # Record errors
        if status != "passed":
            record_error_in_progress(test_id, test_node, error_type, error_message)

        print(f"    -> {status} (exit={exit_code}, duration={duration_ms}ms)")

        # Save manifest after each test
        save_manifest(manifest)

    # Print summary
    stats = manifest["statistics"]
    total = manifest["total_tests"]
    completed = stats["passed"] + stats["failed"] + stats["error"] + stats["timeout"]
    print(f"\nProgress: {completed}/{total} ({completed/total*100:.1f}%)")
    print(f"  Passed: {stats['passed']}, Failed: {stats['failed']}, Error: {stats['error']}, Timeout: {stats['timeout']}")


def main():
    parser = argparse.ArgumentParser(description="Run tests in batches")
    parser.add_argument("--batch-size", "-b", type=int, default=10, help="Number of tests per batch")
    parser.add_argument("--start-id", "-s", type=int, default=1, help="Starting test ID")
    parser.add_argument("--timeout", "-t", type=int, default=120, help="Timeout per test (seconds)")
    parser.add_argument("--max-batches", "-m", type=int, default=1, help="Maximum batches to run")
    args = parser.parse_args()

    manifest = load_manifest()

    for batch_num in range(args.max_batches):
        start_id = args.start_id + (batch_num * args.batch_size)
        run_batch(manifest, start_id, args.batch_size, args.timeout)

        # Check if we've completed all tests
        stats = manifest["statistics"]
        if stats["pending"] == 0:
            print("All tests completed!")
            break


# ============================================================================
# NEW ENHANCED FUNCTIONS - Background/Parallel Execution
# ============================================================================


def detect_hf_dependency(test_node: str) -> bool:
    """
    Check if a test needs HuggingFace model.

    Uses heuristics based on test path patterns and naming conventions.

    Args:
        test_node: Test node identifier (e.g., "tests/models/test_xxx.py::test_yyy")

    Returns:
        True if test likely depends on HF models, False otherwise
    """
    for pattern in HF_DEPENDENT_PATTERNS:
        if re.search(pattern, test_node, re.IGNORECASE):
            return True
    return False


def smart_timeout(test_node: str, has_cached_model: bool = False) -> int:
    """
    Adjust timeout based on test type (model-dependent vs model-free).

    Args:
        test_node: Test node identifier
        has_cached_model: Whether the model is already cached (reduces timeout)

    Returns:
        Timeout in seconds appropriate for the test
    """
    is_hf_dependent = detect_hf_dependency(test_node)

    if not is_hf_dependent:
        return DEFAULT_TIMEOUT_MODEL_FREE

    if has_cached_model:
        return DEFAULT_TIMEOUT_MODEL_DEPENDENT

    # Model not cached - may need download, use longer timeout
    return DEFAULT_TIMEOUT_HF_DOWNLOAD


def get_log_manager():
    """Get LogManager instance, or return None if not available."""
    if HAS_LOG_MANAGER:
        return LogManager(UT_LOGS_DIR)
    return None


def get_issues_tracker():
    """Get IssuesTracker instance, or return None if not available."""
    if HAS_ISSUES_TRACKER:
        return IssuesTracker(ISSUES_FILE)
    return None


def append_to_progress_md(
    event_type: str,
    content: dict,
    progress_file: Path = PROGRESS_FILE
) -> None:
    """
    Append record to PROGRESS.md with timestamp.

    This is append-only mode - does not modify historical records.

    Args:
        event_type: Type of event (e.g., "批次执行", "问题发现", "阶段切换", "断连恢复")
        content: Dictionary with event details
        progress_file: Path to PROGRESS.md file
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build the entry based on event type
    lines = [f"\n### {timestamp} - {event_type}\n"]

    for key, value in content.items():
        if isinstance(value, list):
            lines.append(f"- {key}: {', '.join(map(str, value))}")
        elif isinstance(value, dict):
            lines.append(f"- {key}:")
            for k, v in value.items():
                lines.append(f"  - {k}: {v}")
        else:
            lines.append(f"- {key}: {value}")

    lines.append("")  # Empty line after entry

    # Append to file
    with open(progress_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("Appended %s event to PROGRESS.md", event_type)


def run_tests_background(
    test_nodes: list[str],
    batch_id: str,
    phase: int = 1,
    timeout: int = 120,
    gpu: str = "0-1"
) -> dict:
    """
    Execute pytest via nohup on remote server.

    Background execution that survives local disconnects.

    Args:
        test_nodes: List of test node identifiers to run
        batch_id: Batch identifier (e.g., "batch_20260605_1030")
        phase: Phase number (1, 2, or 3)
        timeout: Timeout per test in seconds
        gpu: GPU assignment (e.g., "0-1")

    Returns:
        Dictionary with batch metadata:
            - batch_id
            - pid (remote process ID)
            - log_file (remote log path)
            - pid_file (remote pid file path)
            - started_at
            - test_count
            - status ("started")
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Determine log directory based on phase
    log_dir = f"{UT_LOGS_DIR}/phase{phase}"
    log_file = f"{log_dir}/{batch_id}.log"
    pid_file = f"{log_dir}/{batch_id}.pid"

    # Build pytest command with nohup
    test_args = " ".join(f'"{node}"' for node in test_nodes)
    pytest_cmd = (
        f"cd {VLLM_DIR} && "
        f"mkdir -p {log_dir} && "
        f"nohup sudo docker exec {CONTAINER_PREFIX.split()[-1]} "
        f"bash -c 'cd {VLLM_DIR} && timeout {timeout} pytest {test_args} -v --tb=short' "
        f"> {log_file} 2>&1 & echo $! > {pid_file}"
    )

    # Build remote command via agent.py
    cmd_parts = REMOTE_CMD_PREFIX.copy()
    cmd_parts.extend([pytest_cmd])

    logger.info("Starting background batch: %s (%d tests)", batch_id, len(test_nodes))
    logger.info("Log file: %s", log_file)

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=30,  # Command timeout (not test timeout)
            cwd=SCRIPT_DIR.parent.parent.parent  # workspace/apmm
        )

        # Parse PID from output
        output = result.stdout + result.stderr
        pid = None

        # Try to extract PID from command output
        for line in output.split('\n'):
            if line.strip().isdigit():
                pid = int(line.strip())
                break

        if pid is None:
            # Fallback: read PID from remote pid file
            pid_cmd = f"cat {pid_file}"
            pid_result = subprocess.run(
                REMOTE_CMD_PREFIX[:-2] + ["run", pid_cmd],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=SCRIPT_DIR.parent.parent.parent.parent
            )
            if pid_result.stdout.strip().isdigit():
                pid = int(pid_result.stdout.strip())

        return {
            "batch_id": batch_id,
            "pid": pid,
            "log_file": log_file,
            "pid_file": pid_file,
            "started_at": datetime.now().isoformat(),
            "test_count": len(test_nodes),
            "test_nodes": test_nodes,
            "phase": phase,
            "gpu": gpu,
            "status": "started"
        }

    except subprocess.TimeoutExpired:
        logger.error("Command timeout while starting background batch")
        return {
            "batch_id": batch_id,
            "pid": None,
            "log_file": log_file,
            "pid_file": pid_file,
            "started_at": datetime.now().isoformat(),
            "test_count": len(test_nodes),
            "status": "error",
            "error": "Command timeout"
        }
    except Exception as e:
        logger.error("Failed to start background batch: %s", e)
        return {
            "batch_id": batch_id,
            "pid": None,
            "log_file": log_file,
            "pid_file": pid_file,
            "started_at": datetime.now().isoformat(),
            "test_count": len(test_nodes),
            "status": "error",
            "error": str(e)
        }


def monitor_batch_progress(
    batch_info: dict,
    poll_interval: int = 10,
    max_checks: int = 60
) -> dict:
    """
    Monitor background batch progress via log growth.

    Polls remote log file to check for progress and completion.

    Args:
        batch_info: Dictionary from run_tests_background() with batch metadata
        poll_interval: Seconds between checks (default: 10s)
        max_checks: Maximum number of checks before declaring timeout (default: 60 = 10min)

    Returns:
        Dictionary with monitoring results:
            - status ("running", "completed", "stalled", "error")
            - completed_tests (count)
            - log_lines (count)
            - pid_alive (bool)
            - results (dict with passed/failed/error counts)
            - last_check_at
    """
    log_file = batch_info.get("log_file")
    pid_file = batch_info.get("pid_file")
    pid = batch_info.get("pid")

    if not log_file:
        return {"status": "error", "error": "No log file specified"}

    logger.info("Monitoring batch: %s", batch_info.get("batch_id"))

    last_log_lines = 0
    last_check_time = datetime.now()
    stall_count = 0

    for check_num in range(max_checks):
        # Check if process is alive
        pid_alive = True
        if pid:
            ps_cmd = f"ps -p {pid}"
            try:
                ps_result = subprocess.run(
                    REMOTE_CMD_PREFIX[:-2] + ["run", ps_cmd],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=SCRIPT_DIR.parent.parent.parent.parent
                )
                # ps returns 0 if process exists, 1 if not
                pid_alive = ps_result.returncode == 0
            except Exception:
                pid_alive = False  # Assume dead on error

        # Get log file stats
        try:
            wc_cmd = f"wc -l {log_file}"
            wc_result = subprocess.run(
                REMOTE_CMD_PREFIX[:-2] + ["run", wc_cmd],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=SCRIPT_DIR.parent.parent.parent.parent
            )
            log_lines = int(wc_result.stdout.strip().split()[0]) if wc_result.stdout.strip() else 0
        except Exception:
            log_lines = 0

        current_check_time = datetime.now()
        logger.debug(
            "Check %d/%d: pid_alive=%s, log_lines=%d (prev=%d)",
            check_num + 1, max_checks, pid_alive, log_lines, last_log_lines
        )

        # Check for completion indicators in log
        if log_lines > 10:  # Need some output to parse
            try:
                tail_cmd = f"tail -n 50 {log_file}"
                tail_result = subprocess.run(
                    REMOTE_CMD_PREFIX[:-2] + ["run", tail_cmd],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=SCRIPT_DIR.parent.parent.parent.parent
                )
                tail_output = tail_result.stdout

                # Check for pytest completion markers
                if re.search(r"passed|failed|error|skipped", tail_output, re.IGNORECASE):
                    # Parse results from tail
                    results = parse_batch_log_tail(tail_output)

                    if results.get("has_summary"):
                        logger.info("Batch completed: %s", results)
                        return {
                            "status": "completed",
                            "completed_tests": results.get("total", 0),
                            "log_lines": log_lines,
                            "pid_alive": pid_alive,
                            "results": results,
                            "last_check_at": current_check_time.isoformat()
                        }
            except Exception as e:
                logger.warning("Failed to parse log tail: %s", e)

        # Check for stall (no progress for 3 consecutive checks)
        if log_lines == last_log_lines and not pid_alive:
            stall_count += 1
            if stall_count >= 3:
                logger.warning("Batch appears stalled (no log growth, process dead)")
                return {
                    "status": "stalled",
                    "completed_tests": 0,
                    "log_lines": log_lines,
                    "pid_alive": pid_alive,
                    "results": {},
                    "last_check_at": current_check_time.isoformat()
                }
        else:
            stall_count = 0

        # If process dead and no completion detected
        if not pid_alive and log_lines > 0:
            # Process finished, parse final results
            try:
                cat_cmd = f"cat {log_file}"
                cat_result = subprocess.run(
                    REMOTE_CMD_PREFIX[:-2] + ["run", cat_cmd],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=SCRIPT_DIR.parent.parent.parent.parent
                )
                results = parse_batch_log(cat_result.stdout)
                return {
                    "status": "completed",
                    "completed_tests": results.get("total", 0),
                    "log_lines": log_lines,
                    "pid_alive": pid_alive,
                    "results": results,
                    "last_check_at": current_check_time.isoformat()
                }
            except Exception as e:
                logger.error("Failed to read final log: %s", e)

        last_log_lines = log_lines
        last_check_time = current_check_time

        # Wait before next check
        import time
        time.sleep(poll_interval)

    # Max checks reached without completion
    logger.warning("Max checks reached, batch still running")
    return {
        "status": "running",
        "completed_tests": 0,
        "log_lines": log_lines,
        "pid_alive": pid_alive,
        "results": {},
        "last_check_at": datetime.now().isoformat()
    }


def parse_batch_log(log_content: str) -> dict:
    """
    Parse batch log to extract test results.

    Parses pytest output to extract PASSED, FAILED, ERROR test results.

    Args:
        log_content: Full pytest output log

    Returns:
        Dictionary with:
            - passed (count)
            - failed (count)
            - error (count)
            - skipped (count)
            - total (count)
            - has_summary (bool)
            - test_results (list of individual test results)
            - errors_by_type (dict)
    """
    results = {
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "total": 0,
        "has_summary": False,
        "test_results": [],
        "errors_by_type": {}
    }

    # Parse individual test results
    # Pattern: "PASSED tests/xxx.py::test_yyy"
    # Pattern: "FAILED tests/xxx.py::test_yyy - AssertionError"
    # Pattern: "ERROR tests/xxx.py::test_yyy - ImportError"

    test_pattern = re.compile(
        r"(PASSED|FAILED|ERROR|SKIPPED)\s+(tests/[^\s:]+(?:\:\:[^\s]+)?)"
        r"(?:\s*[-]\s*(.+))?",
        re.MULTILINE
    )

    for match in test_pattern.finditer(log_content):
        status = match.group(1)
        test_node = match.group(2)
        error_detail = match.group(3) if match.group(3) else None

        results["test_results"].append({
            "status": status,
            "test_node": test_node,
            "error_detail": error_detail
        })

        if status == "PASSED":
            results["passed"] += 1
        elif status == "FAILED":
            results["failed"] += 1
            # Track error type
            if error_detail:
                error_type = categorize_error_type(error_detail)
                results["errors_by_type"][error_type] = \
                    results["errors_by_type"].get(error_type, 0) + 1
        elif status == "ERROR":
            results["error"] += 1
            if error_detail:
                error_type = categorize_error_type(error_detail)
                results["errors_by_type"][error_type] = \
                    results["errors_by_type"].get(error_type, 0) + 1
        elif status == "SKIPPED":
            results["skipped"] += 1

    results["total"] = results["passed"] + results["failed"] + \
                        results["error"] + results["skipped"]

    # Parse summary line
    # Pattern: "X passed, Y failed, Z error, W skipped in T.XXs"
    summary_pattern = re.compile(
        r"(\d+)\s+passed"
        r"(?:\s*,\s*(\d+)\s+failed)?"
        r"(?:\s*,\s*(\d+)\s+error)?"
        r"(?:\s*,\s*(\d+)\s+skipped)?"
        r"(?:\s*,\s*(\d+)\s+warning)?"
        r"\s+in\s+[\d.]+s",
        re.IGNORECASE
    )

    summary_match = summary_pattern.search(log_content)
    if summary_match:
        results["has_summary"] = True
        results["passed"] = int(summary_match.group(1))
        if summary_match.group(2):
            results["failed"] = int(summary_match.group(2))
        if summary_match.group(3):
            results["error"] = int(summary_match.group(3))
        if summary_match.group(4):
            results["skipped"] = int(summary_match.group(4))
        results["total"] = results["passed"] + results["failed"] + \
                            results["error"] + results["skipped"]

    return results


def parse_batch_log_tail(tail_content: str) -> dict:
    """
    Parse last N lines of batch log to detect completion.

    Quick check for pytest summary markers.

    Args:
        tail_content: Last 50 lines of pytest output

    Returns:
        Dictionary with basic completion info
    """
    results = {
        "has_summary": False,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "total": 0
    }

    # Look for summary line
    summary_pattern = re.compile(
        r"(\d+)\s+passed"
        r"(?:\s*,\s*(\d+)\s+failed)?"
        r"(?:\s*,\s*(\d+)\s+error)?"
        r"(?:\s*,\s*(\d+)\s+skipped)?"
        r"(?:\s*,\s*(\d+)\s+warning)?"
        r"\s+in\s+[\d.]+s",
        re.IGNORECASE
    )

    summary_match = summary_pattern.search(tail_content)
    if summary_match:
        results["has_summary"] = True
        results["passed"] = int(summary_match.group(1))
        if summary_match.group(2):
            results["failed"] = int(summary_match.group(2))
        if summary_match.group(3):
            results["error"] = int(summary_match.group(3))
        if summary_match.group(4):
            results["skipped"] = int(summary_match.group(4))
        results["total"] = results["passed"] + results["failed"] + \
                            results["error"] + results["skipped"]

    return results


def categorize_error_type(error_detail: str) -> str:
    """
    Categorize error type for tracking.

    Uses simplified categorization if IssuesTracker not available.

    Args:
        error_detail: Error message or traceback

    Returns:
        Category code (C, E, D, P, M, S)
    """
    if HAS_ISSUES_TRACKER:
        tracker = get_issues_tracker()
        if tracker:
            code, name = tracker.categorize_error(error_detail)
            return code

    # Simplified categorization fallback
    patterns = {
        "M": ["LocalEntryNotFoundError", "config.json", "model not found", "HuggingFace"],
        "D": ["ImportError", "ModuleNotFoundError", "cannot import", "undefined symbol"],
        "P": ["wrap_triton", "torch.compile", "VllmBackend", "CompilationError"],
        "E": ["CUDA out of memory", "OSError", "Network", "timeout", "Connection"],
        "S": ["pytest.skip", "SkipTest", "Skipped", "not supported"],
    }

    for code, keywords in patterns.items():
        for keyword in keywords:
            if keyword.lower() in error_detail.lower():
                return code

    return "C"  # Default to Code Bug


async def run_test_async(
    test_node: str,
    test_id: int,
    worker_id: int,
    timeout: int = 120,
    gpu: str = None
) -> dict:
    """
    Async version of run_test_on_remote for parallel execution.

    Args:
        test_node: Test node identifier
        test_id: Test ID from manifest
        worker_id: Worker ID for parallel tracking
        timeout: Timeout in seconds
        gpu: GPU assignment (optional)

    Returns:
        Dictionary with test result
    """
    logger.info("[Worker %d] Starting test %d: %s", worker_id, test_id, test_node[:60])

    # Use smart timeout
    actual_timeout = smart_timeout(test_node)

    # Run in subprocess (asyncio compatible)
    proc = await asyncio.create_subprocess_exec(
        *REMOTE_CMD_PREFIX,
        f"sudo docker exec {CONTAINER_PREFIX.split()[-1]} bash -c "
        f"'cd {VLLM_DIR} && timeout {actual_timeout} pytest \"{test_node}\" -v --tb=short'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=SCRIPT_DIR.parent.parent.parent.parent
    )

    start_time = datetime.now()

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=actual_timeout + 30
        )

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        output = stdout.decode() + stderr.decode()

        # Parse exit code
        exit_code = proc.returncode

        # Determine status
        if exit_code == 0:
            status = "passed"
            error_type = None
            error_message = None
        elif exit_code == 124:
            status = "timeout"
            error_type = "timeout"
            error_message = f"Test exceeded {actual_timeout}s timeout"
        elif exit_code == 1:
            status = "failed"
            error_type = categorize_error_type(output)
            error_message = extract_error_message(output)
        else:
            status = "error"
            error_type = categorize_error_type(output)
            error_message = extract_error_message(output)

        logger.info(
            "[Worker %d] Test %d: %s (duration=%dms)",
            worker_id, test_id, status, duration_ms
        )

        return {
            "test_id": test_id,
            "test_node": test_node,
            "worker_id": worker_id,
            "status": status,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "error_type": error_type,
            "error_message": error_message
        }

    except asyncio.TimeoutError:
        logger.warning("[Worker %d] Test %d: async timeout", worker_id, test_id)
        return {
            "test_id": test_id,
            "test_node": test_node,
            "worker_id": worker_id,
            "status": "timeout",
            "exit_code": 124,
            "duration_ms": actual_timeout * 1000,
            "error_type": "timeout",
            "error_message": "Async command timeout"
        }
    except Exception as e:
        logger.error("[Worker %d] Test %d: error - %s", worker_id, test_id, e)
        return {
            "test_id": test_id,
            "test_node": test_node,
            "worker_id": worker_id,
            "status": "error",
            "exit_code": -1,
            "duration_ms": 0,
            "error_type": "execution",
            "error_message": str(e)
        }


def extract_error_message(output: str) -> str:
    """Extract key error message from pytest output."""
    # Look for common error patterns
    patterns = [
        r"AssertionError: (.+)",
        r"ImportError: (.+)",
        r"ModuleNotFoundError: (.+)",
        r"RuntimeError: (.+)",
        r"TypeError: (.+)",
        r"ValueError: (.+)",
        r"CUDA out of memory.*",
        r"LocalEntryNotFoundError.*",
    ]

    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(0)[:200]  # Truncate long messages

    return "Unknown error"


async def run_tests_parallel(
    manifest: dict,
    start_id: int,
    batch_size: int,
    num_workers: int = 3,
    timeout: int = 120
) -> list[dict]:
    """
    Asyncio version of run_batch for concurrent execution.

    Runs multiple tests in parallel using asyncio.

    Args:
        manifest: Test manifest dictionary
        start_id: Starting test ID
        batch_size: Number of tests to run
        num_workers: Number of parallel workers (default: 3)
        timeout: Base timeout per test

    Returns:
        List of test result dictionaries
    """
    tests_to_run = [
        t for t in manifest["tests"]
        if t["id"] >= start_id and t["id"] < start_id + batch_size and t["status"] == "pending"
    ]

    if not tests_to_run:
        logger.info("No pending tests in range %d-%d", start_id, start_id + batch_size - 1)
        return []

    logger.info(
        "Running parallel batch: tests %d to %d (%d tests, %d workers)",
        tests_to_run[0]["id"], tests_to_run[-1]["id"], len(tests_to_run), num_workers
    )

    # Create semaphore to limit concurrent workers
    semaphore = asyncio.Semaphore(num_workers)

    async def run_with_semaphore(test, worker_id):
        async with semaphore:
            return await run_test_async(
                test["test_node"],
                test["id"],
                worker_id,
                timeout=smart_timeout(test["test_node"])
            )

    # Create tasks for all tests
    tasks = [
        run_with_semaphore(test, (test["id"] - start_id) % num_workers)
        for test in tests_to_run
    ]

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append({
                "test_id": tests_to_run[i]["id"],
                "test_node": tests_to_run[i]["test_node"],
                "status": "error",
                "error_message": str(result)
            })
        else:
            processed_results.append(result)

    # Update manifest
    for result in processed_results:
        update_manifest_status(
            manifest,
            result["test_id"],
            result["status"],
            result.get("exit_code", -1),
            result.get("duration_ms", 0),
            result.get("error_type"),
            result.get("error_message"),
            None
        )

    # Save manifest
    save_manifest(manifest)

    # Log summary
    passed = sum(1 for r in processed_results if r["status"] == "passed")
    failed = sum(1 for r in processed_results if r["status"] == "failed")
    error = sum(1 for r in processed_results if r["status"] == "error")
    timeout_count = sum(1 for r in processed_results if r["status"] == "timeout")

    logger.info(
        "Parallel batch complete: passed=%d, failed=%d, error=%d, timeout=%d",
        passed, failed, error, timeout_count
    )

    # Append to PROGRESS.md
    append_to_progress_md("批次执行", {
        "测试范围": f"#{start_id}-#{start_id + batch_size - 1}",
        "测试数": len(tests_to_run),
        "并行worker": num_workers,
        "结果": {
            "passed": passed,
            "failed": failed,
            "error": error,
            "timeout": timeout_count
        }
    })

    return processed_results


def run_batch_parallel(
    manifest: dict,
    start_id: int,
    batch_size: int,
    num_workers: int = 3,
    timeout: int = 120
) -> list[dict]:
    """
    Synchronous wrapper for run_tests_parallel.

    Args:
        manifest: Test manifest dictionary
        start_id: Starting test ID
        batch_size: Number of tests to run
        num_workers: Number of parallel workers
        timeout: Timeout per test

    Returns:
        List of test result dictionaries
    """
    return asyncio.run(
        run_tests_parallel(manifest, start_id, batch_size, num_workers, timeout)
    )


def main_enhanced():
    """
    Enhanced CLI with parallel and background execution options.
    """
    parser = argparse.ArgumentParser(
        description="Enhanced batch test runner with parallel/background execution"
    )

    # Basic options (from original)
    parser.add_argument("--batch-size", "-b", type=int, default=10,
                        help="Number of tests per batch")
    parser.add_argument("--start-id", "-s", type=int, default=1,
                        help="Starting test ID")
    parser.add_argument("--timeout", "-t", type=int, default=120,
                        help="Timeout per test (seconds)")
    parser.add_argument("--max-batches", "-m", type=int, default=1,
                        help="Maximum batches to run")

    # Enhanced options
    parser.add_argument("--parallel", "-p", type=int, default=1,
                        help="Number of parallel workers (default: 1, use 3 for parallel)")
    parser.add_argument("--background", "-B", action="store_true",
                        help="Run tests in background mode (nohup on remote)")
    parser.add_argument("--phase", type=int, default=1,
                        help="Phase number (1, 2, or 3)")
    parser.add_argument("--gpu", type=str, default="0-1",
                        help="GPU assignment (e.g., '0-1')")
    parser.add_argument("--monitor", "-M", action="store_true",
                        help="Monitor existing background batch")
    parser.add_argument("--batch-id", type=str,
                        help="Batch ID to monitor (e.g., batch_20260605_1030)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would run, don't execute")

    args = parser.parse_args()

    # Load manifest
    manifest = load_manifest()

    if args.dry_run:
        tests_to_run = [
            t for t in manifest["tests"]
            if t["id"] >= args.start_id and
               t["id"] < args.start_id + args.batch_size and
               t["status"] == "pending"
        ]
        print(f"\n[DRY RUN] Would run {len(tests_to_run)} tests:")
        for test in tests_to_run[:10]:  # Show first 10
            hf_dep = detect_hf_dependency(test["test_node"])
            timeout_val = smart_timeout(test["test_node"])
            print(f"  ID {test['id']}: {test['test_node'][:60]}")
            print(f"    HF-dependent: {hf_dep}, timeout: {timeout_val}s")
        if len(tests_to_run) > 10:
            print(f"  ... and {len(tests_to_run) - 10} more")
        return

    if args.monitor:
        if not args.batch_id:
            print("Error: --batch-id required for monitor mode")
            return

        # Monitor existing batch
        batch_info = {
            "batch_id": args.batch_id,
            "log_file": f"{UT_LOGS_DIR}/phase{args.phase}/{args.batch_id}.log",
            "pid_file": f"{UT_LOGS_DIR}/phase{args.phase}/{args.batch_id}.pid",
        }

        print(f"Monitoring batch: {args.batch_id}")
        result = monitor_batch_progress(batch_info)
        print(f"\nMonitoring result:")
        print(f"  Status: {result['status']}")
        print(f"  Log lines: {result['log_lines']}")
        if result['results']:
            print(f"  Results: {result['results']}")
        return

    if args.background:
        # Background execution mode
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        batch_id = f"batch_{timestamp}"

        tests_to_run = [
            t for t in manifest["tests"]
            if t["id"] >= args.start_id and
               t["id"] < args.start_id + args.batch_size and
               t["status"] == "pending"
        ]

        if not tests_to_run:
            print(f"No pending tests in range {args.start_id}-{args.start_id + args.batch_size - 1}")
            return

        test_nodes = [t["test_node"] for t in tests_to_run]

        print(f"Starting background batch: {batch_id}")
        print(f"  Tests: {len(test_nodes)}")
        print(f"  Range: #{tests_to_run[0]['id']} to #{tests_to_run[-1]['id']}")
        print(f"  Phase: {args.phase}")
        print(f"  GPU: {args.gpu}")

        batch_info = run_tests_background(
            test_nodes,
            batch_id,
            phase=args.phase,
            timeout=args.timeout,
            gpu=args.gpu
        )

        print(f"\nBackground batch started:")
        print(f"  Batch ID: {batch_info['batch_id']}")
        print(f"  PID: {batch_info['pid']}")
        print(f"  Log: {batch_info['log_file']}")
        print(f"  Status: {batch_info['status']}")

        if batch_info['status'] == 'started':
            append_to_progress_md("后台批次启动", {
                "batch_id": batch_id,
                "测试数": len(test_nodes),
                "测试范围": f"#{tests_to_run[0]['id']}-#{tests_to_run[-1]['id']}",
                "PID": batch_info['pid'],
                "日志": batch_info['log_file']
            })

        return

    # Normal or parallel execution
    if args.parallel > 1:
        print(f"Running parallel batches with {args.parallel} workers")
        for batch_num in range(args.max_batches):
            start_id = args.start_id + (batch_num * args.batch_size)
            run_batch_parallel(
                manifest, start_id, args.batch_size,
                args.parallel, args.timeout
            )

            # Check if all tests completed
            stats = manifest["statistics"]
            if stats["pending"] == 0:
                print("All tests completed!")
                break
    else:
        # Sequential execution (original behavior)
        for batch_num in range(args.max_batches):
            start_id = args.start_id + (batch_num * args.batch_size)
            run_batch(manifest, start_id, args.batch_size, args.timeout)

            stats = manifest["statistics"]
            if stats["pending"] == 0:
                print("All tests completed!")
                break


if __name__ == "__main__":
    # Use enhanced CLI if new flags detected, otherwise use original
    if any(arg in sys.argv for arg in ["--parallel", "--background", "--monitor", "--dry-run", "--phase"]):
        main_enhanced()
    else:
        main()