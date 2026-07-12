#!/usr/bin/env python3
"""
auto_run_batches_two_phase.py - Phase 1: Script batch execution with forced checkpoints

Purpose:
  Two-phase strategy Phase 1 implementation:
  - Pure script batch execution (no agent intervention)
  - 4 forced checkpoints per batch (avoid manifest missing)
  - checkpoint_interval config (support resume from interruption)
  - Generate phase1_summary.json report on completion

Usage:
    python tasks/ut/scripts/auto_run_batches_two_phase.py \
        --workflow-yaml tasks/ut/deployment/production/config/workflow.yaml \
        --run-dir runs/ut-20260706-123456

Design: tasks/ut/docs/designs/2026-07-06-two-phase-strategy-design.md §5 (lines 92-159)
  - Lines 92-159: Phase 1 execution flow with 4 forced checkpoints
  - Lines 163-169: Phase 1 config parameters
"""

import os
# Clear PYTHONPATH to avoid Hermes venv leaking into apmm subprocesses
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from skills.ut.shared import get_paths, get_config


# ============================================================================
# Helper Functions
# ============================================================================

def create_batch_id(index: int, prefix: str = "batch") -> str:
    """Create batch_id with timestamp format: batch_{YYYYMMDD_HHMMSS}

    Args:
        index: Batch index (used for uniqueness)
        prefix: Batch prefix (default: "batch")

    Returns:
        Batch ID string
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}_{index:04d}"


def create_batch_config(
    batch_id: str,
    manifest_path: Path,
    batch_dir: Path,
    batch_size: int,
    workflow_state_path: Path,
) -> Path:
    """Stage 1: Generate batch_config.json

    Args:
        batch_id: Batch identifier
        manifest_path: Path to manifest.json
        batch_dir: Batch directory path (parent of batch_id subdir)
        batch_size: Number of tests per batch
        workflow_state_path: Path to workflow_state.json

    Returns:
        Path to generated batch_config.json

    Raises:
        subprocess.CalledProcessError: If generate_batch.py fails
    """
    # Call generate_batch.py with --workflow-state (recommended)
    # Note: batch_dir will become parent, generate_batch.py creates batch_id subdir
    cmd = [
        sys.executable,
        str(_project_root / "skills/ut/batch-selector/scripts/generate_batch.py"),
        "--workflow-state", str(workflow_state_path),
        "--batch-dir", str(batch_dir),  # Parent dir, generate_batch.py creates batch_id subdir
        "--batch-size", str(batch_size),
        "--batch-id", batch_id,  # Explicit batch_id for consistency
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )

    # batch_config.json is at batch_dir / batch_id / batch_config.json
    config_path = batch_dir / batch_id / "batch_config.json"
    return config_path


def validate_config_schema(config_path: Path) -> bool:
    """Validate batch_config.json schema

    Args:
        config_path: Path to batch_config.json

    Returns:
        True if valid, False otherwise
    """
    if not config_path.exists():
        return False

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))

        # Check required fields
        required_fields = ["batch_id", "tests", "generated_at"]
        for field in required_fields:
            if field not in config:
                return False

        # Check tests array is not empty
        if not isinstance(config.get("tests"), list) or len(config["tests"]) == 0:
            return False

        return True
    except (json.JSONDecodeError, Exception):
        return False


def execute_batch_script(
    batch_id: str,
    batch_config_path: Path,
    workflow_state_path: Path,
) -> dict:
    """Stage 2: Execute batch pytest tests

    Args:
        batch_id: Batch identifier
        batch_config_path: Path to batch_config.json
        workflow_state_path: Path to workflow_state.json

    Returns:
        Execution result dict with exit_code, stdout, stderr

    Raises:
        subprocess.CalledProcessError: If execute_batch.py fails
    """
    cmd = [
        sys.executable,
        str(_project_root / "skills/ut/unit-test-executor/scripts/execute_batch.py"),
        "--batch-config", str(batch_config_path),
        "--workflow-state", str(workflow_state_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "batch_id": batch_id,
    }


def validate_batch_results(
    batch_id: str,
    batch_dir: Path,
    result: dict,
) -> Path:
    """Stage 3: Validate batch_results.json

    Args:
        batch_id: Batch identifier
        batch_dir: Batch directory path
        result: Execution result from execute_batch_script

    Returns:
        Path to batch_results.json

    Note:
        In the current implementation, execute_batch.py already writes
        batch_results.json to the batch_dir. This function validates
        the file exists and returns its path.
    """
    batch_results_path = batch_dir / "batch_results.json"

    # execute_batch.py already writes batch_results.json
    # We just need to verify it exists
    if not batch_results_path.exists():
        # If missing, we could write from result.stdout (but this shouldn't happen)
        raise FileNotFoundError(f"batch_results.json not found: {batch_results_path}")

    return batch_results_path


def update_batch_state(
    batch_id: str,
    batch_results_path: Path,
    workflow_state_path: Path,
) -> None:
    """Stage 4.5: Update test_load + workflow_state via update_batch_state.py

    Uses update_batch_state.py which:
    1. Reads batch_results.json + handled_tests.json from batch_dir
    2. Applies v5 merge to test_load (retry_count, retriable_error->ignored, handled overrides)
    3. Updates workflow_state.json batch status to completed

    Args:
        batch_id: Batch identifier
        batch_results_path: Path to batch_results.json
        workflow_state_path: Path to workflow_state.json

    Raises:
        subprocess.CalledProcessError: If update fails
    """
    cmd = [
        sys.executable,
        str(_project_root / "skills/ut/shared/update_batch_state.py"),
        "--workflow-state", str(workflow_state_path),
        "--batch-id", batch_id,
        "--batch-results", str(batch_results_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )


def verify_batch_updated(batch_id: str, workflow_state_path: Path) -> bool:
    """Checkpoint 4: Verify test_load was updated for batch

    Reads test_load path from workflow_state.json, then checks if any test
    has this batch_id with updated status (non-pending).
    """
    try:
        state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        paths = state.get("paths", {})
        test_load_path = paths.get("test_load", "")
        if not test_load_path or not Path(test_load_path).exists():
            return False
        test_load = json.loads(Path(test_load_path).read_text(encoding="utf-8"))
        for test in test_load.get("tests", []):
            if test.get("last_batch_id") == batch_id:
                if test.get("status", "pending") != "pending":
                    return True
        return False
    except (json.JSONDecodeError, Exception):
        return False


def write_checkpoint_file(
    checkpoint_log: list,
    run_dir: Path,
    checkpoint_file: str = "phase1_checkpoint.json",
) -> None:
    """Write checkpoint file for resume support

    Args:
        checkpoint_log: List of batch execution records
        run_dir: Run directory path
        checkpoint_file: Checkpoint filename
    """
    checkpoint_path = run_dir / checkpoint_file

    checkpoint_data = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": "phase1",
        "total_batches": len(checkpoint_log),
        "successful_batches": sum(1 for entry in checkpoint_log if "SUCCESS" in entry.get("status", "")),
        "failed_batches": sum(1 for entry in checkpoint_log if "ERROR" in entry.get("status", "")),
        "checkpoint_log": checkpoint_log,
    }

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        json.dumps(checkpoint_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def generate_phase1_summary(checkpoint_log: list) -> dict:
    """Generate Phase 1 summary report

    Args:
        checkpoint_log: List of batch execution records

    Returns:
        Phase 1 summary dict
    """
    total = len(checkpoint_log)
    successful = sum(1 for entry in checkpoint_log if "SUCCESS" in entry.get("status", ""))
    failed = sum(1 for entry in checkpoint_log if "ERROR" in entry.get("status", ""))
    aborted = sum(1 for entry in checkpoint_log if "ABORT" in entry.get("status", ""))

    summary = {
        "phase": "phase1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_batches": total,
        "successful_batches": successful,
        "failed_batches": failed,
        "aborted_batches": aborted,
        "success_rate": round(successful / total * 100, 2) if total > 0 else 0.0,
        "checkpoint_log": checkpoint_log,
        "status": "completed" if aborted == 0 else "aborted",
    }

    return summary


def write_report(report: dict, filename: str, run_dir: Path) -> None:
    """Write report to file

    Args:
        report: Report data dict
        filename: Output filename
        run_dir: Run directory path
    """
    report_path = run_dir / filename
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def log_error(message: str, run_dir: Path) -> None:
    """Log error to phase1_errors.log

    Args:
        message: Error message
        run_dir: Run directory path
    """
    error_log_path = run_dir / "phase1_errors.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    error_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(error_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


# ============================================================================
# Main Phase 1 Loop
# ============================================================================

def get_phase1_config(config: dict) -> dict:
    """Read phase1 config block from workflow.yaml

    Args:
        config: Config dict from workflow.yaml (from get_config)

    Returns:
        Phase1 config dict with defaults applied

    Note:
        Returns defaults if phase1 block not found in workflow.yaml
    """
    phase1_defaults = {
        "auto_create_batches": True,
        "auto_execute": True,
        "checkpoint_interval": 10,
        "enable_force_checkpoints": True,
    }

    phase1_config = config.get("phase1", {})

    # Merge: config values override defaults
    for key, default_value in phase1_defaults.items():
        if key not in phase1_config:
            phase1_config[key] = default_value

    return phase1_config


def phase1_batch_loop(
    workflow_yaml_path: Path,
    run_dir: Path,
    batch_group_size: Optional[int] = None,
    checkpoint_interval: Optional[int] = None,
    enable_force_checkpoints: Optional[bool] = None,
    auto_create_batches: Optional[bool] = None,
    auto_execute: Optional[bool] = None,
) -> list:
    """Phase 1: Script batch execution + forced checkpoints

    Args:
        workflow_yaml_path: Path to workflow.yaml
        run_dir: Run directory path
        batch_group_size: Number of batches to execute (CLI override, reads from config if None)
        checkpoint_interval: Write checkpoint every N batches (CLI override, reads from config if None)
        enable_force_checkpoints: Enable 4 forced checkpoints per batch (CLI override, reads from config if None)
        auto_create_batches: Auto create batch configs (CLI override, reads from config if None)
        auto_execute: Auto execute batches (CLI override, reads from config if None)

    Returns:
        Checkpoint log list

    Raises:
        AssertionError: On checkpoint failure (immediate abort)

    Config-driven design:
        All parameters read from workflow.yaml phase1 config block by default.
        CLI args override config values when explicitly provided.
    """
    # Load workflow.yaml config
    config = get_config(workflow_yaml_path)

    # Get phase1 config block (with defaults)
    phase1_config = get_phase1_config(config)

    # ✅ Read batch_group_size from workflow top-level (per design §10)
    # Default value if not configured
    batch_group_size_default = 10

    # Apply CLI overrides (CLI > config)
    if batch_group_size is not None:
        # CLI override
        final_batch_group_size = batch_group_size
    else:
        # Read from workflow.yaml top-level
        final_batch_group_size = config.get("batch_group_size", batch_group_size_default)

    if checkpoint_interval is not None:
        phase1_config["checkpoint_interval"] = checkpoint_interval
    if enable_force_checkpoints is not None:
        phase1_config["enable_force_checkpoints"] = enable_force_checkpoints
    if auto_create_batches is not None:
        phase1_config["auto_create_batches"] = auto_create_batches
    if auto_execute is not None:
        phase1_config["auto_execute"] = auto_execute

    # Final values (config + CLI overrides)
    batch_group_size = final_batch_group_size
    checkpoint_interval = phase1_config["checkpoint_interval"]
    enable_force_checkpoints = phase1_config["enable_force_checkpoints"]
    auto_create_batches = phase1_config["auto_create_batches"]
    auto_execute = phase1_config["auto_execute"]

    # Get paths from workflow_state.json
    workflow_state_path = run_dir / "workflow_state.json"
    paths = get_paths(workflow_state_path)

    manifest_path = Path(paths["manifest"])
    batches_dir = paths["run_dir"] / "batches"  # Batches parent directory

    # Ensure test_load exists (auto-generate if missing)
    test_load_path = paths.get("test_load", "")
    if not test_load_path or not Path(test_load_path).exists():
        print(f"[Phase 1] test_load not found, generating...")
        # Read count from workflow.yaml
        tl_count = config.get("workflow", {}).get("test_load", {}).get("count", 1000)
        gtl_cmd = [
            sys.executable,
            str(_project_root / "tasks" / "ut" / "scripts" / "generate_test_load.py"),
            "--manifest-path", str(manifest_path),
            "--count", str(tl_count),
            "--output-dir", str(paths["run_dir"]),
            "--workflow-state", str(workflow_state_path),
        ]
        gtl_result = subprocess.run(gtl_cmd, capture_output=True, text=True)
        if gtl_result.returncode != 0:
            print(f"[Phase 1] generate_test_load failed: {gtl_result.stderr}")
            sys.exit(1)
        print(gtl_result.stdout)
        # Reload paths
        paths = get_paths(workflow_state_path)
        test_load_path = paths.get("test_load", "")
    else:
        print(f"[Phase 1] Using test_load: {test_load_path}")

    # Get batch_size from workflow.yaml
    batch_size = config.get("config", {}).get("batch_size", 8)

    # ✅ Resume support: Read existing checkpoint if available
    checkpoint_path = run_dir / "phase1_checkpoint.json"
    if checkpoint_path.exists():
        checkpoint_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint_log = checkpoint_data.get("checkpoint_log", [])
        start_index = len(checkpoint_log)
        completed_batch_ids = [e.get("batch_id") for e in checkpoint_log if e.get("status") == "✓ SUCCESS"]
        print(f"[Phase 1] Resuming from checkpoint: {start_index} batches already processed, {len(completed_batch_ids)} successful")
    else:
        checkpoint_log = []
        start_index = 0
        completed_batch_ids = []
        print("[Phase 1] Starting fresh execution (no checkpoint found)")

    print(f"[Phase 1] Starting batch loop: {batch_group_size - start_index} batches remaining (total: {batch_group_size})")
    print(f"[Phase 1] Batch size: {batch_size}")
    print(f"[Phase 1] Checkpoint interval: {checkpoint_interval}")
    print(f"[Phase 1] Force checkpoints: {enable_force_checkpoints}")
    print(f"[Phase 1] Auto create batches: {auto_create_batches}")
    print(f"[Phase 1] Auto execute: {auto_execute}")

    for i in range(start_index, batch_group_size):
        batch_id = create_batch_id(i)

        print(f"\n[Batch {i+1}/{batch_group_size}] {batch_id}")

        try:
            # Stage 1: Batch配置生成
            print(f"  [Stage 1] Creating batch config...")
            # generate_batch.py creates batches_dir / batch_id / batch_config.json
            config_path = create_batch_config(
                batch_id, manifest_path, batches_dir, batch_size, workflow_state_path
            )

            # Batch directory is batches_dir / batch_id
            batch_dir = batches_dir / batch_id

            # ✅ 检查点1: 配置文件完整性
            if enable_force_checkpoints:
                assert config_path.exists(), f"[STOP] 配置文件未创建: {config_path}"
                assert validate_config_schema(config_path), f"[STOP] 配置格式错误: {config_path}"
                print(f"  ✓ Checkpoint 1: Config validated")

            # Stage 2: Batch执行
            print(f"  [Stage 2] Executing batch...")
            result = execute_batch_script(batch_id, config_path, workflow_state_path)

            # ✅ 检查点2: 执行完成验证
            if enable_force_checkpoints:
                assert result["exit_code"] is not None, f"[STOP] 执行未完成: {batch_id}"
                print(f"  ✓ Checkpoint 2: Execution completed (exit_code={result['exit_code']})")

            # Stage 3: 结果收集
            print(f"  [Stage 3] Collecting results...")
            result_path = validate_batch_results(batch_id, batch_dir, result)

            # ✅ 检查点3: 结果文件生成
            if enable_force_checkpoints:
                assert result_path.exists(), f"[STOP] 结果文件未生成: {result_path}"
                print(f"  ✓ Checkpoint 3: Results collected")

            # Stage 4.5: test_load update增量更新
            print(f"  [Stage 4.5] Updating test_load...")
            update_batch_state(batch_id, result_path, workflow_state_path)

            # ✅ 检查点4: test_load更新验证
            if enable_force_checkpoints:
                assert verify_batch_updated(batch_id, workflow_state_path), f"[STOP] test_load未更新: {batch_id}"
                print(f"  ✓ Checkpoint 4: test_load updated")

            checkpoint_log.append({
                "batch_id": batch_id,
                "status": "✓ SUCCESS",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "exit_code": result["exit_code"],
            })

            # ✅ 定期checkpoint写入（便于恢复）
            if (i + 1) % checkpoint_interval == 0:
                write_checkpoint_file(checkpoint_log, run_dir)
                print(f"\n[Checkpoint] 已完成 {i+1}/{batch_group_size} 个batch")

        except AssertionError as e:
            # ✗ 检查点失败 → 立即停止循环
            log_error(f"[ABORT] 检查点失败: {e}", run_dir)
            checkpoint_log.append({
                "batch_id": batch_id,
                "status": f"✗ ABORT: {str(e)}",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            write_checkpoint_file(checkpoint_log, run_dir)
            raise

        except Exception as e:
            # 记录错误但继续执行
            log_error(f"[ERROR] Batch执行异常: {batch_id} - {e}", run_dir)
            checkpoint_log.append({
                "batch_id": batch_id,
                "status": f"✗ ERROR: {str(e)}",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            print(f"  ✗ Error: {e}")
            # Continue to next batch

    # Phase 1完成报告
    phase1_report = generate_phase1_summary(checkpoint_log)
    write_report(phase1_report, "phase1_summary.json", run_dir)

    print(f"\n[Phase 1 Complete] Summary:")
    print(f"  Total batches: {phase1_report['total_batches']}")
    print(f"  Successful: {phase1_report['successful_batches']}")
    print(f"  Failed: {phase1_report['failed_batches']}")
    print(f"  Success rate: {phase1_report['success_rate']}%")
    print(f"  Report: {run_dir / 'phase1_summary.json'}")

    return checkpoint_log


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Phase 1: Script batch execution with forced checkpoints"
    )
    parser.add_argument(
        "--workflow-yaml",
        required=True,
        help="Path to workflow.yaml config file",
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to run directory (contains workflow_state.json)",
    )
    parser.add_argument(
        "--batch-group-size",
        type=int,
        default=None,
        help="Number of batches to execute (default: from workflow.yaml phase1 config)",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=None,
        help="Write checkpoint every N batches (default: from workflow.yaml phase1 config)",
    )
    parser.add_argument(
        "--enable-force-checkpoints",
        action="store_true",
        default=None,
        dest="enable_force_checkpoints",
        help="Enable 4 forced checkpoints per batch (default: from workflow.yaml phase1 config)",
    )
    parser.add_argument(
        "--no-force-checkpoints",
        action="store_false",
        dest="enable_force_checkpoints",
        help="Disable forced checkpoints",
    )
    parser.add_argument(
        "--auto-create-batches",
        action="store_true",
        default=None,
        dest="auto_create_batches",
        help="Auto create batch configs (default: from workflow.yaml phase1 config)",
    )
    parser.add_argument(
        "--no-auto-create-batches",
        action="store_false",
        dest="auto_create_batches",
        help="Disable auto batch creation",
    )
    parser.add_argument(
        "--auto-execute",
        action="store_true",
        default=None,
        dest="auto_execute",
        help="Auto execute batches (default: from workflow.yaml phase1 config)",
    )
    parser.add_argument(
        "--no-auto-execute",
        action="store_false",
        dest="auto_execute",
        help="Disable auto execution",
    )

    args = parser.parse_args()

    workflow_yaml_path = Path(args.workflow_yaml)
    run_dir = Path(args.run_dir)

    if not workflow_yaml_path.exists():
        print(f"Error: workflow.yaml not found: {workflow_yaml_path}")
        sys.exit(1)

    if not run_dir.exists():
        print(f"Error: run_dir not found: {run_dir}")
        sys.exit(1)

    try:
        checkpoint_log = phase1_batch_loop(
            workflow_yaml_path,
            run_dir,
            batch_group_size=args.batch_group_size,
            checkpoint_interval=args.checkpoint_interval,
            enable_force_checkpoints=args.enable_force_checkpoints,
            auto_create_batches=args.auto_create_batches,
            auto_execute=args.auto_execute,
        )
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FATAL] Checkpoint failure: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
