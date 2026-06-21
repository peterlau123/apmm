"""Performance metrics collection for test pipeline execution.

Collects timing data for pipeline stages and computes throughput metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerfMetrics:
    """Collects and aggregates performance metrics for test pipeline runs.
    
    Usage:
        metrics = PerfMetrics(mode="mock", n=100)
        metrics.record_stage("manifest_build", 150)  # ms
        metrics.record_stage("batch_select", 50)      # ms
        # ... run tests ...
        result = metrics.finalize(total=100, passed=98, failed=2, error=0, wall_clock_s=120.0)
    """
    
    mode: str
    n: int
    _stages: dict[str, int] = field(default_factory=dict)
    
    def record_stage(self, stage_name: str, duration_ms: int) -> None:
        """Record timing for a pipeline stage (accumulates if called multiple times).
        
        Args:
            stage_name: Name of the pipeline stage (e.g., "manifest_build", "execute")
            duration_ms: Duration in milliseconds
        """
        if stage_name not in self._stages:
            self._stages[stage_name] = 0
        self._stages[stage_name] += duration_ms
    
    def finalize(
        self,
        total: int,
        passed: int,
        failed: int,
        error: int,
        wall_clock_s: float,
    ) -> dict[str, Any]:
        """Finalize metrics and return a complete metrics report.
        
        Args:
            total: Total number of tests executed
            passed: Number of passed tests
            failed: Number of failed tests
            error: Number of tests with errors
            wall_clock_s: Total wall-clock time in seconds
            
        Returns:
            Dict with all metrics including:
            - total, passed, failed, error
            - wall_clock_s
            - throughput_per_min (total / wall_clock_s * 60)
            - stage_ms (dict of stage timings)
            - mode, n
        """
        throughput_per_min = 0.0
        if wall_clock_s > 0:
            throughput_per_min = (total / wall_clock_s) * 60.0
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "error": error,
            "wall_clock_s": round(wall_clock_s, 3),
            "throughput_per_min": round(throughput_per_min, 2),
            "stage_ms": dict(self._stages),
            "mode": self.mode,
            "n": self.n,
        }