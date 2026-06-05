#!/usr/bin/env python3
"""
state_manager.py - Manage execution_state.json and issues.json

Provides functions for:
- Loading/saving state files
- Initializing state structure
- Updating phase progress
- Managing remote process tracking
- Issue management

Usage:
    from state_manager import StateManager

    sm = StateManager()
    state = sm.load_state()
    sm.update_phase_progress(state, 1, 42)
    sm.save_state(state)
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path


# Default paths (relative to this script's location)
SCRIPT_DIR = Path(__file__).parent
DEFAULT_STATE_FILE = SCRIPT_DIR / "execution_state.json"
DEFAULT_ISSUES_FILE = SCRIPT_DIR / "issues.json"


class StateManager:
    """Manages execution_state.json for phase tracking and resume."""

    def __init__(self, state_file: Optional[Path] = None, issues_file: Optional[Path] = None):
        self.state_file = state_file or DEFAULT_STATE_FILE
        self.issues_file = issues_file or DEFAULT_ISSUES_FILE

    def load_state(self) -> Dict[str, Any]:
        """
        Read execution_state.json.

        Returns state dict with all phase progress info.
        Creates initial state if file doesn't exist.
        """
        if not self.state_file.exists():
            return self.init_state()

        with open(self.state_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_state(self, state: Dict[str, Any]) -> None:
        """
        Write execution_state.json.

        Updates last_update timestamp automatically.
        """
        state["last_update"] = datetime.now().isoformat()

        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def init_state(self) -> Dict[str, Any]:
        """
        Create initial state structure.

        Returns fresh state dict with zero progress.
        """
        return {
            "current_phase": 1,
            "phase1_status": {
                "total": 13165,
                "completed": 0,
                "last_test_id": 0,
                "manifest_file": "test_manifest.json"
            },
            "phase2_status": {
                "total": 18207,
                "completed": 0,
                "remaining_tests": [],
                "manifest_file": "test_manifest_phase2.json"
            },
            "phase3_status": {
                "errors_fixed": 0,
                "errors_pending": 34,
                "collection_errors": []
            },
            "last_update": datetime.now().isoformat(),
            "disconnect_count": 0,
            "remote_processes": [],
            "completed_batches": [],
            "config": {
                "parallel_workers": 3,
                "timeout_per_test": 120,
                "log_poll_interval": 10,
                "batch_size": 100,
                "background_mode": True
            }
        }

    def get_current_phase(self, state: Dict[str, Any]) -> int:
        """
        Return current phase number (1, 2, or 3).
        """
        return state.get("current_phase", 1)

    def update_phase_progress(self, state: Dict[str, Any], phase: int, test_id: int,
                               increment: int = 1) -> None:
        """
        Update progress after test completion.

        Args:
            state: Current state dict
            phase: Phase number (1, 2, or 3)
            test_id: Last completed test ID
            increment: Number of tests completed (default 1)
        """
        if phase == 1:
            phase_status = state["phase1_status"]
            phase_status["completed"] += increment
            phase_status["last_test_id"] = test_id
        elif phase == 2:
            phase_status = state["phase2_status"]
            phase_status["completed"] += increment
        elif phase == 3:
            # Phase 3 tracks errors, not test IDs
            pass
        else:
            raise ValueError(f"Invalid phase: {phase}")

    def add_remote_process(self, state: Dict[str, Any], batch_info: Dict[str, Any]) -> None:
        """
        Record new background process.

        Args:
            state: Current state dict
            batch_info: Dict with keys:
                - batch_id: Unique batch identifier
                - pid: Process ID on remote server
                - test_range: Test ID range (e.g., "4200-4210")
                - started_at: ISO timestamp
                - log_file: Remote log file path
                - status: "running"
                - expected_tests: Number of tests in batch
        """
        state["remote_processes"].append(batch_info)

    def remove_remote_process(self, state: Dict[str, Any], batch_id: str,
                              results: Optional[Dict[str, int]] = None) -> None:
        """
        Remove completed process and record in completed_batches.

        Args:
            state: Current state dict
            batch_id: Batch identifier to remove
            results: Optional results dict (passed, failed, error counts)
        """
        # Find and remove from remote_processes
        processes = state["remote_processes"]
        removed = None
        for i, proc in enumerate(processes):
            if proc["batch_id"] == batch_id:
                removed = processes.pop(i)
                break

        if removed:
            # Add to completed_batches
            completed_info = {
                "batch_id": batch_id,
                "completed_at": datetime.now().isoformat(),
                "results": results or {},
                "test_range": removed.get("test_range", ""),
                "started_at": removed.get("started_at", "")
            }
            state["completed_batches"].append(completed_info)

    def get_running_processes(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Return list of currently running remote processes.
        """
        return state.get("remote_processes", [])

    def advance_phase(self, state: Dict[str, Any]) -> int:
        """
        Move to next phase when current phase complete.

        Returns new phase number.
        """
        current = state["current_phase"]
        if current < 3:
            state["current_phase"] = current + 1
            return current + 1
        return current

    def increment_disconnect_count(self, state: Dict[str, Any]) -> int:
        """
        Increment disconnect counter.

        Returns new disconnect count.
        """
        state["disconnect_count"] = state.get("disconnect_count", 0) + 1
        return state["disconnect_count"]

    def is_phase_complete(self, state: Dict[str, Any], phase: int) -> bool:
        """
        Check if phase is complete.
        """
        if phase == 1:
            return state["phase1_status"]["completed"] >= state["phase1_status"]["total"]
        elif phase == 2:
            return state["phase2_status"]["completed"] >= state["phase2_status"]["total"]
        elif phase == 3:
            return state["phase3_status"]["errors_pending"] == 0
        return False

    def get_phase_summary(self, state: Dict[str, Any], phase: int) -> Dict[str, Any]:
        """
        Get summary info for a specific phase.
        """
        if phase == 1:
            ps = state["phase1_status"]
            return {
                "phase": 1,
                "total": ps["total"],
                "completed": ps["completed"],
                "remaining": ps["total"] - ps["completed"],
                "progress_pct": (ps["completed"] / ps["total"] * 100) if ps["total"] > 0 else 0,
                "last_test_id": ps["last_test_id"]
            }
        elif phase == 2:
            ps = state["phase2_status"]
            return {
                "phase": 2,
                "total": ps["total"],
                "completed": ps["completed"],
                "remaining": ps["total"] - ps["completed"],
                "progress_pct": (ps["completed"] / ps["total"] * 100) if ps["total"] > 0 else 0
            }
        elif phase == 3:
            ps = state["phase3_status"]
            return {
                "phase": 3,
                "errors_fixed": ps["errors_fixed"],
                "errors_pending": ps["errors_pending"]
            }
        return {}


