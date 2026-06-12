#!/usr/bin/env python3
"""
progress_tracker.py - Track test execution progress from manifest

Enhanced with:
- append_to_progress_md() - Append records with timestamp (不覆盖历史)
- update_overview_table() - Update only top overview table section
- generate_summary_section() - Add summary section to PROGRESS.md
- sync_from_remote() - Download manifest from remote via SSH channel
- merge_progress() - Merge local + remote progress
- detect_stalled_tests() - Alert if tests running > 10 minutes
- update_issues_json() - Track issues from test failures

Usage:
    python progress_tracker.py --manifest test_manifest.json
    python progress_tracker.py --append-progress "batch execution" --log-file "xxx"
    python progress_tracker.py --sync-remote
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union

# Import related modules
try:
    from issues_tracker import IssuesTracker, ErrorCategory
except ImportError:
    SCRIPT_DIR = Path(__file__).parent
    sys.path.insert(0, str(SCRIPT_DIR))
    from issues_tracker import IssuesTracker, ErrorCategory

# StateManager is in the ut directory (parent of scripts)
try:
    from state_manager import StateManager
except ImportError:
    UT_DIR = Path(__file__).parent.parent
    sys.path.insert(0, str(UT_DIR))
    from state_manager import StateManager


def show_progress(manifest_file: str):
    """Show progress statistics from manifest."""

    if not os.path.exists(manifest_file):
        raise FileNotFoundError(f"Manifest file not found: {manifest_file}")

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    stats = manifest["statistics"]
    total = manifest["total_tests"]

    # Calculate percentages
    completed = stats["passed"] + stats["failed"] + stats["error"] + stats["timeout"] + stats["skipped"]
    pending = stats["pending"]
    completion_rate = (completed / total) * 100 if total > 0 else 0

    print("=" * 60)
    print("TEST EXECUTION PROGRESS")
    print("=" * 60)
    print(f"Generated at: {manifest['generated_at']}")
    print(f"Total tests:   {total}")
    print()
    print("Status breakdown:")
    print(f"  [OK]  Passed:    {stats['passed']:>6} ({stats['passed']/total*100:>5.1f}%)")
    print(f"  [FAIL] Failed:    {stats['failed']:>6} ({stats['failed']/total*100:>5.1f}%)")
    print(f"  [ERR]  Error:     {stats['error']:>6} ({stats['error']/total*100:>5.1f}%)")
    print(f"  [TIME] Timeout:   {stats['timeout']:>6} ({stats['timeout']/total*100:>5.1f}%)")
    print(f"  [SKIP] Skipped:   {stats['skipped']:>6} ({stats['skipped']/total*100:>5.1f}%)")
    print(f"  [PEND] Pending:   {pending:>6} ({pending/total*100:>5.1f}%)")
    print()
    print(f"Completion: {completed}/{total} ({completion_rate:.1f}%)")
    print("=" * 60)

    # Group by test file
    tests = manifest["tests"]
    file_stats = defaultdict(lambda: {"pending": 0, "passed": 0, "failed": 0, "error": 0})
    for t in tests:
        file_stats[t["test_file"]][t["status"]] += 1

    # Show top 20 files by pending count
    pending_files = sorted(file_stats.items(), key=lambda x: -x[1]["pending"])[:20]
    if pending_files and pending_files[0][1]["pending"] > 0:
        print()
        print("Top 20 files with pending tests:")
        for file_path, fstats in pending_files:
            print(f"  {fstats['pending']:>4} pending | {file_path}")

    return manifest


def generate_report(manifest_file: str, output_dir: str):
    """Generate markdown progress report."""

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    stats = manifest["statistics"]
    total = manifest["total_tests"]
    completed = stats["passed"] + stats["failed"] + stats["error"] + stats["timeout"] + stats["skipped"]

    report = f"""# Unit Test Progress Report

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Source:** {manifest['source_file']}
**Total Tests:** {total}

## Statistics

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Passed | {stats['passed']} | {stats['passed']/total*100:.1f}% |
| ❌ Failed | {stats['failed']} | {stats['failed']/total*100:.1f}% |
| ⚠️ Error | {stats['error']} | {stats['error']/total*100:.1f}% |
| ⏱️ Timeout | {stats['timeout']} | {stats['timeout']/total*100:.1f}% |
| ⏭️ Skipped | {stats['skipped']} | {stats['skipped']/total*100:.1f}% |
| ⏳ Pending | {stats['pending']} | {stats['pending']/total*100:.1f}% |

