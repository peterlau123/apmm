"""Unit tests for PerfMetrics performance collector."""

import pytest

from tests.ut.integration._perf import PerfMetrics


class TestPerfMetrics:
    """Tests for PerfMetrics class."""
    
    def test_throughput_calculation(self):
        """Test throughput: 8 cases / 120s = 4 cases/min."""
        metrics = PerfMetrics(mode="mock", n=8)
        result = metrics.finalize(
            total=8,
            passed=8,
            failed=0,
            error=0,
            wall_clock_s=120.0,
        )
        
        assert result["total"] == 8
        assert result["passed"] == 8
        assert result["failed"] == 0
        assert result["error"] == 0
        assert result["wall_clock_s"] == 120.0
        assert result["throughput_per_min"] == 4.0
    
    def test_throughput_fractional(self):
        """Test throughput with fractional result."""
        metrics = PerfMetrics(mode="real", n=100)
        result = metrics.finalize(
            total=100,
            passed=95,
            failed=5,
            error=0,
            wall_clock_s=150.0,
        )
        
        expected_throughput = (100 / 150.0) * 60.0
        assert result["throughput_per_min"] == round(expected_throughput, 2)
    
    def test_throughput_zero_time(self):
        """Test throughput when wall_clock_s is 0 (avoid division by zero)."""
        metrics = PerfMetrics(mode="mock", n=0)
        result = metrics.finalize(
            total=0,
            passed=0,
            failed=0,
            error=0,
            wall_clock_s=0.0,
        )
        
        assert result["throughput_per_min"] == 0.0
    
    def test_stage_accumulation(self):
        """Test that stage times accumulate correctly."""
        metrics = PerfMetrics(mode="mock", n=10)
        
        metrics.record_stage("manifest_build", 100)
        metrics.record_stage("batch_select", 50)
        metrics.record_stage("manifest_build", 50)  # Accumulate
        
        result = metrics.finalize(
            total=10,
            passed=10,
            failed=0,
            error=0,
            wall_clock_s=30.0,
        )
        
        stage_ms = result["stage_ms"]
        assert stage_ms["manifest_build"] == 150
        assert stage_ms["batch_select"] == 50
    
    def test_finalize_output_structure(self):
        """Test that finalize returns all required keys."""
        metrics = PerfMetrics(mode="mock", n=5)
        metrics.record_stage("setup", 200)
        
        result = metrics.finalize(
            total=5,
            passed=3,
            failed=1,
            error=1,
            wall_clock_s=60.0,
        )
        
        required_keys = [
            "total",
            "passed",
            "failed",
            "error",
            "wall_clock_s",
            "throughput_per_min",
            "stage_ms",
            "mode",
            "n",
        ]
        
        for key in required_keys:
            assert key in result, f"Missing key: {key}"
        
        assert result["mode"] == "mock"
        assert result["n"] == 5
        assert isinstance(result["stage_ms"], dict)
    
    def test_multiple_stages(self):
        """Test recording multiple different stages."""
        metrics = PerfMetrics(mode="real", n=50)
        
        metrics.record_stage("manifest_build", 120)
        metrics.record_stage("batch_select", 80)
        metrics.record_stage("execute", 5000)
        metrics.record_stage("analyze", 200)
        metrics.record_stage("update_manifest", 50)
        
        result = metrics.finalize(
            total=50,
            passed=48,
            failed=2,
            error=0,
            wall_clock_s=300.0,
        )
        
        stages = result["stage_ms"]
        assert len(stages) == 5
        assert stages["manifest_build"] == 120
        assert stages["execute"] == 5000
        
        expected_throughput = (50 / 300.0) * 60.0
        assert result["throughput_per_min"] == round(expected_throughput, 2)