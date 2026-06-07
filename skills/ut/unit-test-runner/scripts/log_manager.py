#!/usr/bin/env python3
"""
log_manager.py - Manage test execution logs for multi-phase test automation

Manages log organization by phase, log rotation, and cleanup.
Logs are stored on the remote server under ut_logs/ directory.

Usage:
    from log_manager import LogManager, TestLogMetadata, TestLogResult

    log_manager = LogManager("/gpfs/gcsp/M2.7_verify/vllm/ut_logs")
    log_manager.setup_log_dirs()

    # Write a test log
    log_path = log_manager.get_log_path(phase=1, test_id=4200)
    metadata = TestLogMetadata(
        test_id=4200,
        test_node="tests/kernels/test_cache.py::test_basic",
        phase=1,
        started="2026-06-05T10:30:00",
        worker=1,
        gpu="0-1"
    )
    result = TestLogResult(
        status="PASSED",
        duration_ms=2300,
        exit_code=0
    )
    log_manager.write_test_log(log_path, metadata, pytest_output, result)

    # Rotate old logs (compress to archive)
    log_manager.rotate_logs()

    # Optional: cleanup passed logs older than 7 days
    log_manager.cleanup_passed_logs()
"""

import gzip
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LogConfig:
    """Configuration for log management."""
    log_root: str = "/gpfs/gcsp/M2.7_verify/vllm/ut_logs"
    max_size_bytes: int = 10 * 1024 * 1024  # 10MB
    archive_days: int = 30  # Compress logs older than 30 days
    cleanup_passed_days: int = 7  # Clean passed logs older than 7 days (optional)
    cleanup_passed: bool = False  # Whether to auto-cleanup passed logs
    truncate_lines: int = 5000  # Max lines to keep when truncating


@dataclass
class TestLogMetadata:
    """Metadata for a test log entry."""
    test_id: int
    test_node: str
    phase: int
    started: str  # ISO format timestamp
    worker: int
    gpu: str