## Completion Rate

**{completed}/{total} ({completed/total*100:.1f}%)**

## Error Analysis

### Failed Tests
{stats['failed']} tests failed with assertion errors.

### Error Tests
{stats['error']} tests encountered runtime errors.

### Timeout Tests
{stats['timeout']} tests exceeded time limit.
"""

    report_path = os.path.join(output_dir, "progress_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report generated: {report_path}")


# ── NEW: PROGRESS.md Append Mode ────────────────────────────────────────────────────────

OVERVIEW_TABLE_START = "## 当前状态概览"
OVERVIEW_TABLE_END = "---"

# Section markers for update strategy
SECTION_MARKERS = {
    "overview_start": "## 当前状态概览",
    "overview_end": "---",
    "history_start": "## 历史测试执行报告",
}


def get_progress_md_path(manifest_file: str) -> Path:
    """
    Get PROGRESS.md path from manifest file location.

    Args:
        manifest_file: Path to test_manifest.json

    Returns:
        Path to PROGRESS.md (same directory as manifest)
    """
    manifest_path = Path(manifest_file)
    return manifest_path.parent / "PROGRESS.md"


def append_to_progress_md(
    progress_file: Union[str, Path],
    record_type: str,
    content: dict,
    timestamp: Optional[str] = None
) -> bool:
    """
    Append new record with timestamp (不覆盖历史).

    Supported record types:
        - "batch_execution": 批次执行记录
        - "issue_discovery": 发现新问题
        - "phase_switch": 阶段切换
        - "disconnect_recovery": 断连恢复

    Args:
        progress_file: Path to PROGRESS.md
        record_type: Type of record to append
        content: Dict with record details
        timestamp: Optional timestamp (default: now)

    Returns:
        True if appended successfully
    """
    progress_path = Path(progress_file)
    if not progress_path.exists():
        print(f"Warning: PROGRESS.md not found: {progress_path}")
        return False

    timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Format record based on type
    record_lines = format_progress_record(record_type, content, timestamp)

    # Append to file (追加模式)
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(record_lines) + "\n")

    print(f"[+] Appended {record_type} record to {progress_path}")
    return True


def format_progress_record(record_type: str, content: dict, timestamp: str) -> list[str]:
    """
    Format a progress record for PROGRESS.md.

    Args:
        record_type: Type of record
        content: Dict with record details
        timestamp: Record timestamp

    Returns:
        List of formatted lines
    """
    lines = [f"### {timestamp} - {RECORD_TYPE_LABELS.get(record_type, record_type)}"]

    if record_type == "batch_execution":
        test_range = content.get("test_range", "N/A")
        batch_size = content.get("batch_size", 0)
        passed = content.get("passed", 0)
        failed = content.get("failed", 0)
        error = content.get("error", 0)
        duration = content.get("duration", "N/A")
        log_file = content.get("log_file", "N/A")

        lines.extend([
            f"- 执行测试: {test_range} (batch_size={batch_size})",
            f"- 结果: {passed} passed, {failed} failed, {error} error",
            f"- 耗时: {duration}",
            f"- 日志: {log_file}",
        ])

    elif record_type == "issue_discovery":
        issue_type = content.get("issue_type", "Unknown")
        affected_test = content.get("affected_test", "N/A")
        error_info = content.get("error_info", "N/A")

        lines.extend([
            f"- 问题类型: {issue_type}",
            f"- 影响测试: {affected_test}",
            f"- 错误信息: {error_info[:100]}...",
            f"- 已添加到 issues.json",
        ])

    elif record_type == "phase_switch":
        from_phase = content.get("from_phase", 1)
        to_phase = content.get("to_phase", 2)
        completed_tests = content.get("completed_tests", 0)
        remaining_tests = content.get("remaining_tests", 0)

        lines.extend([
            f"- Phase {from_phase} 完成: {completed_tests} tests executed",
            f"- 开始 Phase {to_phase}: {remaining_tests} remaining tests",
            f"- manifest 已生成: {content.get('manifest', 'N/A')}",
        ])

    elif record_type == "disconnect_recovery":
        disconnect_time = content.get("disconnect_time", "N/A")
        recovery_time = content.get("recovery_time", timestamp)
        remote_completed = content.get("remote_completed", 0)

        lines.extend([
            f"- 本地断连时间: {disconnect_time}",
            f"- 恢复时间: {recovery_time}",
            f"- 远程测试状态: 已完成 {remote_completed} tests (后台运行)",
            f"- 正在同步进度...",
        ])

    else:
        # Generic record
        for key, value in content.items():
            lines.append(f"- {key}: {value}")

    lines.append("")  # Empty line after record
    return lines


RECORD_TYPE_LABELS = {
    "batch_execution": "批次执行",
    "issue_discovery": "发现新问题",
    "phase_switch": "阶段切换",
    "disconnect_recovery": "断连恢复",
}


def update_overview_table(
    progress_file: Union[str, Path],
    manifest_file: Union[str, Path],
    update_date: Optional[str] = None
) -> bool:
    """
    Update only top overview table section (不修改历史).

    Reads manifest statistics and updates the overview table at the top.
    Preserves all historical records below.

    Args:
        progress_file: Path to PROGRESS.md
        manifest_file: Path to test_manifest.json
        update_date: Optional date string (default: today)

    Returns:
        True if updated successfully
    """
    progress_path = Path(progress_file)
    manifest_path = Path(manifest_file)

    if not progress_path.exists():
        print(f"Warning: PROGRESS.md not found: {progress_path}")
        return False

    if not manifest_path.exists():
        print(f"Warning: Manifest not found: {manifest_path}")
        return False

    update_date = update_date or datetime.now().strftime("%Y-%m-%d")

    # Load manifest statistics
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    stats = manifest.get("statistics", {})
    total = manifest.get("total_tests", 0)

    # Read existing PROGRESS.md
    with open(progress_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find overview section start
    overview_start_idx = content.find(OVERVIEW_TABLE_START)
    if overview_start_idx == -1:
        print("Warning: Overview section not found in PROGRESS.md")
        return False

    # Find the end of overview section using multiple strategies:
    # 1. Find the next "##" section header after overview
    # 2. Or find the second "---" after overview (one is in table, one ends section)
    overview_end_search_start = overview_start_idx + len(OVERVIEW_TABLE_START)

    # Strategy 1: Find next section header
    next_section_idx = content.find("\n## ", overview_end_search_start)

    # Strategy 2: Find second "---" delimiter
    first_delimiter_idx = content.find("\n---", overview_end_search_start)
    second_delimiter_idx = content.find("\n---", first_delimiter_idx + 4) if first_delimiter_idx != -1 else -1

    # Use the earliest valid end marker
    if next_section_idx != -1:
        overview_end_idx = next_section_idx
    elif second_delimiter_idx != -1:
        overview_end_idx = second_delimiter_idx
    elif first_delimiter_idx != -1:
        # Only one delimiter found, use it
        overview_end_idx = first_delimiter_idx
    else:
        overview_end_idx = len(content)

    # Generate new overview table
    new_overview = generate_overview_table(stats, total, update_date)

    # Replace overview section
    new_content = content[:overview_start_idx] + new_overview + content[overview_end_idx:]

    # Write back
    with open(progress_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[+] Updated overview table in {progress_path}")
    return True


def generate_overview_table(stats: dict, total: int, update_date: str) -> str:
    """
    Generate overview table markdown.

    Args:
        stats: Statistics dict from manifest
        total: Total test count
        update_date: Date string for table title

    Returns:
        Markdown formatted overview table
    """
    passed = stats.get("passed", 0)
    failed = stats.get("failed", 0)
    error = stats.get("error", 0)
    skipped = stats.get("skipped", 0)
    pending = stats.get("pending", 0)

    completed = passed + failed + error + stats.get("timeout", 0) + skipped
    coverage_rate = (completed / total * 100) if total > 0 else 0

    return f"""## 当前状态概览（{update_date} 更新）

