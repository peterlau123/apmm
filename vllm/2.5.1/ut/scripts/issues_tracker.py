#!/usr/bin/env python3
"""
issues_tracker.py - Track and categorize test issues for vLLM unit test automation

Manages issue categorization, tracking, and reporting for test failures.
Integrates with issues.json for persistent storage and PROGRESS.md for reporting.

Usage:
    from issues_tracker import IssuesTracker, Issue, ErrorCategory

    tracker = IssuesTracker("/path/to/issues.json")

    # Categorize an error
    category = tracker.categorize_error(error_message, traceback)

    # Add a new issue
    issue_id = tracker.add_issue(
        category="C-代码Bug",
        description="fp8 OOM",
        affected_tests=["test_cache.py::test_fp8"],
        notes="GPU memory issue"
    )

    # Generate report for PROGRESS.md
    report = tracker.generate_report()
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Error categories for test failures."""
    CODE_BUG = "C-代码Bug"
    ENVIRONMENT = "E-环境问题"
    DEPENDENCY = "D-依赖缺失"
    PLATFORM = "P-平台兼容"
    MODEL_MISSING = "M-模型缺失"
    SKIP = "S-跳过问题"


@dataclass
class Issue:
    """
    Represents a tracked issue.

    Schema matches issues.json structure:
        - id: Unique issue identifier (e.g., P-1, C-1)
        - category: One of: P-平台兼容, C-代码Bug, E-环境问题, D-依赖缺失, M-模型缺失, S-跳过问题
        - description: Short description of the issue
        - affected_tests: List of affected test IDs
        - status: One of: open, known, fixed
        - first_seen: ISO date when first detected
        - last_seen: ISO date when last seen
        - fix_commit: Commit hash that fixed the issue (null if open)
        - notes: Additional notes (null if none)
    """
    id: str
    category: str
    description: str
    affected_tests: list[str] = field(default_factory=list)
    status: str = "open"
    first_seen: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    last_seen: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    fix_commit: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert Issue to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "category": self.category,
            "description": self.description,
            "affected_tests": self.affected_tests,
            "status": self.status,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "fix_commit": self.fix_commit,
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Issue":
        """Create Issue from dictionary."""
        return cls(
            id=data["id"],
            category=data["category"],
            description=data["description"],
            affected_tests=data.get("affected_tests", []),
            status=data.get("status", "open"),
            first_seen=data.get("first_seen", datetime.now().strftime("%Y-%m-%d")),
            last_seen=data.get("last_seen", datetime.now().strftime("%Y-%m-%d")),
            fix_commit=data.get("fix_commit"),
            notes=data.get("notes")
        )