@dataclass
class TestLogResult:
    """Result section for a test log entry."""
    status: str  # PASSED, FAILED, ERROR, TIMEOUT, SKIPPED
    duration_ms: int
    exit_code: int
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class LogManager:
    """
    Manages test execution logs for multi-phase test automation.

    Log Directory Structure:
        ut_logs/
        ├── phase1/        # Phase 1 logs
        ├── phase2/        # Phase 2 logs
        ├── phase3/        # Phase 3 error handling logs
        ├── stalled/       # Interrupted/stalled tests
        └── archive/       # Compressed logs (>30 days)

    Log Naming Convention:
        - Single test: {YYYYMMDD}_test_{id}.log
        - Batch test: batch_{YYYYMMDD}_{seq}.log
    """

    PHASE_DIRS = ["phase1", "phase2", "phase3", "stalled", "archive"]

    def __init__(self, log_root: Optional[str] = None, config: Optional[LogConfig] = None):
        """
        Initialize LogManager.

        Args:
            log_root: Root directory for logs. If None, uses config default.
            config: LogConfig object. If None, uses defaults.
        """
        self.config = config or LogConfig()
        if log_root:
            self.config.log_root = log_root
        self.log_root = Path(self.config.log_root)

    def setup_log_dirs(self) -> dict[str, Path]:
        """
        Create log directories for all phases.

        Creates: phase1/, phase2/, phase3/, stalled/, archive/

        Returns:
            Dictionary mapping directory names to Path objects
        """
        dirs = {}
        for phase_dir in self.PHASE_DIRS:
            dir_path = self.log_root / phase_dir
            dir_path.mkdir(parents=True, exist_ok=True)
            dirs[phase_dir] = dir_path
        return dirs

    def get_log_path(
        self,
        phase: int,
        test_id: Optional[int] = None,
        batch_seq: Optional[int] = None,
        is_stalled: bool = False
    ) -> Path:
        """
        Generate log path based on phase and test_id or batch sequence.

        Args:
            phase: Phase number (1, 2, or 3)
            test_id: Test ID for single test log
            batch_seq: Batch sequence number for batch logs
            is_stalled: If True, use stalled/ directory

        Returns:
            Path object for the log file

        Raises:
            ValueError: If neither test_id nor batch_seq is provided
        """
        today = datetime.now().strftime("%Y%m%d")

        if is_stalled:
            base_dir = self.log_root / "stalled"
            if test_id is not None:
                filename = f"stalled_{today}_test_{test_id}.log"
            elif batch_seq is not None:
                filename = f"stalled_{today}_batch_{batch_seq:03d}.log"
            else:
                raise ValueError("Either test_id or batch_seq must be provided")
        else:
            base_dir = self.log_root / f"phase{phase}"

            if test_id is not None:
                filename = f"{today}_test_{test_id:04d}.log"
            elif batch_seq is not None:
                filename = f"batch_{today}_{batch_seq:03d}.log"
            else:
                raise ValueError("Either test_id or batch_seq must be provided")

        return base_dir / filename

    def write_test_log(
        self,
        log_path: Path,
        metadata: TestLogMetadata,
        pytest_output: str,
        result: TestLogResult
    ) -> Path:
        """
        Write a test log with metadata header, pytest output, and result footer.

        Log format:
            === TEST METADATA ===
            test_id: 4200
            test_node: tests/kernels/test_cache.py::test_basic
            phase: 1
            started: 2026-06-05T10:30:00
            worker: 1
            gpu: 0-1
            === END METADATA ===

            # pytest output...

            === TEST RESULT ===
            status: PASSED
            duration_ms: 2300
            exit_code: 0
            === END RESULT ===

        Args:
            log_path: Path to write the log file
            metadata: TestLogMetadata object
            pytest_output: Raw pytest output
            result: TestLogResult object

        Returns:
            Path to the written log file
        """
        # Ensure parent directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Truncate output if too large
        pytest_output = self._truncate_output(pytest_output)

        # Build log content
        content = self._format_log_content(metadata, pytest_output, result)

        # Write log file
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)

        return log_path

    def _format_log_content(
        self,
        metadata: TestLogMetadata,
        pytest_output: str,
        result: TestLogResult
    ) -> str:
        """Format the complete log content."""
        lines = [
            "=== TEST METADATA ===",
            f"test_id: {metadata.test_id}",
            f"test_node: {metadata.test_node}",
            f"phase: {metadata.phase}",
            f"started: {metadata.started}",
            f"worker: {metadata.worker}",
            f"gpu: {metadata.gpu}",
            "=== END METADATA ===",
            "",
            pytest_output,
            "",
            "=== TEST RESULT ===",
            f"status: {result.status}",
            f"duration_ms: {result.duration_ms}",
            f"exit_code: {result.exit_code}",
        ]

        if result.error_type:
            lines.append(f"error_type: {result.error_type}")
        if result.error_message:
            lines.append(f"error_message: {result.error_message}")

        lines.append("=== END RESULT ===")
        lines.append("")  # Trailing newline

        return "\n".join(lines)

    def _truncate_output(self, output: str) -> str:
        """
        Truncate output if it exceeds max_size_bytes.

        Keeps first truncate_lines lines if truncation is needed.
        For very large single lines, truncates to max_size_bytes directly.
        """
        encoded_size = len(output.encode('utf-8'))
        if encoded_size <= self.config.max_size_bytes:
            return output

        # Try truncation by lines first
        lines = output.split('\n')
        truncated_lines = lines[:self.config.truncate_lines]
        truncated = '\n'.join(truncated_lines)
        line_truncated = True

        # If still too large (e.g., very long single lines), truncate by bytes
        while len(truncated.encode('utf-8')) > self.config.max_size_bytes and len(truncated_lines) > 1:
            truncated_lines.pop()
            truncated = '\n'.join(truncated_lines)

        # Final byte truncation if needed
        encoded = truncated.encode('utf-8')
        if len(encoded) > self.config.max_size_bytes:
            # Truncate to max_size_bytes - 100 (for truncation message)
            truncated = encoded[:self.config.max_size_bytes - 100].decode('utf-8', errors='ignore')
            line_truncated = False

        # Build truncation message based on truncation type
        if line_truncated:
            trunc_msg = f"\n\n... [TRUNCATED - Original size: {encoded_size // (1024*1024)}MB, kept first {len(truncated_lines)} lines]"
        else:
            kept_size_kb = len(truncated.encode('utf-8')) // 1024
            trunc_msg = f"\n\n... [TRUNCATED - Original size: {encoded_size // (1024*1024)}MB, kept first {kept_size_kb}KB]"

        return truncated + trunc_msg

    def rotate_logs(self, days: Optional[int] = None) -> list[Path]:
        """
        Compress old logs to archive directory.

        Logs older than archive_days are compressed to .gz files
        and moved to the archive/ directory.

        Args:
            days: Override archive_days config. If None, uses config value.

        Returns:
            List of archived log paths
        """
        archive_days = days if days is not None else self.config.archive_days
        cutoff_date = datetime.now() - timedelta(days=archive_days)
        archive_dir = self.log_root / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        archived_files = []

        # Process phase directories (not stalled or archive)
        for phase_dir_name in ["phase1", "phase2", "phase3", "stalled"]:
            phase_dir = self.log_root / phase_dir_name
            if not phase_dir.exists():
                continue

            for log_file in phase_dir.glob("*.log"):
                # Check file modification time
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

                if mtime < cutoff_date:
                    # Compress and move to archive
                    archived_path = self._compress_and_archive(log_file, archive_dir)
                    archived_files.append(archived_path)

        return archived_files

    def _compress_and_archive(self, log_file: Path, archive_dir: Path) -> Path:
        """
        Compress a log file and move it to archive.

        Args:
            log_file: Path to the log file to archive
            archive_dir: Path to the archive directory

        Returns:
            Path to the archived .gz file
        """
        # Create compressed file with phase prefix
        phase_prefix = log_file.parent.name  # e.g., "phase1"
        archive_name = f"{phase_prefix}_{log_file.stem}.log.gz"
        archive_path = archive_dir / archive_name

        # Handle duplicate names
        counter = 1
        while archive_path.exists():
            archive_name = f"{phase_prefix}_{log_file.stem}_{counter}.log.gz"
            archive_path = archive_dir / archive_name
            counter += 1

        # Compress
        with open(log_file, 'rb') as f_in:
            with gzip.open(archive_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove original
        log_file.unlink()

        return archive_path

    def cleanup_passed_logs(self, days: Optional[int] = None) -> list[Path]:
        """
        Clean up passed test logs older than specified days.

        This is optional and controlled by cleanup_passed config.
        Failed/error logs are always preserved.

        Args:
            days: Override cleanup_passed_days config. If None, uses config value.

        Returns:
            List of removed log paths
        """
        if not self.config.cleanup_passed:
            return []

        cleanup_days = days if days is not None else self.config.cleanup_passed_days
        cutoff_date = datetime.now() - timedelta(days=cleanup_days)
        removed_files = []

        for phase_dir_name in ["phase1", "phase2", "phase3"]:
            phase_dir = self.log_root / phase_dir_name
            if not phase_dir.exists():
                continue

            for log_file in phase_dir.glob("*.log"):
                # Check file modification time
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

                if mtime < cutoff_date:
                    # Check if it's a passed test
                    if self._is_passed_log(log_file):
                        log_file.unlink()
                        removed_files.append(log_file)

        return removed_files

    def _is_passed_log(self, log_file: Path) -> bool:
        """
        Check if a log file represents a passed test.

        Args:
            log_file: Path to the log file

        Returns:
            True if the test passed, False otherwise
        """
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
            return "status: PASSED" in content
        except Exception as e:
            logger.warning("Failed to read log file %s: %s", log_file, e)
            return False

    def parse_log_metadata(self, log_path: Path) -> Optional[dict]:
        """
        Parse metadata from a log file.

        Args:
            log_path: Path to the log file

        Returns:
            Dictionary with metadata fields, or None if parsing fails
        """
        if not log_path.exists():
            return None

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()

            metadata = {}
            in_metadata = False

            for line in content.split('\n'):
                if line == "=== TEST METADATA ===":
                    in_metadata = True
                    continue
                elif line == "=== END METADATA ===":
                    break
                elif in_metadata and ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()

            return metadata if metadata else None

        except Exception as e:
            logger.warning("Failed to parse log metadata from %s: %s", log_path, e)
            return None

    def parse_log_result(self, log_path: Path) -> Optional[dict]:
        """
        Parse result section from a log file.

        Args:
            log_path: Path to the log file

        Returns:
            Dictionary with result fields, or None if parsing fails
        """
        if not log_path.exists():
            return None

        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()

            result = {}
            in_result = False

            for line in content.split('\n'):
                if line == "=== TEST RESULT ===":
                    in_result = True
                    continue
                elif line == "=== END RESULT ===":
                    break
                elif in_result and ':' in line:
                    key, value = line.split(':', 1)
                    result[key.strip()] = value.strip()

            return result if result else None

        except Exception as e:
            logger.warning("Failed to parse log result from %s: %s", log_path, e)
            return None

    def list_logs_by_phase(self, phase: int) -> list[Path]:
        """
        List all log files in a phase directory.

        Args:
            phase: Phase number (1, 2, or 3)

        Returns:
            List of log file paths, sorted by name
        """
        phase_dir = self.log_root / f"phase{phase}"
        if not phase_dir.exists():
            return []

        logs = sorted(phase_dir.glob("*.log"))
        return logs

    def list_stalled_logs(self) -> list[Path]:
        """
        List all stalled log files.

        Returns:
            List of stalled log file paths, sorted by name
        """
        stalled_dir = self.log_root / "stalled"
        if not stalled_dir.exists():
            return []

        logs = sorted(stalled_dir.glob("*.log"))
        return logs

    def list_archived_logs(self) -> list[Path]:
        """
        List all archived (compressed) log files.

        Returns:
            List of archived .gz file paths, sorted by name
        """
        archive_dir = self.log_root / "archive"
        if not archive_dir.exists():
            return []

        logs = sorted(archive_dir.glob("*.gz"))
        return logs

    def get_log_stats(self) -> dict:
        """
        Get statistics about log files.

        Returns:
            Dictionary with counts and sizes for each directory
        """
        stats = {
            "phase1": {"count": 0, "size_bytes": 0},
            "phase2": {"count": 0, "size_bytes": 0},
            "phase3": {"count": 0, "size_bytes": 0},
            "stalled": {"count": 0, "size_bytes": 0},
            "archive": {"count": 0, "size_bytes": 0},
        }

        for phase_name in ["phase1", "phase2", "phase3", "stalled"]:
            phase_dir = self.log_root / phase_name
            if phase_dir.exists():
                logs = list(phase_dir.glob("*.log"))
                stats[phase_name]["count"] = len(logs)
                stats[phase_name]["size_bytes"] = sum(
                    f.stat().st_size for f in logs if f.is_file()
                )

        archive_dir = self.log_root / "archive"
        if archive_dir.exists():
            archives = list(archive_dir.glob("*.gz"))
            stats["archive"]["count"] = len(archives)
            stats["archive"]["size_bytes"] = sum(
                f.stat().st_size for f in archives if f.is_file()
            )

        return stats

    def write_batch_log(
        self,
        log_path: Path,
        batch_id: str,
        phase: int,
        started: str,
        test_ids: list[int],
        worker: int,
        gpu: str,
        pytest_output: str,
        results_summary: dict
    ) -> Path:
        """
        Write a batch test log.

        Similar to write_test_log but for batch execution.

        Args:
            log_path: Path to write the log file
            batch_id: Batch identifier (e.g., "batch_20260605_1030")
            phase: Phase number
            started: ISO format timestamp when batch started
            test_ids: List of test IDs in the batch
            worker: Worker ID
            gpu: GPU assignment (e.g., "0-1")
            pytest_output: Raw pytest output
            results_summary: Dict with passed, failed, error, timeout counts

        Returns:
            Path to the written log file
        """
        # Ensure parent directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Truncate output if needed
        pytest_output = self._truncate_output(pytest_output)

        # Build content
        content = [
            "=== BATCH METADATA ===",
            f"batch_id: {batch_id}",
            f"phase: {phase}",
            f"started: {started}",
            f"test_ids: {','.join(map(str, test_ids))}",
            f"test_count: {len(test_ids)}",
            f"worker: {worker}",
            f"gpu: {gpu}",
            "=== END METADATA ===",
            "",
            pytest_output,
            "",
            "=== BATCH RESULT ===",
            f"passed: {results_summary.get('passed', 0)}",
            f"failed: {results_summary.get('failed', 0)}",
            f"error: {results_summary.get('error', 0)}",
            f"timeout: {results_summary.get('timeout', 0)}",
            f"skipped: {results_summary.get('skipped', 0)}",
            "=== END RESULT ===",
            ""
        ]

        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))

        return log_path