| 指标 | 数量 | 说明 |
|------|:----:|------|
| 测试清单 | **{total}** | ut_test_list.txt |
| 累计通过 | **{passed}** | kernels/* + v1 + quantization + plugins(1) |
| 累计失败 | **{failed}** | marlin_moe, Triton, fp8 OOM 等 |
| 累计错误 | **{error}+** | Triton编译 + HF网络问题 |
| 累计跳过 | **{skipped}** | 硬件不支持 kernel |
| 覆盖率 | **{coverage_rate:.1f}%** | 约 {completed} 个测试已执行 |

---"""


def generate_summary_section(
    progress_file: Union[str, Path],
    manifest_file: Union[str, Path],
    issues_file: Optional[Union[str, Path]] = None
) -> str:
    """
    Generate summary section for PROGRESS.md.

    Args:
        progress_file: Path to PROGRESS.md
        manifest_file: Path to test_manifest.json
        issues_file: Optional path to issues.json

    Returns:
        Generated summary markdown
    """
    manifest_path = Path(manifest_file)

    if not manifest_path.exists():
        return "**Error: Manifest not found**"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    stats = manifest.get("statistics", {})
    total = manifest.get("total_tests", 0)

    # Generate summary
    lines = [
        "## 执行汇总",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "### 统计数据",
        "",
        "| 状态 | 数量 | 百分比 |",
        "|------|:----:|:------:|",
    ]

    status_labels = {
        "passed": "通过",
        "failed": "失败",
        "error": "错误",
        "timeout": "超时",
        "skipped": "跳过",
        "pending": "待运行",
    }

    for status, label in status_labels.items():
        count = stats.get(status, 0)
        pct = (count / total * 100) if total > 0 else 0
        lines.append(f"| {label} | **{count}** | {pct:.1f}% |")

    # Add issues summary if available
    if issues_file:
        issues_path = Path(issues_file)
        if issues_path.exists():
            tracker = IssuesTracker(issues_path)
            issue_stats = tracker.get_issue_stats()

            lines.extend([
                "",
                "### 问题分类",
                "",
                f"| 总问题数 | 开放 | 已知 | 已修复 |",
                f"|:--------:|:----:|:----:|:------:|",
                f"| **{issue_stats['total_issues']}** | {issue_stats['open']} | {issue_stats['known']} | {issue_stats['fixed']} |",
            ])

    lines.extend([
        "",
        f"*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ])

    return "\n".join(lines)


# ── NEW: Remote Sync via SSH Channel ─────────────────────────────────────────────────────

def sync_from_remote(
    manifest_file: Union[str, Path],
    remote_path: str,
    agent_path: Optional[Union[str, Path]] = None,
    profile: str = "t_h20"
) -> bool:
    """
    Download manifest from remote via SSH channel (不经bastion).

    Uses agent.py SSH channel to read remote manifest content.

    Args:
        manifest_file: Local path to save manifest
        remote_path: Remote manifest path (e.g., /gpfs/gcsp/M2.7_verify/vllm/test_manifest.json)
        agent_path: Path to agent.py (default: look in parent directories)
        profile: Bastion profile name

    Returns:
        True if sync successful
    """
    manifest_path = Path(manifest_file)

    # Find agent.py
    if agent_path:
        agent_py = Path(agent_path)
    else:
        # Search upward from manifest location
        search_dir = manifest_path.parent
        while search_dir != search_dir.parent:
            candidate = search_dir / "agent.py"
            if candidate.exists():
                agent_py = candidate
                break
            search_dir = search_dir.parent

        if not agent_py.exists():
            # Check workspace root
            agent_py = Path(__file__).parent.parent.parent / "agent.py"

    if not agent_py.exists():
        print(f"Error: agent.py not found. Searched: {agent_py}")
        return False

    # Use SSH channel to read remote manifest
    # Read content directly via 'cat' command, not through SFTP
    read_cmd = f"cat {remote_path}"

    try:
        result = subprocess.run(
            ["python", str(agent_py), "-p", profile, "run", "--timeout", "60", read_cmd],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=agent_py.parent
        )

        if result.returncode != 0:
            print(f"Error: Failed to read remote manifest: {result.stderr}")
            return False

        # Parse JSON content
        manifest_content = result.stdout.strip()
        if not manifest_content:
            print(f"Warning: Empty manifest from remote: {remote_path}")
            return False

        # Validate JSON
        try:
            manifest_data = json.loads(manifest_content)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON from remote: {e}")
            return False

        # Save to local
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        print(f"[+] Synced manifest from remote to {manifest_path}")
        print(f"    Remote: {remote_path}")
        print(f"    Tests: {manifest_data.get('total_tests', 'N/A')}")
        return True

    except subprocess.TimeoutExpired:
        print(f"Error: Timeout syncing from remote")
        return False
    except Exception as e:
        print(f"Error: Sync failed: {e}")
        return False


def merge_progress(
    local_manifest: Union[str, Path],
    remote_manifest: Union[str, Path],
    output_file: Optional[Union[str, Path]] = None
) -> dict:
    """
    Merge local + remote progress.

    Strategy:
        - For each test, use the latest status (most recent run_at timestamp)
        - If test was run locally and remotely, keep remote status (more recent)
        - Merge statistics by summing counts

    Args:
        local_manifest: Path to local test_manifest.json
        remote_manifest: Path to remote manifest (or dict if already loaded)
        output_file: Optional output path (default: update local)

    Returns:
        Merged manifest dict
    """
    local_path = Path(local_manifest)

    if not local_path.exists():
        print(f"Warning: Local manifest not found: {local_path}")
        return {}

    # Load local
    with open(local_path, "r", encoding="utf-8") as f:
        local_data = json.load(f)

    # Load remote (may be path or dict)
    if isinstance(remote_manifest, (str, Path)):
        remote_path = Path(remote_manifest)
        if remote_path.exists():
            with open(remote_path, "r", encoding="utf-8") as f:
                remote_data = json.load(f)
        else:
            print(f"Warning: Remote manifest not found: {remote_path}")
            return local_data
    else:
        remote_data = remote_manifest

    # Merge tests
    local_tests = {t["id"]: t for t in local_data.get("tests", [])}
    remote_tests = {t["id"]: t for t in remote_data.get("tests", [])}

    merged_tests = []
    for test_id in local_tests.keys():
        local_test = local_tests[test_id]
        remote_test = remote_tests.get(test_id)

        if remote_test:
            # Compare timestamps
            local_time = local_test.get("run_at", "")
            remote_time = remote_test.get("run_at", "")

            # Use most recent (remote if timestamps are equal or remote is newer)
            if remote_time >= local_time:
                merged_test = remote_test.copy()
            else:
                merged_test = local_test.copy()
        else:
            merged_test = local_test.copy()

        merged_tests.append(merged_test)

    # Add tests that only exist in remote
    for test_id, remote_test in remote_tests.items():
        if test_id not in local_tests:
            merged_tests.append(remote_test.copy())

    # Sort by ID
    merged_tests.sort(key=lambda x: x["id"])

    # Recalculate statistics
    merged_stats = {
        "pending": sum(1 for t in merged_tests if t.get("status") == "pending"),
        "passed": sum(1 for t in merged_tests if t.get("status") == "passed"),
        "failed": sum(1 for t in merged_tests if t.get("status") == "failed"),
        "error": sum(1 for t in merged_tests if t.get("status") == "error"),
        "timeout": sum(1 for t in merged_tests if t.get("status") == "timeout"),
        "skipped": sum(1 for t in merged_tests if t.get("status") == "skipped"),
    }

    # Build merged manifest
    merged_data = {
        "generated_at": datetime.now().isoformat(),
        "source_file": local_data.get("source_file", "merged"),
        "total_tests": len(merged_tests),
        "statistics": merged_stats,
        "tests": merged_tests,
        "merged_from": {
            "local": str(local_manifest),
            "remote": str(remote_manifest) if isinstance(remote_manifest, (str, Path)) else "dict",
            "merged_at": datetime.now().isoformat(),
        }
    }

    # Save output
    output_path = Path(output_file) if output_file else local_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)

    print(f"[+] Merged manifest saved to {output_path}")
    print(f"    Local tests: {len(local_tests)}")
    print(f"    Remote tests: {len(remote_tests)}")
    print(f"    Merged tests: {len(merged_tests)}")

    return merged_data


# ── NEW: Stalled Test Detection ────────────────────────────────────────────────────────

STALLED_THRESHOLD_SECONDS = 600  # 10 minutes


def detect_stalled_tests(
    state_file: Union[str, Path],
    threshold_seconds: int = STALLED_THRESHOLD_SECONDS,
    agent_path: Optional[Union[str, Path]] = None,
    profile: str = "t_h20"
) -> list[dict]:
    """
    Alert if tests running > threshold seconds (default 10 minutes).

    Checks remote processes in execution_state.json and
    verifies if they are still alive on remote server.

    Args:
        state_file: Path to execution_state.json
        threshold_seconds: Stall threshold (default 600s = 10min)
        agent_path: Path to agent.py
        profile: Bastion profile

    Returns:
        List of stalled process info dicts
    """
    state_path = Path(state_file)

    if not state_path.exists():
        print(f"Warning: State file not found: {state_path}")
        return []

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    remote_processes = state.get("remote_processes", [])
    if not remote_processes:
        print("No remote processes to check")
        return []

    # Find agent.py
    if agent_path:
        agent_py = Path(agent_path)
    else:
        agent_py = Path(__file__).parent.parent.parent.parent / "agent.py"

    stalled = []
    now = datetime.now()

    for proc in remote_processes:
        started_at = proc.get("started_at", "")
        pid = proc.get("pid", 0)
        batch_id = proc.get("batch_id", "unknown")

        if not started_at:
            continue

        try:
            start_time = datetime.fromisoformat(started_at)
        except ValueError:
            continue

        running_seconds = (now - start_time).total_seconds()

        if running_seconds > threshold_seconds:
            # Check if process is still alive
            is_alive = check_remote_process_alive(pid, agent_py, profile)

            if is_alive:
                stalled_info = {
                    "batch_id": batch_id,
                    "pid": pid,
                    "started_at": started_at,
                    "running_seconds": int(running_seconds),
                    "status": "stalled",
                    "log_file": proc.get("log_file", "N/A"),
                }
                stalled.append(stalled_info)

                # Alert
                print(f"[!] STALLED: {batch_id} running for {int(running_seconds/60)} minutes (PID: {pid})")
            else:
                # Process already finished, update state
                print(f"[+] Process {pid} ({batch_id}) already finished")

    return stalled


def check_remote_process_alive(pid: int, agent_py: Path, profile: str) -> bool:
    """
    Check if a remote process is still alive via SSH channel.

    Args:
        pid: Process ID on remote server
        agent_py: Path to agent.py
        profile: Bastion profile

    Returns:
        True if process is alive
    """
    if pid == 0:
        return False

    check_cmd = f"ps -p {pid} -o pid= 2>/dev/null || echo NOT_FOUND"

    try:
        result = subprocess.run(
            ["python", str(agent_py), "-p", profile, "run", "--timeout", "30", check_cmd],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=agent_py.parent
        )

        if "NOT_FOUND" in result.stdout or not result.stdout.strip():
            return False

        return True

    except Exception as e:
        print(f"Warning: Failed to check process {pid}: {e}")
        return False  # Assume not alive if check fails


# ── NEW: Issues Integration ────────────────────────────────────────────────────────

def update_issues_json(
    issues_file: Union[str, Path],
    test_result: dict,
    error_message: Optional[str] = None
) -> str:
    """
    Track issues from test failures in issues.json.

    Categorizes error and adds to IssuesTracker.

    Args:
        issues_file: Path to issues.json
        test_result: Dict with test_id, test_node, status, error_message
        error_message: Optional error message (extracted from test_result if not provided)

    Returns:
        Issue ID if created, or existing issue ID if similar issue exists
    """
    issues_path = Path(issues_file)

    tracker = IssuesTracker(issues_path)

    # Extract error info
    status = test_result.get("status", "unknown")
    test_id = test_result.get("test_id", "unknown")
    test_node = test_result.get("test_node", "unknown")

    if status == "passed":
        return None  # No issue for passed tests

    error_msg = error_message or test_result.get("error_message", "Unknown error")

    # Categorize
    _, category = tracker.categorize_error(error_msg)

    # Add issue
    issue_id = tracker.add_issue(
        category=category,
        description=error_msg[:80],
        test_id=str(test_id),
        notes=f"Test node: {test_node}"
    )

    print(f"[+] Added issue {issue_id} ({category}): {test_node}")
    return issue_id


def batch_update_issues(
    issues_file: Union[str, Path],
    test_results: list[dict]
) -> dict:
    """
    Update issues from batch of test results.

    Args:
        issues_file: Path to issues.json
        test_results: List of test result dicts

    Returns:
        Dict with issue counts by category
    """
    issues_path = Path(issues_file)
    tracker = IssuesTracker(issues_path)

    issue_counts = defaultdict(int)

    for result in test_results:
        if result.get("status") == "passed":
            continue

        issue_id = update_issues_json(issues_file, result)
        if issue_id:
            # Extract category from issue_id (e.g., "P-1" -> "P")
            category_prefix = issue_id.split("-")[0] if "-" in issue_id else "X"
            issue_counts[category_prefix] += 1

    tracker.save_issues()

    return dict(issue_counts)


# ── Enhanced CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Track test progress")
    parser.add_argument("--manifest", "-m", required=False, help="JSON manifest file")
    parser.add_argument("--report-dir", "-r", help="Generate markdown report to directory")

    # NEW: Progress append mode
    parser.add_argument("--progress-file", help="PROGRESS.md file path")
    parser.add_argument("--append-progress", metavar="TYPE",
                        choices=["batch_execution", "issue_discovery", "phase_switch", "disconnect_recovery"],
                        help="Append progress record (type: batch_execution, issue_discovery, phase_switch, disconnect_recovery)")
    parser.add_argument("--record-content", help="JSON content for progress record")

    # NEW: Overview update
    parser.add_argument("--update-overview", action="store_true",
                        help="Update overview table in PROGRESS.md")

    # NEW: Summary generation
    parser.add_argument("--generate-summary", action="store_true",
                        help="Generate summary section")
    parser.add_argument("--issues-file", help="issues.json path for summary")

    # NEW: Remote sync
    parser.add_argument("--sync-remote", action="store_true",
                        help="Sync manifest from remote server")
    parser.add_argument("--remote-path", default="/gpfs/gcsp/M2.7_verify/vllm/test_manifest.json",
                        help="Remote manifest path")
    parser.add_argument("--agent-path", help="Path to agent.py")
    parser.add_argument("--profile", default="t_h20",
                        help="Bastion profile name")

    # NEW: Merge progress
    parser.add_argument("--merge", action="store_true",
                        help="Merge local and remote manifest")
    parser.add_argument("--remote-manifest", help="Remote manifest file (local path after sync)")

    # NEW: Stalled detection
    parser.add_argument("--detect-stalled", action="store_true",
                        help="Detect stalled tests (>10 minutes)")
    parser.add_argument("--state-file", default="execution_state.json",
                        help="execution_state.json path")
    parser.add_argument("--stalled-threshold", type=int, default=600,
                        help="Stalled threshold in seconds (default: 600)")

    args = parser.parse_args()

    # Handle progress append
    if args.append_progress:
        if not args.progress_file and args.manifest:
            args.progress_file = get_progress_md_path(args.manifest)

        if args.record_content:
            content = json.loads(args.record_content)
        else:
            # Build minimal content
            content = {"test_range": "N/A"}

        append_to_progress_md(args.progress_file, args.append_progress, content)
        return

    # Handle overview update
    if args.update_overview:
        if not args.manifest:
            print("Error: --manifest required for --update-overview")
            return

        progress_file = args.progress_file or get_progress_md_path(args.manifest)
        update_overview_table(progress_file, args.manifest)
        return

    # Handle summary generation
    if args.generate_summary:
        if not args.manifest:
            print("Error: --manifest required for --generate-summary")
            return

        progress_file = args.progress_file or get_progress_md_path(args.manifest)
        summary = generate_summary_section(progress_file, args.manifest, args.issues_file)
        print(summary)
        return

    # Handle remote sync
    if args.sync_remote:
        if not args.manifest:
            print("Error: --manifest required for --sync-remote")
            return

        sync_from_remote(args.manifest, args.remote_path, args.agent_path, args.profile)
        return

    # Handle merge
    if args.merge:
        if not args.manifest:
            print("Error: --manifest required for --merge")
            return

        if not args.remote_manifest:
            # Use synced manifest as remote
            args.remote_manifest = args.manifest + ".remote"

        merge_progress(args.manifest, args.remote_manifest)
        return

    # Handle stalled detection
    if args.detect_stalled:
        stalled = detect_stalled_tests(
            args.state_file,
            args.stalled_threshold,
            args.agent_path,
            args.profile
        )

        if stalled:
            print(f"\n[!] Found {len(stalled)} stalled tests:")
            for proc in stalled:
                print(f"  - {proc['batch_id']}: running for {proc['running_seconds']}s")
        else:
            print("[+] No stalled tests detected")
        return

    # Default: show progress
    if args.manifest:
        show_progress(args.manifest)

        if args.report_dir:
            generate_report(args.manifest, args.report_dir)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()