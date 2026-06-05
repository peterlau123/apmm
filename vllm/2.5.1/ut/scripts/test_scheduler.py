#!/usr/bin/env python3
"""
test_scheduler.py - Main controller for multi-phase test automation

Orchestrates:
- Phase 1: 13,165 tests from ut_test_list.txt
- Phase 2: 18,207 tests from ut_test_list_full.txt (diff from Phase 1)
- Phase 3: 34 error handling tests

Features:
- Parallel execution via asyncio
- Remote background execution on t_h20 server
- Disconnect recovery via execution_state.json
- HF model dependency detection

Usage:
    python test_scheduler.py --parallel 3 --phase 1
    python test_scheduler.py --resume
    python test_scheduler.py --status
    python test_scheduler.py --dry-run
"""

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Union

# Import existing modules
try:
    from log_manager import LogManager, TestLogMetadata, TestLogResult, LogConfig
    from issues_tracker import IssuesTracker, Issue, ErrorCategory
except ImportError:
    # Handle case when running standalone
    SCRIPT_DIR = Path(__file__).parent
    sys.path.insert(0, str(SCRIPT_DIR))
    from log_manager import LogManager, TestLogMetadata, TestLogResult, LogConfig
    from issues_tracker import IssuesTracker, Issue, ErrorCategory

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────────

@dataclass
class SchedulerConfig:
    """Configuration for test scheduler."""
    parallel_count: int = 3
    timeout_per_test: int = 120  # seconds
    hf_cache_path: str = "/gpfs/gcsp/M2.7_verify/hf_hub"
    reconnect_interval: int = 30  # seconds
    phase1_list: str = "ut_test_list.txt"
    phase2_list: str = "ut_test_list_full.txt"
    state_file: str = "execution_state.json"
    background_mode: bool = True
    log_poll_interval: int = 10  # seconds
    stop_on_error_count: int = 5  # Stop after N consecutive errors

    # Remote server settings
    remote_profile: str = "t_h20"
    container_name: str = "v0.13.0_torch2.5.1_compile"
    vllm_dir: str = "/gpfs/gcsp/M2.7_verify/vllm"
    ut_logs_dir: str = "/gpfs/gcsp/M2.7_verify/vllm/ut_logs"


# ── Phase Management ────────────────────────────────────────────────────────────

class Phase(Enum):
    """Execution phases."""
    PHASE1 = 1  # 13,165 tests from ut_test_list.txt
    PHASE2 = 2  # 18,207 tests from ut_test_list_full.txt (diff from Phase 1)
    PHASE3 = 3  # 34 error handling tests


@dataclass
class PhaseStatus:
    """Status for a single phase."""
    total: int = 0
    completed: int = 0
    passed: int = 0
    failed: int = 0
    error: int = 0
    timeout: int = 0
    skipped: int = 0
    last_test_id: int = 0
    remaining_tests: list[int] = field(default_factory=list)


@dataclass
class ExecutionState:
    """State for execution recovery after disconnect."""
    current_phase: int = 1
    phase1_status: PhaseStatus = field(default_factory=lambda: PhaseStatus(total=13165))
    phase2_status: PhaseStatus = field(default_factory=lambda: PhaseStatus(total=18207))
    phase3_status: PhaseStatus = field(default_factory=lambda: PhaseStatus(total=34))
    last_update: Optional[str] = None
    disconnect_count: int = 0
    remote_processes: list[dict] = field(default_factory=list)  # [{pid, test_id, started, log_file}]
    completed_batches: list[str] = field(default_factory=list)
    consecutive_errors: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "current_phase": self.current_phase,
            "phase1_status": {
                "total": self.phase1_status.total,
                "completed": self.phase1_status.completed,
                "last_test_id": self.phase1_status.last_test_id,
                "passed": self.phase1_status.passed,
                "failed": self.phase1_status.failed,
                "error": self.phase1_status.error,
                "timeout": self.phase1_status.timeout,
                "skipped": self.phase1_status.skipped,
            },
            "phase2_status": {
                "total": self.phase2_status.total,
                "completed": self.phase2_status.completed,
                "remaining_tests": self.phase2_status.remaining_tests,
            },
            "phase3_status": {
                "errors_fixed": self.phase3_status.completed,
                "errors_pending": self.phase3_status.remaining_tests,
            },
            "last_update": self.last_update,
            "disconnect_count": self.disconnect_count,
            "remote_processes": self.remote_processes,
            "completed_batches": self.completed_batches,
            "consecutive_errors": self.consecutive_errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionState":
        """Create from dictionary."""
        state = cls()
        state.current_phase = data.get("current_phase", 1)
        state.last_update = data.get("last_update")
        state.disconnect_count = data.get("disconnect_count", 0)
        state.remote_processes = data.get("remote_processes", [])
        state.completed_batches = data.get("completed_batches", [])
        state.consecutive_errors = data.get("consecutive_errors", 0)

        # Phase 1 status
        p1 = data.get("phase1_status", {})
        state.phase1_status = PhaseStatus(
            total=p1.get("total", 13165),
            completed=p1.get("completed", 0),
            last_test_id=p1.get("last_test_id", 0),
            passed=p1.get("passed", 0),
            failed=p1.get("failed", 0),
            error=p1.get("error", 0),
            timeout=p1.get("timeout", 0),
            skipped=p1.get("skipped", 0),
        )

        # Phase 2 status
        p2 = data.get("phase2_status", {})
        state.phase2_status = PhaseStatus(
            total=p2.get("total", 18207),
            completed=p2.get("completed", 0),
            remaining_tests=p2.get("remaining_tests", []),
        )

        # Phase 3 status
        p3 = data.get("phase3_status", {})
        # Handle both int and list for errors_pending
        errors_pending = p3.get("errors_pending", 34)
        if isinstance(errors_pending, list):
            pending_count = len(errors_pending)
        else:
            pending_count = int(errors_pending) if errors_pending else 34
        state.phase3_status = PhaseStatus(
            total=34,
            completed=p3.get("errors_fixed", 0),
            remaining_tests=list(range(pending_count)) if pending_count > 0 else [],
        )

        return state