def main():
    """CLI interface for log management."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage test execution logs")
    parser.add_argument(
        "--log-root",
        default="/gpfs/gcsp/M2.7_verify/vllm/ut_logs",
        help="Root directory for logs"
    )
    parser.add_argument(
        "--setup-dirs",
        action="store_true",
        help="Create log directories"
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Rotate old logs to archive"
    )
    parser.add_argument(
        "--rotate-days",
        type=int,
        default=30,
        help="Days threshold for rotation (default: 30)"
    )
    parser.add_argument(
        "--cleanup-passed",
        action="store_true",
        help="Clean up passed logs older than 7 days"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show log statistics"
    )

    args = parser.parse_args()

    config = LogConfig(
        log_root=args.log_root,
        archive_days=args.rotate_days,
        cleanup_passed=args.cleanup_passed
    )
    log_manager = LogManager(config=config)

    if args.setup_dirs:
        dirs = log_manager.setup_log_dirs()
        print("Created log directories:")
        for name, path in dirs.items():
            print(f"  {name}: {path}")

    if args.rotate:
        archived = log_manager.rotate_logs()
        print(f"Archived {len(archived)} log files")
        for path in archived:
            print(f"  {path}")

    if args.cleanup_passed:
        removed = log_manager.cleanup_passed_logs()
        print(f"Removed {len(removed)} passed log files")

    if args.stats:
        stats = log_manager.get_log_stats()
        print("\nLog Statistics:")
        for name, data in stats.items():
            size_mb = data["size_bytes"] / (1024 * 1024)
            print(f"  {name}: {data['count']} files, {size_mb:.2f} MB")

    if not any([args.setup_dirs, args.rotate, args.cleanup_passed, args.stats]):
        parser.print_help()


if __name__ == "__main__":
    main()