class IssuesManager:
    """Manages issues.json for issue tracking."""

    # Issue categories
    CATEGORIES = [
        "C-代码Bug",    # vLLM code defects
        "E-环境问题",   # Environment limits
        "D-依赖缺失",   # Missing dependencies
        "P-平台兼容",   # PyTorch API compatibility
        "M-模型缺失",   # HF models not downloaded
        "S-跳过问题"    # Reasonably skipped tests
    ]

    def __init__(self, issues_file: Optional[Path] = None):
        self.issues_file = issues_file or DEFAULT_ISSUES_FILE
        self._next_id_cache = {}  # category -> next number

    def load_issues(self) -> Dict[str, Any]:
        """
        Read issues.json.

        Returns issues dict with all tracked issues.
        Creates initial structure if file doesn't exist.
        """
        if not self.issues_file.exists():
            return self.init_issues()

        with open(self.issues_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_issues(self, issues: Dict[str, Any]) -> None:
        """
        Write issues.json.

        Updates statistics and metadata automatically.
        """
        # Update metadata
        if "metadata" not in issues:
            issues["metadata"] = {}
        issues["metadata"]["last_updated"] = datetime.now().isoformat()

        # Recalculate statistics
        issues["statistics"] = self._calculate_statistics(issues["issues"])

        with open(self.issues_file, "w", encoding="utf-8") as f:
            json.dump(issues, f, indent=2, ensure_ascii=False)

    def init_issues(self) -> Dict[str, Any]:
        """
        Create initial issues structure.
        """
        return {
            "issues": [],
            "statistics": {
                "total_issues": 0,
                "open": 0,
                "known": 0,
                "fixed": 0,
                "by_category": {cat: 0 for cat in self.CATEGORIES}
            },
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "version": "1.0"
            }
        }

    def add_issue(self, issues: Dict[str, Any], category: str, description: str,
                  affected_tests: Any, status: str = "open",
                  notes: Optional[str] = None) -> str:
        """
        Add new issue from test failure.

        Args:
            issues: Current issues dict
            category: One of C/E/D/P/M/S categories
            description: Brief description
            affected_tests: Test ID or list of test IDs
            status: "open", "known", or "fixed"
            notes: Additional context

        Returns:
            Issue ID (e.g., "C-1")
        """
        if category not in self.CATEGORIES:
            raise ValueError(f"Invalid category: {category}. Must be one of {self.CATEGORIES}")

        # Generate unique ID
        issue_id = self._generate_issue_id(issues, category)

        today = datetime.now().strftime("%Y-%m-%d")

        # Normalize affected_tests to list
        if isinstance(affected_tests, int):
            affected_tests = [affected_tests]
        elif isinstance(affected_tests, str):
            affected_tests = [affected_tests]

        issue = {
            "id": issue_id,
            "category": category,
            "description": description,
            "affected_tests": affected_tests,
            "status": status,
            "first_seen": today,
            "last_seen": today,
            "fix_commit": None,
            "notes": notes
        }

        issues["issues"].append(issue)
        return issue_id

    def update_issue(self, issues: Dict[str, Any], issue_id: str,
                     status: Optional[str] = None,
                     fix_commit: Optional[str] = None,
                     notes: Optional[str] = None,
                     add_affected_tests: Optional[List] = None) -> bool:
        """
        Update existing issue status.

        Args:
            issues: Current issues dict
            issue_id: Issue identifier (e.g., "C-1")
            status: New status (optional)
            fix_commit: Git commit hash if fixed (optional)
            notes: Additional notes (optional)
            add_affected_tests: Additional test IDs to add (optional)

        Returns:
            True if issue found and updated, False otherwise
        """
        for issue in issues["issues"]:
            if issue["id"] == issue_id:
                if status:
                    issue["status"] = status
                if fix_commit:
                    issue["fix_commit"] = fix_commit
                if notes:
                    issue["notes"] = notes
                if add_affected_tests:
                    existing = set(issue["affected_tests"])
                    issue["affected_tests"] = list(existing | set(add_affected_tests))
                issue["last_seen"] = datetime.now().strftime("%Y-%m-%d")
                return True
        return False

    def find_issue_by_description(self, issues: Dict[str, Any],
                                   description: str) -> Optional[Dict[str, Any]]:
        """
        Find existing issue by description (exact match).
        """
        for issue in issues["issues"]:
            if issue["description"] == description:
                return issue
        return None

    def categorize_error(self, error_message: str, error_type: str) -> str:
        """
        Classify error type to category.

        Args:
            error_message: Full error message/traceback
            error_type: Error type from pytest (failed, error)

        Returns:
            Category string (C-代码Bug, etc.)
        """
        error_lower = error_message.lower()

        # Detection patterns
        if "wrap_triton" in error_message or "triton" in error_lower:
            return "P-平台兼容"
        if "fp32_precision" in error_message or "abi" in error_lower:
            return "P-平台兼容"

        if "importerror" in error_lower or "modulenotfounderror" in error_lower:
            return "D-依赖缺失"

        if "localentrynotfounderror" in error_lower or "config.json" in error_lower:
            return "M-模型缺失"
        if "huggingface" in error_lower or "hf_hub" in error_lower:
            return "M-模型缺失"

        if "oserror" in error_lower or "filenotfounderror" in error_lower:
            return "E-环境问题"
        if "quota" in error_lower or "permission" in error_lower:
            return "E-环境问题"

        if "skip" in error_lower or error_type == "skipped":
            return "S-跳过问题"

        if "assertionerror" in error_lower or "assertion" in error_lower:
            return "C-代码Bug"
        if "typeerror" in error_lower or "valueerror" in error_lower:
            # Could be code bug or environment, default to code bug
            return "C-代码Bug"

        # Default: code bug for failed, environment for error
        if error_type == "failed":
            return "C-代码Bug"
        return "E-环境问题"

    def get_issue_stats(self, issues: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return issue statistics.
        """
        return issues.get("statistics", self._calculate_statistics(issues.get("issues", [])))

    def _generate_issue_id(self, issues: Dict[str, Any], category: str) -> str:
        """
        Generate unique issue ID for category.
        """
        # Get category prefix (first letter before dash)
        prefix = category.split("-")[0]

        # Find highest existing number for this category
        existing_nums = []
        for issue in issues.get("issues", []):
            if issue["category"] == category:
                try:
                    num = int(issue["id"].split("-")[1])
                    existing_nums.append(num)
                except (IndexError, ValueError):
                    pass

        next_num = max(existing_nums, default=0) + 1
        return f"{prefix}-{next_num}"

    def _calculate_statistics(self, issues_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate statistics from issues list.
        """
        stats = {
            "total_issues": len(issues_list),
            "open": 0,
            "known": 0,
            "fixed": 0,
            "by_category": {cat: 0 for cat in self.CATEGORIES}
        }

        for issue in issues_list:
            status = issue.get("status", "open")
            category = issue.get("category", "")

            if status == "open":
                stats["open"] += 1
            elif status == "known":
                stats["known"] += 1
            elif status == "fixed":
                stats["fixed"] += 1

            if category in stats["by_category"]:
                stats["by_category"][category] += 1

        return stats


# Convenience functions for direct use
def load_state(filepath: Optional[Path] = None) -> Dict[str, Any]:
    """Read JSON state file."""
    sm = StateManager(filepath)
    return sm.load_state()


def save_state(filepath: Optional[Path] = None, state: Dict[str, Any] = None) -> None:
    """Write JSON state file."""
    sm = StateManager(filepath)
    sm.save_state(state)


def init_state() -> Dict[str, Any]:
    """Create initial state structure."""
    sm = StateManager()
    return sm.init_state()


def update_phase_progress(state: Dict[str, Any], phase: int, test_id: int,
                          increment: int = 1) -> None:
    """Update progress after test completion."""
    sm = StateManager()
    sm.update_phase_progress(state, phase, test_id, increment)


def add_remote_process(state: Dict[str, Any], batch_info: Dict[str, Any]) -> None:
    """Record new background process."""
    sm = StateManager()
    sm.add_remote_process(state, batch_info)


def remove_remote_process(state: Dict[str, Any], batch_id: str,
                          results: Optional[Dict[str, int]] = None) -> None:
    """Remove completed process."""
    sm = StateManager()
    sm.remove_remote_process(state, batch_id, results)


def get_current_phase(state: Dict[str, Any]) -> int:
    """Return current phase number."""
    return state.get("current_phase", 1)


if __name__ == "__main__":
    # Demo usage
    print("State Manager Demo")
    print("=" * 50)

    # Initialize state
    sm = StateManager()
    state = sm.init_state()
    print(f"Initial state: Phase {sm.get_current_phase(state)}")

    # Simulate progress
    sm.update_phase_progress(state, 1, 100, increment=10)
    print(f"Phase 1 progress: {state['phase1_status']['completed']}/{state['phase1_status']['total']}")

    # Add remote process
    batch_info = {
        "batch_id": "batch_20260605_1030",
        "pid": 12345,
        "test_range": "100-110",
        "started_at": datetime.now().isoformat(),
        "log_file": "ut_logs/phase1/batch_20260605_1030.log",
        "status": "running",
        "expected_tests": 10
    }
    sm.add_remote_process(state, batch_info)
    print(f"Remote processes: {len(state['remote_processes'])}")

    # Complete batch
    sm.remove_remote_process(state, "batch_20260605_1030", {"passed": 8, "failed": 2})
    print(f"Completed batches: {len(state['completed_batches'])}")

    # Issues demo
    im = IssuesManager()
    issues = im.init_issues()

    # Add some issues
    issue_id = im.add_issue(issues, "P-平台兼容", "Triton编译器版本不兼容", [1, 2, 3])
    print(f"Added issue: {issue_id}")

    issue_id2 = im.add_issue(issues, "C-代码Bug", "fp8 OOM", [4, 5, 6], notes="GPU显存不足")
    print(f"Added issue: {issue_id2}")

    # Get stats
    stats = im.get_issue_stats(issues)
    print(f"Statistics: {stats}")

    # Categorize an error
    category = im.categorize_error("ImportError: wrap_triton not found", "error")
    print(f"Categorized error: {category}")