class PhaseManager:
    """
    Manage multi-phase execution state.

    Phase 1: Run 13,165 tests from ut_test_list.txt
    Phase 2: Run 18,207 tests from ut_test_list_full.txt (diff from Phase 1)
    Phase 3: Handle 34 error tests from Phase 1/2
    """

    def __init__(self, config: SchedulerConfig, work_dir: Path):
        """
        Initialize PhaseManager.

        Args:
            config: SchedulerConfig object
            work_dir: Working directory (vllm/2.5.1/ut/)
        """
        self.config = config
        self.work_dir = work_dir
        self.state_file = work_dir / config.state_file
        self.state: Optional[ExecutionState] = None

        # Load test lists
        self.phase1_tests: list[str] = []
        self.phase2_tests: list[str] = []
        self._load_test_lists()

    def _load_test_lists(self) -> None:
        """Load test lists from files."""
        phase1_file = self.work_dir / self.config.phase1_list
        phase2_file = self.work_dir / self.config.phase2_list

        if phase1_file.exists():
            with open(phase1_file, "r", encoding="utf-8") as f:
                self.phase1_tests = [line.strip() for line in f if line.strip()]
            logger.info("Loaded %d tests for Phase 1 from %s", len(self.phase1_tests), phase1_file)
        else:
            logger.warning("Phase 1 test list not found: %s", phase1_file)

        if phase2_file.exists():
            with open(phase2_file, "r", encoding="utf-8") as f:
                self.phase2_tests = [line.strip() for line in f if line.strip()]
            logger.info("Loaded %d tests for Phase 2 from %s", len(self.phase2_tests), phase2_file)
        else:
            logger.warning("Phase 2 test list not found: %s", phase2_file)

    def load_state(self) -> ExecutionState:
        """
        Read execution_state.json.

        Returns:
            ExecutionState object
        """
        if not self.state_file.exists():
            logger.info("State file not found, creating new state")
            self.state = ExecutionState()
            self.save_state()
            return self.state

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.state = ExecutionState.from_dict(data)
            logger.info("Loaded state from %s: Phase %d, completed %d",
                       self.state_file, self.state.current_phase,
                       self.state.phase1_status.completed)
            return self.state
        except json.JSONDecodeError as e:
            logger.error("Failed to parse state file: %s", e)
            self.state = ExecutionState()
            return self.state

    def save_state(self) -> None:
        """Persist state after each batch."""
        if self.state is None:
            return

        self.state.last_update = datetime.now().isoformat()

        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)

        logger.debug("Saved state to %s", self.state_file)

    def get_current_phase(self) -> Phase:
        """Return current phase (1, 2, or 3)."""
        if self.state is None:
            self.load_state()
        return Phase(self.state.current_phase)

    def compute_remaining(self) -> list[str]:
        """
        Compute remaining tests for Phase 2.

        Phase 2 tests = full_list - phase1_list (tests not in Phase 1)

        Returns:
            List of test nodes not in Phase 1
        """
        phase1_set = set(self.phase1_tests)
        remaining = [t for t in self.phase2_tests if t not in phase1_set]
        logger.info("Computed %d remaining tests for Phase 2", len(remaining))
        return remaining

    def advance_phase(self) -> bool:
        """
        Move to next phase when current phase is complete.

        Returns:
            True if advanced, False if already at last phase
        """
        if self.state is None:
            self.load_state()

        current = self.state.current_phase

        if current >= 3:
            logger.info("Already at Phase 3, cannot advance")
            return False

        # Check if current phase is complete
        if current == 1:
            if self.state.phase1_status.completed < self.state.phase1_status.total:
                logger.warning("Phase 1 not complete: %d/%d",
                              self.state.phase1_status.completed,
                              self.state.phase1_status.total)
                return False
            # Compute Phase 2 remaining
            self.state.phase2_status.remaining_tests = [
                i for i, t in enumerate(self.phase2_tests)
                if t not in set(self.phase1_tests)
            ]
            self.state.phase2_status.total = len(self.state.phase2_status.remaining_tests)

        elif current == 2:
            if self.state.phase2_status.completed < self.state.phase2_status.total:
                logger.warning("Phase 2 not complete: %d/%d",
                              self.state.phase2_status.completed,
                              self.state.phase2_status.total)
                return False

        # Advance to next phase
        self.state.current_phase = current + 1
        self.state.consecutive_errors = 0
        self.save_state()

        logger.info("Advanced to Phase %d", self.state.current_phase)
        return True

    def resume_from_state(self) -> tuple[Phase, int]:
        """
        Quick recovery after disconnect.

        Returns:
            Tuple of (current_phase, last_test_id)
        """
        if self.state is None:
            self.load_state()

        phase = self.get_current_phase()
        if phase == Phase.PHASE1:
            last_id = self.state.phase1_status.last_test_id
        elif phase == Phase.PHASE2:
            # Resume from remaining tests
            if self.state.phase2_status.remaining_tests:
                last_id = self.state.phase2_status.remaining_tests[0]
            else:
                last_id = 0
        else:
            last_id = 0

        logger.info("Resuming from Phase %d, test ID %d", phase.value, last_id)
        return phase, last_id

    def update_phase_progress(
        self,
        test_id: int,
        status: str,
        passed: bool = False,
        is_error: bool = False
    ) -> None:
        """
        Update phase progress after a test completes.

        Args:
            test_id: Completed test ID
            status: Test status (passed, failed, error, timeout)
            passed: Whether test passed
            is_error: Whether this was an error (affects consecutive_errors)
        """
        if self.state is None:
            self.load_state()

        phase = self.get_current_phase()

        if phase == Phase.PHASE1:
            self.state.phase1_status.completed += 1
            self.state.phase1_status.last_test_id = test_id
            if status == "passed":
                self.state.phase1_status.passed += 1
                self.state.consecutive_errors = 0
            elif status == "failed":
                self.state.phase1_status.failed += 1
                self.state.consecutive_errors += 1
            elif status == "error":
                self.state.phase1_status.error += 1
                self.state.consecutive_errors += 1
            elif status == "timeout":
                self.state.phase1_status.timeout += 1
                self.state.consecutive_errors += 1
            elif status == "skipped":
                self.state.phase1_status.skipped += 1

        elif phase == Phase.PHASE2:
            self.state.phase2_status.completed += 1
            # Remove from remaining_tests
            if test_id in self.state.phase2_status.remaining_tests:
                self.state.phase2_status.remaining_tests.remove(test_id)
            if status == "passed":
                self.state.phase2_status.passed += 1
                self.state.consecutive_errors = 0
            else:
                self.state.consecutive_errors += 1

        self.save_state()

    def should_stop(self) -> bool:
        """
        Check if we should stop due to consecutive errors.

        Returns:
            True if consecutive errors exceed threshold
        """
        if self.state is None:
            self.load_state()
        return self.state.consecutive_errors >= self.config.stop_on_error_count