class IssuesTracker:
    """
    Track and categorize test issues for vLLM unit test automation.

    Manages issue categorization, tracking, and reporting.
    Issues are stored in issues.json with the following structure:

        {
          "_schema": { ... },
          "issues": [ ... ],
          "statistics": { ... }
        }

    Error Categories:
        C-代码Bug: vLLM code defects (AssertionError, TypeError in vLLM code)
        E-环境问题: environment limits (OSError, FileNotFoundError, quota errors)
        D-依赖缺失: missing dependencies (ImportError, ModuleNotFoundError)
        P-平台兼容: PyTorch API compatibility (wrap_triton, fp32_precision, ABI errors)
        M-模型缺失: HF models not downloaded (LocalEntryNotFoundError, config.json missing)
        S-跳过问题: reasonably skipped tests (pytest.skip(), SkipTest)
    """

    # Error patterns for categorization
    CATEGORY_PATTERNS = {
        ErrorCategory.CODE_BUG: [
            r"AssertionError",
            r"TypeError.*vllm",
            r"ValueError.*vllm",
            r"RuntimeError.*vllm",
            r"AttributeError.*vllm",
            r"KeyError.*vllm",
            r"IndexError",
            r"ZeroDivisionError",
            r"RecursionError",
            r"NotImplementedError",
        ],
        ErrorCategory.ENVIRONMENT: [
            r"OSError",
            r"FileNotFoundError",
            r"PermissionError",
            r"CUDA out of memory",
            r"CUDA error",
            r"RuntimeError: CUDA",
            r"disk quota exceeded",
            r"No space left on device",
            r"Connection refused",
            r"Connection timed out",
            r"Network is unreachable",
            r"Too many open files",
            r"Resource temporarily unavailable",
        ],
        ErrorCategory.DEPENDENCY: [
            r"ImportError:",
            r"ModuleNotFoundError:",
            r"No module named",
            r"cannot import name",
            r"undefined symbol:",
            r"ABI",
            r"cannot find module",
            r"lib.*\.so.*not found",
        ],
        ErrorCategory.PLATFORM: [
            r"wrap_triton",
            r"fp32_precision",
            r"torch\.library",
            r"torch\.dynamo",
            r"torch\.compile",
            r"torch\._dynamo",
            r"VllmBackend",
            r"CompilationError",
            r"Triton.*compil",
            r"triton\.compiler",
            r"AnnAssign.*no attribute",
            r"got an unexpected keyword argument",
            r"missing.*argument",
        ],
        ErrorCategory.MODEL_MISSING: [
            r"LocalEntryNotFoundError",
            r"EntryNotFoundError",
            r"config\.json.*not found",
            r"model.*not found",
            r"snapshot.*not found",
            r"HuggingFace",
            r"HF.*timeout",
            r"hf-mirror",
            r"meta-llama",
            r"RedHatAI",
            r"does not exist.*cache",
            r"Cannot find.*model",
        ],
        ErrorCategory.SKIP: [
            r"pytest\.skip",
            r"Skipped:",
            r"SkipTest",
            r"skip.*reason:",
            r"platform.*not supported",
            r"GPU.*not available",
            r"requires.*GPU",
            r"requires.*CUDA",
            r"not implemented for",
            r"only supported on",
        ],
    }

    def __init__(self, issues_file: Union[str, Path]):
        """
        Initialize IssuesTracker.

        Args:
            issues_file: Path to issues.json file
        """
        self.issues_file = Path(issues_file)
        self._data: dict = {}
        self._issues: dict[str, Issue] = {}
        self._next_ids: dict[str, int] = {}

        # Initialize default structure
        self._init_default_structure()

        # Load existing issues
        self.load_issues()

    def _init_default_structure(self) -> None:
        """Initialize default JSON structure if file doesn't exist."""
        self._data = {
            "_schema": {
                "description": "Issues tracking for test automation",
                "issue_fields": {
                    "id": "Unique issue identifier (e.g., P-1, C-1)",
                    "category": "One of: P-平台兼容, C-代码Bug, E-环境问题, D-依赖缺失, M-模型缺失, S-跳过问题",
                    "description": "Short description of the issue",
                    "affected_tests": "List of affected test IDs",
                    "status": "One of: open, known, fixed",
                    "first_seen": "ISO date when first detected",
                    "last_seen": "ISO date when last seen",
                    "fix_commit": "Commit hash that fixed the issue (null if open)",
                    "notes": "Additional notes (null if none)"
                }
            },
            "issues": [],
            "statistics": {
                "total_issues": 0,
                "open": 0,
                "known": 0,
                "fixed": 0,
                "by_category": {
                    "C-代码Bug": 0,
                    "E-环境问题": 0,
                    "D-依赖缺失": 0,
                    "P-平台兼容": 0,
                    "M-模型缺失": 0,
                    "S-跳过问题": 0
                }
            }
        }

    def load_issues(self) -> dict:
        """
        Load issues from issues.json file.

        Returns:
            Dictionary containing the loaded data
        """
        if not self.issues_file.exists():
            logger.info("Issues file not found, creating new: %s", self.issues_file)
            self.save_issues()
            return self._data

        try:
            with open(self.issues_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            # Parse issues into Issue objects
            self._issues = {}
            for issue_data in self._data.get("issues", []):
                issue = Issue.from_dict(issue_data)
                self._issues[issue.id] = issue

            # Initialize next IDs for each category prefix
            self._init_next_ids()

            logger.info("Loaded %d issues from %s", len(self._issues), self.issues_file)
            return self._data

        except json.JSONDecodeError as e:
            logger.error("Failed to parse issues file: %s", e)
            raise

    def _init_next_ids(self) -> None:
        """Initialize next ID counters for each category prefix."""
        # Category prefix mapping
        category_prefixes = {
            "C-代码Bug": "C",
            "E-环境问题": "E",
            "D-依赖缺失": "D",
            "P-平台兼容": "P",
            "M-模型缺失": "M",
            "S-跳过问题": "S"
        }

        # Initialize all prefixes with 1
        for prefix in category_prefixes.values():
            self._next_ids[prefix] = 1

        # Update based on existing issues
        for issue_id in self._issues.keys():
            if "-" in issue_id:
                prefix, num_str = issue_id.split("-", 1)
                try:
                    num = int(num_str)
                    if prefix in self._next_ids:
                        self._next_ids[prefix] = max(self._next_ids[prefix], num + 1)
                except ValueError:
                    pass

    def save_issues(self) -> None:
        """Save issues to issues.json file."""
        # Ensure parent directory exists
        self.issues_file.parent.mkdir(parents=True, exist_ok=True)

        # Update data with current issues
        self._data["issues"] = [issue.to_dict() for issue in self._issues.values()]

        # Update statistics
        self._data["statistics"] = self.get_issue_stats()

        # Write to file
        with open(self.issues_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

        logger.info("Saved %d issues to %s", len(self._issues), self.issues_file)

    def _get_next_id(self, category: str) -> str:
        """
        Get the next available issue ID for a category.

        Args:
            category: Issue category (e.g., "C-代码Bug")

        Returns:
            Next available ID (e.g., "C-5")
        """
        # Map category to prefix
        category_to_prefix = {
            "C-代码Bug": "C",
            "E-环境问题": "E",
            "D-依赖缺失": "D",
            "P-平台兼容": "P",
            "M-模型缺失": "M",
            "S-跳过问题": "S"
        }

        prefix = category_to_prefix.get(category, "X")
        next_num = self._next_ids.get(prefix, 1)
        self._next_ids[prefix] = next_num + 1

        return f"{prefix}-{next_num}"

    def add_issue(
        self,
        category: str,
        description: str,
        affected_tests: Optional[list[str]] = None,
        status: str = "open",
        notes: Optional[str] = None,
        test_id: Optional[str] = None
    ) -> str:
        """
        Add a new issue to the tracker.

        If an issue with similar description exists, update its affected_tests
        and last_seen instead of creating a duplicate.

        Args:
            category: Issue category (e.g., "C-代码Bug")
            description: Short description of the issue
            affected_tests: List of affected test IDs
            status: Issue status (open, known, fixed)
            notes: Additional notes
            test_id: Single test ID (will be added to affected_tests)

        Returns:
            Issue ID (e.g., "C-1")
        """
        # Handle single test_id parameter
        if test_id:
            if affected_tests is None:
                affected_tests = []
            if test_id not in affected_tests:
                affected_tests.append(test_id)

        if affected_tests is None:
            affected_tests = []

        today = datetime.now().strftime("%Y-%m-%d")

        # Check for existing issue with similar description
        for issue in self._issues.values():
            if issue.category == category and issue.description == description:
                # Update existing issue
                issue.last_seen = today
                for test in affected_tests:
                    if test not in issue.affected_tests:
                        issue.affected_tests.append(test)
                logger.info("Updated existing issue %s with %d affected tests",
                           issue.id, len(issue.affected_tests))
                self.save_issues()
                return issue.id

        # Create new issue
        issue_id = self._get_next_id(category)
        issue = Issue(
            id=issue_id,
            category=category,
            description=description,
            affected_tests=affected_tests,
            status=status,
            first_seen=today,
            last_seen=today,
            notes=notes
        )

        self._issues[issue_id] = issue
        logger.info("Added new issue %s: %s", issue_id, description)
        self.save_issues()

        return issue_id

    def update_issue(
        self,
        issue_id: str,
        status: Optional[str] = None,
        affected_tests: Optional[list[str]] = None,
        fix_commit: Optional[str] = None,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update an existing issue.

        Args:
            issue_id: Issue ID to update
            status: New status (open, known, fixed)
            affected_tests: Tests to add to affected_tests list
            fix_commit: Commit hash that fixed the issue
            notes: Additional notes to append

        Returns:
            True if issue was updated, False if not found
        """
        if issue_id not in self._issues:
            logger.warning("Issue %s not found", issue_id)
            return False

        issue = self._issues[issue_id]
        today = datetime.now().strftime("%Y-%m-%d")

        # Update fields
        issue.last_seen = today

        if status:
            issue.status = status

        if affected_tests:
            for test in affected_tests:
                if test not in issue.affected_tests:
                    issue.affected_tests.append(test)

        if fix_commit:
            issue.fix_commit = fix_commit
            if status is None:
                issue.status = "fixed"

        if notes:
            if issue.notes:
                issue.notes = f"{issue.notes}\n{notes}"
            else:
                issue.notes = notes

        logger.info("Updated issue %s", issue_id)
        self.save_issues()
        return True

    def categorize_error(
        self,
        error_message: str,
        traceback: Optional[str] = None,
        test_file: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Classify error type based on error message and traceback.

        Categorization rules (in priority order):
            1. S-跳过问题: pytest.skip, SkipTest, platform not supported
            2. M-模型缺失: HF model download issues
            3. D-依赖缺失: ImportError, ModuleNotFoundError
            4. P-平台兼容: wrap_triton, torch API issues
            5. E-环境问题: CUDA OOM, network, disk errors
            6. C-代码Bug: AssertionError, vLLM code errors

        Args:
            error_message: The error message string
            traceback: Optional traceback string for additional context
            test_file: Optional test file path for context

        Returns:
            Tuple of (category_code, category_name)
            e.g., ("C", "C-代码Bug")
        """
        # Combine error message and traceback for pattern matching
        combined = error_message
        if traceback:
            combined = f"{error_message}\n{traceback}"

        # Check patterns in priority order
        # Priority: S > M > D > P > E > C
        priority_order = [
            ErrorCategory.SKIP,
            ErrorCategory.MODEL_MISSING,
            ErrorCategory.DEPENDENCY,
            ErrorCategory.PLATFORM,
            ErrorCategory.ENVIRONMENT,
            ErrorCategory.CODE_BUG,
        ]

        for category in priority_order:
            patterns = self.CATEGORY_PATTERNS.get(category, [])
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE | re.MULTILINE):
                    return (category.value[0], category.value)

        # Default to C-代码Bug if no pattern matches
        return ("C", ErrorCategory.CODE_BUG.value)

    def get_issue(self, issue_id: str) -> Optional[Issue]:
        """
        Get an issue by ID.

        Args:
            issue_id: Issue ID (e.g., "C-1")

        Returns:
            Issue object or None if not found
        """
        return self._issues.get(issue_id)

    def get_issues_by_category(self, category: str) -> list[Issue]:
        """
        Get all issues in a category.

        Args:
            category: Category name (e.g., "C-代码Bug")

        Returns:
            List of Issue objects
        """
        return [issue for issue in self._issues.values() if issue.category == category]

    def get_issues_by_status(self, status: str) -> list[Issue]:
        """
        Get all issues with a status.

        Args:
            status: Status value (open, known, fixed)

        Returns:
            List of Issue objects
        """
        return [issue for issue in self._issues.values() if issue.status == status]

    def get_issue_stats(self) -> dict:
        """
        Get issue statistics.

        Returns:
            Dictionary with:
                - total_issues: Total count
                - open: Count of open issues
                - known: Count of known issues
                - fixed: Count of fixed issues
                - by_category: Count per category
        """
        stats = {
            "total_issues": len(self._issues),
            "open": 0,
            "known": 0,
            "fixed": 0,
            "by_category": {
                "C-代码Bug": 0,
                "E-环境问题": 0,
                "D-依赖缺失": 0,
                "P-平台兼容": 0,
                "M-模型缺失": 0,
                "S-跳过问题": 0
            }
        }

        for issue in self._issues.values():
            # Count by status
            if issue.status == "open":
                stats["open"] += 1
            elif issue.status == "known":
                stats["known"] += 1
            elif issue.status == "fixed":
                stats["fixed"] += 1

            # Count by category
            if issue.category in stats["by_category"]:
                stats["by_category"][issue.category] += 1

        return stats

    def generate_report(self, include_tests: bool = False, max_tests: int = 5) -> str:
        """
        Generate a markdown report of issues for PROGRESS.md.

        Args:
            include_tests: Whether to include affected test lists
            max_tests: Maximum number of tests to show per issue

        Returns:
            Markdown formatted report string
        """
        stats = self.get_issue_stats()

        lines = [
            "## 问题分类统计",
            "",
            f"| 类别 | 数量 | 说明 |",
            f"|------|:----:|------|",
        ]

        # Category descriptions
        category_desc = {
            "C-代码Bug": "vLLM 源码缺陷",
            "E-环境问题": "环境限制（GPU内存、网络、磁盘）",
            "D-依赖缺失": "Python 包缺失",
            "P-平台兼容": "PyTorch API 兼容问题",
            "M-模型缺失": "HuggingFace 模型未下载",
            "S-跳过问题": "合理跳过的测试",
        }

        for category, count in stats["by_category"].items():
            desc = category_desc.get(category, "")
            lines.append(f"| {category} | **{count}** | {desc} |")

        lines.extend([
            "",
            f"**总问题数**: {stats['total_issues']}",
            f"**开放**: {stats['open']} | **已知**: {stats['known']} | **已修复**: {stats['fixed']}",
            ""
        ])

        # Add detailed issue list if there are issues
        if self._issues:
            lines.extend([
                "## 问题详情",
                "",
                "| 问题ID | 描述 | 状态 | 影响测试数 | 首次发现 |",
                "|--------|------|:----:|:----------:|:--------:|",
            ])

            # Sort by category and ID
            sorted_issues = sorted(
                self._issues.values(),
                key=lambda x: (x.category, x.id)
            )

            for issue in sorted_issues:
                status_indicator = {"open": "[O]", "known": "[K]", "fixed": "[F]"}.get(issue.status, "[?]")
                affected_count = len(issue.affected_tests)
                lines.append(
                    f"| {issue.id} | {issue.description} | {status_indicator} {issue.status} | "
                    f"{affected_count} | {issue.first_seen} |"
                )

                # Optionally include affected tests
                if include_tests and issue.affected_tests:
                    shown_tests = issue.affected_tests[:max_tests]
                    remaining = len(issue.affected_tests) - max_tests
                    for test in shown_tests:
                        lines.append(f"| | `{test}` | | | |")
                    if remaining > 0:
                        lines.append(f"| | ... and {remaining} more | | | |")

        lines.append("")
        lines.append(f"*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

        return "\n".join(lines)

    def generate_progress_summary(self) -> str:
        """
        Generate a brief summary for PROGRESS.md header.

        Returns:
            Brief markdown summary string
        """
        stats = self.get_issue_stats()

        return (
            f"**问题统计**: 总计 {stats['total_issues']} 个 | "
            f"开放 {stats['open']} | 已知 {stats['known']} | 已修复 {stats['fixed']}"
        )

    def find_similar_issues(self, description: str, threshold: float = 0.8) -> list[Issue]:
        """
        Find issues with similar descriptions.

        Uses simple word overlap for similarity.

        Args:
            description: Description to match
            threshold: Minimum similarity threshold (0.0 to 1.0)

        Returns:
            List of similar Issue objects
        """
        def similarity(s1: str, s2: str) -> float:
            """Calculate word overlap similarity."""
            words1 = set(s1.lower().split())
            words2 = set(s2.lower().split())
            if not words1 or not words2:
                return 0.0
            intersection = words1 & words2
            union = words1 | words2
            return len(intersection) / len(union)

        similar = []
        for issue in self._issues.values():
            sim = similarity(description, issue.description)
            if sim >= threshold:
                similar.append((issue, sim))

        # Sort by similarity descending
        similar.sort(key=lambda x: x[1], reverse=True)
        return [issue for issue, _ in similar]

    def cleanup_duplicate_tests(self) -> int:
        """
        Remove duplicate test IDs from all issues' affected_tests lists.

        Returns:
            Number of duplicates removed
        """
        removed = 0
        for issue in self._issues.values():
            original_count = len(issue.affected_tests)
            issue.affected_tests = list(set(issue.affected_tests))
            removed += original_count - len(issue.affected_tests)

        if removed > 0:
            self.save_issues()
            logger.info("Removed %d duplicate test IDs", removed)

        return removed

    def export_for_progress_md(self) -> str:
        """
        Export issues in format suitable for PROGRESS.md.

        Returns:
            Formatted string for PROGRESS.md issues section
        """
        lines = [
            "## 兼容性问题汇总",
            "",
            "详细问题记录见: `docs/reports/compatibility_issues_20260603.md`",
            "",
            "| 问题ID | 问题 | 影响测试数 |",
            "|--------|------|:--------:|",
        ]

        for issue in sorted(self._issues.values(), key=lambda x: x.id):
            count = len(issue.affected_tests)
            lines.append(f"| {issue.id} | {issue.description} | **{count}** |")

        lines.append("")
        return "\n".join(lines)


def main():
    """CLI interface for issues tracker."""
    import argparse

    parser = argparse.ArgumentParser(description="Track test issues")
    parser.add_argument(
        "--issues-file",
        "-i",
        default="issues.json",
        help="Path to issues.json file"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show issue statistics"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate markdown report"
    )
    parser.add_argument(
        "--add",
        nargs=3,
        metavar=("CATEGORY", "DESCRIPTION", "TEST_ID"),
        help="Add a new issue"
    )
    parser.add_argument(
        "--categorize",
        metavar="ERROR_MESSAGE",
        help="Categorize an error message"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all issues"
    )

    args = parser.parse_args()

    tracker = IssuesTracker(args.issues_file)

    if args.stats:
        stats = tracker.get_issue_stats()
        print("\nIssue Statistics:")
        print(f"  Total: {stats['total_issues']}")
        print(f"  Open: {stats['open']}")
        print(f"  Known: {stats['known']}")
        print(f"  Fixed: {stats['fixed']}")
        print("\nBy Category:")
        for cat, count in stats["by_category"].items():
            print(f"  {cat}: {count}")

    if args.report:
        print(tracker.generate_report(include_tests=True))

    if args.add:
        category, description, test_id = args.add
        issue_id = tracker.add_issue(
            category=category,
            description=description,
            test_id=test_id
        )
        print(f"Created issue: {issue_id}")

    if args.categorize:
        code, name = tracker.categorize_error(args.categorize)
        print(f"Category: {code} - {name}")

    if args.list:
        for issue in tracker._issues.values():
            print(f"{issue.id}: [{issue.status}] {issue.description}")

    if not any([args.stats, args.report, args.add, args.categorize, args.list]):
        parser.print_help()


if __name__ == "__main__":
    main()