# ── HF Model Detector ────────────────────────────────────────────────────────────

class HFModelDetector:
    """
    Detect tests that depend on HuggingFace models.

    Checks if models are available in hf_cache_path and
    marks tests as model-dependent or not.
    """

    # Common model patterns in test files
    MODEL_PATTERNS = [
        r"meta-llama",
        r"RedHatAI",
        r"mistralai",
        r"Qwen",
        r"bert-base",
        r"gpt2",
        r"hf_hub",
        r"from_pretrained",
        r"AutoModel",
        r"AutoTokenizer",
    ]

    def __init__(self, config: SchedulerConfig):
        """
        Initialize HFModelDetector.

        Args:
            config: SchedulerConfig with hf_cache_path
        """
        self.config = config
        self.cache_path = Path(config.hf_cache_path)
        self._cached_models: Optional[set[str]] = None

    def check_model_cache(self) -> set[str]:
        """
        Check which models exist in hf_hub/ cache.

        Returns:
            Set of model names found in cache
        """
        if self._cached_models is not None:
            return self._cached_models

        models = set()

        # This needs to be checked via remote execution
        # For now, return empty set and rely on classification
        self._cached_models = models
        return models

    def classify_test(self, test_node: str, test_file: str = None) -> bool:
        """
        Mark test as model-dependent or not.

        Args:
            test_node: Full test node path (e.g., "tests/...::test_func")
            test_file: Optional test file path for more context

        Returns:
            True if test appears to depend on HF models
        """
        for pattern in self.MODEL_PATTERNS:
            if re.search(pattern, test_node, re.IGNORECASE):
                return True
        return False

    def skip_model_tests(self, tests: list[dict]) -> list[dict]:
        """
        Option to skip HF-dependent tests.

        Args:
            tests: List of test dicts from manifest

        Returns:
            List of tests without HF-dependent tests
        """
        return [t for t in tests if not self.classify_test(t.get("test_node", ""))]


# ── Remote Executor ──────────────────────────────────────────────────────────────

@dataclass
class RemoteProcess:
    """Remote process info."""
    pid: int
    test_id: int
    test_node: str
    started: str
    log_file: str
    worker: int
    status: str = "running"


class RemoteExecutor:
    """
    Execute tests on remote server via agent.py.

    Supports:
    - Background execution with nohup
    - Process status monitoring
    - Log growth monitoring
    - Timeout handling
    """

    # Remote command prefix for agent.py
    REMOTE_CMD_PREFIX_TEMPLATE = ["python", "agent.py", "-p", "{profile}", "run", "--timeout", "{timeout}"]

    def __init__(self, config: SchedulerConfig, agent_path: Path):
        """
        Initialize RemoteExecutor.

        Args:
            config: SchedulerConfig
            agent_path: Path to agent.py script
        """
        self.config = config
        self.agent_path = agent_path
        self.processes: dict[int, RemoteProcess] = {}  # test_id -> RemoteProcess

    def _build_remote_cmd(self, timeout: int = None) -> list[str]:
        """Build remote command prefix."""
        timeout = timeout or self.config.timeout_per_test + 60
        template = self.REMOTE_CMD_PREFIX_TEMPLATE.copy()
        return [
            template[0], template[1],
            "-p", self.config.remote_profile,
            template[4], "--timeout", str(timeout)
        ]

    def start_background_test(
        self,
        test_id: int,
        test_node: str,
        worker: int = 0,
        timeout: int = None
    ) -> RemoteProcess:
        """
        Start pytest process on remote server with nohup.

        Args:
            test_id: Test ID
            test_node: Full test node path
            worker: Worker ID for parallel execution
            timeout: Per-test timeout override

        Returns:
            RemoteProcess with PID and log file info
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"{self.config.ut_logs_dir}/{timestamp}_test_{test_id:04d}_worker{worker}.log"

        # Build pytest command
        pytest_cmd = (
            f"cd {self.config.vllm_dir} && "
            f"timeout {timeout or self.config.timeout_per_test} "
            f"pytest '{test_node}' -v --tb=short 2>&1 | tee {log_file}; "
            f"echo EXIT_CODE:$?"
        )

        # Wrap in container
        container_cmd = f"sudo docker exec {self.config.container_name} bash -c '{pytest_cmd}'"

        # Build full remote command
        remote_prefix = self._build_remote_cmd(timeout or self.config.timeout_per_test + 60)
        full_cmd = remote_prefix + [container_cmd]

        # For background mode, use nohup wrapper
        if self.config.background_mode:
            nohup_cmd = f"nohup bash -c '{container_cmd}' > /dev/null 2>&1 & echo $!"
            remote_prefix = self._build_remote_cmd(30)
            full_cmd = remote_prefix + [nohup_cmd]

        logger.info("Starting test %d: %s", test_id, test_node[:60])

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.agent_path.parent
            )

            started = datetime.now().isoformat()

            # Parse PID if background mode
            pid = 0
            if self.config.background_mode and result.stdout.strip().isdigit():
                pid = int(result.stdout.strip())

            process = RemoteProcess(
                pid=pid,
                test_id=test_id,
                test_node=test_node,
                started=started,
                log_file=log_file,
                worker=worker,
                status="running"
            )

            self.processes[test_id] = process
            logger.info("Started remote process: PID=%d, test_id=%d", pid, test_id)

            return process

        except subprocess.TimeoutExpired:
            logger.error("Timeout starting remote test %d", test_id)
            raise
        except Exception as e:
            logger.error("Failed to start remote test %d: %s", test_id, e)
            raise

    def check_process_status(self, test_id: int) -> str:
        """
        Check if remote process is still running.

        Args:
            test_id: Test ID to check

        Returns:
            Status: "running", "completed", "timeout", "error"
        """
        process = self.processes.get(test_id)
        if not process:
            return "unknown"

        if process.pid == 0:
            # Not background mode, already completed
            return process.status

        # Check process via remote command
        check_cmd = f"ps -p {process.pid} -o pid= 2>/dev/null || echo NOT_FOUND"
        remote_prefix = self._build_remote_cmd(30)
        full_cmd = remote_prefix + [check_cmd]

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.agent_path.parent
            )

            if "NOT_FOUND" in result.stdout or not result.stdout.strip():
                # Process finished
                process.status = "completed"
                return "completed"

            return "running"

        except Exception as e:
            logger.warning("Failed to check process status: %s", e)
            return "unknown"

    def monitor_log_growth(self, test_id: int) -> tuple[int, bool]:
        """
        Monitor log file growth to detect stalled tests.

        Args:
            test_id: Test ID to monitor

        Returns:
            Tuple of (current_size_bytes, is_growing)
        """
        process = self.processes.get(test_id)
        if not process:
            return (0, False)

        # Check log file size via remote command
        check_cmd = f"stat -c %s {process.log_file} 2>/dev/null || echo 0"
        remote_prefix = self._build_remote_cmd(30)
        full_cmd = remote_prefix + [check_cmd]

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.agent_path.parent
            )

            size = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0

            # Compare with previous size
            prev_size = getattr(process, "last_size", 0)
            is_growing = size > prev_size
            process.last_size = size

            return (size, is_growing)

        except Exception as e:
            logger.warning("Failed to monitor log: %s", e)
            return (0, False)

    def parse_completed_tests(self, log_file: str) -> tuple[str, int, Optional[str]]:
        """
        Parse pytest output from log file.

        Args:
            log_file: Remote log file path

        Returns:
            Tuple of (status, exit_code, error_message)
        """
        # Read log via remote command
        read_cmd = f"tail -100 {log_file}"
        remote_prefix = self._build_remote_cmd(30)
        full_cmd = remote_prefix + [read_cmd]

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.agent_path.parent
            )

            output = result.stdout

            # Parse exit code
            exit_code = 0
            if "EXIT_CODE:" in output:
                match = re.search(r"EXIT_CODE:(\d+)", output)
                if match:
                    exit_code = int(match.group(1))

            # Determine status
            if exit_code == 0:
                status = "passed"
                error_message = None
            elif exit_code == 124:
                status = "timeout"
                error_message = "Test exceeded timeout"
            elif exit_code == 1:
                status = "failed"
                error_message = self._extract_error_message(output)
            else:
                status = "error"
                error_message = self._extract_error_message(output)

            return (status, exit_code, error_message)

        except Exception as e:
            logger.warning("Failed to parse log: %s", e)
            return ("error", -1, str(e))

    def _extract_error_message(self, output: str) -> str:
        """Extract first meaningful error line from pytest output."""
        # Look for FAILED line
        failed_match = re.search(r"FAILED.*", output)
        if failed_match:
            return failed_match.group(0)[:100]

        # Look for Error: line
        error_match = re.search(r"(Error|Exception|AssertionError).*", output)
        if error_match:
            return error_match.group(0)[:100]

        return "Unknown error"

    def kill_stalled_process(self, test_id: int) -> bool:
        """
        Kill a stalled/timeout process on remote server.

        Args:
            test_id: Test ID to kill

        Returns:
            True if killed successfully
        """
        process = self.processes.get(test_id)
        if not process or process.pid == 0:
            return False

        # Kill process via remote command
        kill_cmd = f"kill -9 {process.pid} 2>/dev/null || echo NOT_FOUND"
        remote_prefix = self._build_remote_cmd(30)
        full_cmd = remote_prefix + [kill_cmd]

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.agent_path.parent
            )

            process.status = "killed"
            logger.info("Killed stalled process %d for test %d", process.pid, test_id)
            return True

        except Exception as e:
            logger.warning("Failed to kill process: %s", e)
            return False

    def record_pid(self, state: ExecutionState, test_id: int, pid: int, log_file: str) -> None:
        """
        Record process info to execution state for recovery.

        Args:
            state: ExecutionState to update
            test_id: Test ID
            pid: Remote process PID
            log_file: Log file path
        """
        state.remote_processes.append({
            "pid": pid,
            "test_id": test_id,
            "started": datetime.now().isoformat(),
            "log_file": log_file,
        })

    def wait_for_completion(self, test_id: int, timeout: int = None) -> tuple[str, int, Optional[str]]:
        """
        Wait for test to complete (polling).

        Args:
            test_id: Test ID
            timeout: Max wait time in seconds

        Returns:
            Tuple of (status, exit_code, error_message)
        """
        timeout = timeout or self.config.timeout_per_test + 60
        deadline = time.time() + timeout
        poll_interval = 5

        while time.time() < deadline:
            status = self.check_process_status(test_id)

            if status == "completed":
                process = self.processes.get(test_id)
                if process:
                    return self.parse_completed_tests(process.log_file)
                return ("error", -1, "Process info lost")

            if status == "unknown":
                # Check log growth
                size, is_growing = self.monitor_log_growth(test_id)
                if not is_growing and time.time() > deadline - 30:
                    # Log stopped growing, likely finished
                    process = self.processes.get(test_id)
                    if process:
                        return self.parse_completed_tests(process.log_file)

            time.sleep(poll_interval)

        # Timeout
        logger.warning("Test %d timed out after %ds", test_id, timeout)
        self.kill_stalled_process(test_id)
        return ("timeout", 124, "Test exceeded timeout")


# ── Main Scheduler ───────────────────────────────────────────────────────────────

class Scheduler:
    """
    Main controller for test automation.

    Orchestrates:
    - Multi-phase execution
    - Parallel test running
    - Remote execution via agent.py
    - State persistence and recovery
    """

    def __init__(self, config: SchedulerConfig, work_dir: Path):
        """
        Initialize Scheduler.

        Args:
            config: SchedulerConfig
            work_dir: Working directory (vllm/2.5.1/ut/)
        """
        self.config = config
        self.work_dir = work_dir
        self.manifest_file = work_dir / "test_manifest.json"

        # Initialize components
        self.phase_manager = PhaseManager(config, work_dir)
        self.hf_detector = HFModelDetector(config)
        self.remote_executor = RemoteExecutor(config, work_dir.parent.parent.parent / "agent.py")
        self.log_manager = LogManager(config.ut_logs_dir)
        self.issues_tracker = IssuesTracker(work_dir / "issues.json")

        # Manifest data
        self.manifest: Optional[dict] = None

    def load_manifest(self) -> dict:
        """
        Read test_manifest.json.

        Returns:
            Manifest dictionary
        """
        if not self.manifest_file.exists():
            raise FileNotFoundError(f"Manifest not found: {self.manifest_file}")

        with open(self.manifest_file, "r", encoding="utf-8") as f:
            self.manifest = json.load(f)

        logger.info("Loaded manifest: %d tests", self.manifest.get("total_tests", 0))
        return self.manifest

    def get_pending_tests(self, phase: Phase, start_id: int = 0) -> list[dict]:
        """
        Filter pending tests by phase and category.

        Args:
            phase: Current phase
            start_id: Starting test ID

        Returns:
            List of pending test dicts
        """
        if self.manifest is None:
            self.load_manifest()

        tests = self.manifest.get("tests", [])

        # Filter by phase
        if phase == Phase.PHASE1:
            # Tests from ut_test_list.txt
            pending = [
                t for t in tests
                if t["status"] == "pending" and t["id"] >= start_id
            ]
        elif phase == Phase.PHASE2:
            # Tests from ut_test_list_full.txt not in Phase 1
            phase1_tests = set(self.phase_manager.phase1_tests)
            pending = [
                t for t in tests
                if t["status"] == "pending"
                and t["test_node"] not in phase1_tests
            ]
        else:
            # Phase 3: Error tests
            pending = [
                t for t in tests
                if t["status"] in ("failed", "error", "timeout")
            ]

        # Skip HF-dependent tests if configured
        # (handled in schedule_batch)

        logger.info("Found %d pending tests for Phase %d", len(pending), phase.value)
        return pending

    def schedule_batch(self, tests: list[dict], batch_size: int = None) -> list[dict]:
        """
        Select N tests to run in parallel.

        Args:
            tests: List of pending tests
            batch_size: Number of tests (default: parallel_count)

        Returns:
            List of selected tests for batch
        """
        batch_size = batch_size or self.config.parallel_count

        # Skip HF-dependent tests if requested
        if hasattr(self, "_skip_model_tests"):
            tests = self.hf_detector.skip_model_tests(tests)

        # Select next batch
        batch = tests[:batch_size]

        logger.info("Scheduled batch: %d tests (IDs: %s)",
                   len(batch),
                   [t["id"] for t in batch])

        return batch

    async def execute_parallel(self, batch: list[dict]) -> list[dict]:
        """
        Run tests concurrently via asyncio.

        Args:
            batch: List of tests to run

        Returns:
            List of result dicts
        """
        tasks = []

        for i, test in enumerate(batch):
            # Assign worker ID
            worker = i % self.config.parallel_count

            # Create async task
            task = asyncio.create_task(
                self._run_single_test(test, worker)
            )
            tasks.append(task)

        # Wait for all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "test_id": batch[i]["id"],
                    "status": "error",
                    "exit_code": -1,
                    "error_message": str(result),
                })
            else:
                processed_results.append(result)

        return processed_results

    async def _run_single_test(self, test: dict, worker: int) -> dict:
        """
        Run a single test on remote server.

        Args:
            test: Test dict from manifest
            worker: Worker ID

        Returns:
            Result dict with status, exit_code, duration_ms, error_message
        """
        test_id = test["id"]
        test_node = test["test_node"]

        start_time = datetime.now()

        try:
            # Start remote test
            process = self.remote_executor.start_background_test(
                test_id=test_id,
                test_node=test_node,
                worker=worker,
                timeout=self.config.timeout_per_test
            )

            # Wait for completion
            status, exit_code, error_message = self.remote_executor.wait_for_completion(
                test_id=test_id,
                timeout=self.config.timeout_per_test + 60
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return {
                "test_id": test_id,
                "test_node": test_node,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "error_message": error_message,
                "log_file": process.log_file,
                "worker": worker,
            }

        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.error("Test %d failed: %s", test_id, e)
            return {
                "test_id": test_id,
                "test_node": test_node,
                "status": "error",
                "exit_code": -1,
                "duration_ms": duration_ms,
                "error_message": str(e),
            }

    def handle_results(self, results: list[dict]) -> None:
        """
        Parse pytest output, update manifest and state.

        Args:
            results: List of result dicts from execute_parallel
        """
        if self.manifest is None:
            self.load_manifest()

        for result in results:
            test_id = result["test_id"]

            # Update manifest
            for test in self.manifest["tests"]:
                if test["id"] == test_id:
                    test["status"] = result["status"]
                    test["run_at"] = datetime.now().isoformat()
                    test["duration_ms"] = result.get("duration_ms")
                    test["exit_code"] = result.get("exit_code")
                    test["error_type"] = self._classify_error(result)
                    test["error_message"] = result.get("error_message")
                    test["log_file"] = result.get("log_file")
                    break

            # Update phase progress
            self.phase_manager.update_phase_progress(
                test_id=test_id,
                status=result["status"],
                passed=result["status"] == "passed",
                is_error=result["status"] in ("failed", "error", "timeout")
            )

            # Track issues
            if result["status"] != "passed":
                self._track_issue(result)

        # Update manifest statistics
        self._update_manifest_stats()

        # Save manifest
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)

        logger.info("Updated manifest for %d tests", len(results))

    def _classify_error(self, result: dict) -> Optional[str]:
        """Classify error type for manifest."""
        if result["status"] == "passed":
            return None

        error_message = result.get("error_message", "")
        code, category = self.issues_tracker.categorize_error(error_message)
        return code

    def _track_issue(self, result: dict) -> None:
        """Add issue to issues tracker."""
        error_message = result.get("error_message", "Unknown error")
        code, category = self.issues_tracker.categorize_error(error_message)

        self.issues_tracker.add_issue(
            category=category,
            description=error_message[:80],
            test_id=str(result["test_id"]),
            notes=f"Test node: {result.get('test_node', 'unknown')}"
        )

    def _update_manifest_stats(self) -> None:
        """Update statistics in manifest."""
        tests = self.manifest.get("tests", [])

        stats = {
            "pending": sum(1 for t in tests if t["status"] == "pending"),
            "passed": sum(1 for t in tests if t["status"] == "passed"),
            "failed": sum(1 for t in tests if t["status"] == "failed"),
            "error": sum(1 for t in tests if t["status"] == "error"),
            "timeout": sum(1 for t in tests if t["status"] == "timeout"),
            "skipped": sum(1 for t in tests if t["status"] == "skipped"),
        }

        self.manifest["statistics"] = stats

    def auto_reconnect(self) -> bool:
        """
        Check agent.py health, reconnect if needed.

        Returns:
            True if connection is healthy
        """
        # Ping agent.py daemon
        ping_cmd = ["python", "agent.py", "-p", self.config.remote_profile, "ping"]

        try:
            result = subprocess.run(
                ping_cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.work_dir.parent.parent.parent
            )

            if "[OK]" in result.stdout:
                logger.info("Agent connection healthy")
                return True

            logger.warning("Agent connection failed: %s", result.stdout)
            return False

        except Exception as e:
            logger.error("Agent ping failed: %s", e)
            return False

    def run_batch(self, dry_run: bool = False) -> dict:
        """
        Run one batch of tests.

        Args:
            dry_run: If True, only show what would run

        Returns:
            Summary dict with batch results
        """
        # Load state
        state = self.phase_manager.load_state()
        phase, start_id = self.phase_manager.resume_from_state()

        # Check if should stop
        if self.phase_manager.should_stop():
            logger.warning("Stopping due to %d consecutive errors",
                          state.consecutive_errors)
            return {"status": "stopped", "reason": "consecutive_errors"}

        # Get pending tests
        pending_tests = self.get_pending_tests(phase, start_id)

        if not pending_tests:
            logger.info("No pending tests in Phase %d", phase.value)
            # Try to advance phase
            if self.phase_manager.advance_phase():
                return self.run_batch(dry_run)
            return {"status": "complete", "phase": phase.value}

        # Schedule batch
        batch = self.schedule_batch(pending_tests)

        if dry_run:
            logger.info("Dry run: would execute %d tests", len(batch))
            return {
                "status": "dry_run",
                "tests": [t["test_node"][:60] for t in batch],
                "test_ids": [t["id"] for t in batch],
            }

        # Execute batch
        logger.info("Executing batch: %d tests", len(batch))
        results = asyncio.run(self.execute_parallel(batch))

        # Handle results
        self.handle_results(results)

        # Generate summary
        passed = sum(1 for r in results if r["status"] == "passed")
        failed = sum(1 for r in results if r["status"] == "failed")
        error = sum(1 for r in results if r["status"] == "error")
        timeout = sum(1 for r in results if r["status"] == "timeout")

        return {
            "status": "completed",
            "phase": phase.value,
            "batch_size": len(batch),
            "passed": passed,
            "failed": failed,
            "error": error,
            "timeout": timeout,
        }

    def show_status(self) -> str:
        """
        Show current execution status.

        Returns:
            Status string for display
        """
        state = self.phase_manager.load_state()
        phase = self.phase_manager.get_current_phase()

        lines = [
            "=" * 60,
            "TEST SCHEDULER STATUS",
            "=" * 60,
            f"Current Phase: {phase.value}",
            f"Last Update: {state.last_update or 'N/A'}",
            f"Disconnect Count: {state.disconnect_count}",
            f"Consecutive Errors: {state.consecutive_errors}",
            "",
            "Phase 1 Progress:",
            f"  Total: {state.phase1_status.total}",
            f"  Completed: {state.phase1_status.completed}",
            f"  Last Test ID: {state.phase1_status.last_test_id}",
            f"  Passed: {state.phase1_status.passed}",
            f"  Failed: {state.phase1_status.failed}",
            f"  Error: {state.phase1_status.error}",
            f"  Timeout: {state.phase1_status.timeout}",
            "",
            "Phase 2 Progress:",
            f"  Total: {state.phase2_status.total}",
            f"  Completed: {state.phase2_status.completed}",
            f"  Remaining: {len(state.phase2_status.remaining_tests)}",
            "",
            "Phase 3 Progress:",
            f"  Errors Fixed: {state.phase3_status.completed}",
            f"  Errors Pending: {len(state.phase3_status.remaining_tests)}",
            "",
            f"Remote Processes: {len(state.remote_processes)}",
            "=" * 60,
        ]

        return "\n".join(lines)


# ── CLI Interface ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Test scheduler for multi-phase test automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python test_scheduler.py --parallel 3 --phase 1
    python test_scheduler.py --resume
    python test_scheduler.py --status
    python test_scheduler.py --dry-run --parallel 5
    python test_scheduler.py --stop-on-error 3
        """
    )

    parser.add_argument(
        "--parallel", "-p",
        type=int,
        default=3,
        help="Number of parallel workers (default: 3)"
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3],
        help="Start specific phase (1, 2, or 3)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last state"
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=0,
        help="Start from specific test ID"
    )
    parser.add_argument(
        "--skip-model-tests",
        action="store_true",
        help="Skip all model-dependent tests"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-test timeout in seconds (default: 120)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing"
    )
    parser.add_argument(
        "--stop-on-error",
        type=int,
        default=5,
        help="Stop after N consecutive errors (default: 5)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status"
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=1,
        help="Maximum batches to run (default: 1)"
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help="Working directory (default: vllm/2.5.1/ut/)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    return parser


def main():
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Determine work directory
    script_dir = Path(__file__).parent
    if args.work_dir:
        work_dir = Path(args.work_dir)
    else:
        work_dir = script_dir.parent  # vllm/2.5.1/ut/

    # Create config
    config = SchedulerConfig(
        parallel_count=args.parallel,
        timeout_per_test=args.timeout,
        stop_on_error_count=args.stop_on_error,
    )

    # Create scheduler
    scheduler = Scheduler(config, work_dir)

    # Handle skip model tests
    if args.skip_model_tests:
        scheduler._skip_model_tests = True
        logger.info("Skipping HF model-dependent tests")

    # Status check
    if args.status:
        print(scheduler.show_status())
        return

    # Load state for resume or phase selection
    if args.resume:
        phase, start_id = scheduler.phase_manager.resume_from_state()
        logger.info("Resuming: Phase %d, start_id %d", phase.value, start_id)
    elif args.phase:
        scheduler.phase_manager.state = ExecutionState()
        scheduler.phase_manager.state.current_phase = args.phase
        scheduler.phase_manager.save_state()
        logger.info("Starting Phase %d", args.phase)
    else:
        scheduler.phase_manager.load_state()

    # Override start_id if provided
    if args.start_id > 0:
        state = scheduler.phase_manager.state
        if state.current_phase == 1:
            state.phase1_status.last_test_id = args.start_id - 1
        scheduler.phase_manager.save_state()

    # Run batches
    for batch_num in range(args.max_batches):
        result = scheduler.run_batch(dry_run=args.dry_run)

        if result["status"] == "complete":
            print("All tests completed!")
            break
        elif result["status"] == "stopped":
            print(f"Stopped: {result['reason']}")
            break
        elif result["status"] == "dry_run":
            print(f"Dry run batch {batch_num + 1}:")
            for test_node in result["tests"]:
                print(f"  {test_node}")
            print(f"Test IDs: {result['test_ids']}")
            break
        else:
            print(f"Batch {batch_num + 1}: {result}")


if __name__ == "__main__":
    main()