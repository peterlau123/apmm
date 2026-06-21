#!/usr/bin/env python3
"""Linear-mode v5 pipeline integration smoke harness (thin wrapper).

Runs the full v5 pipeline with REAL remote execution via bastion.
This is a thin wrapper around run_pipeline_perf.py.

Usage:
    cd D:/workspace/apmm
    python tests/ut/integration/run_linear_smoke.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_HARNESS_PATH = _PROJECT_ROOT / "tests" / "ut" / "integration" / "run_pipeline_perf.py"
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mini_test_list.txt"


def main() -> int:
    print("=" * 70)
    print("v5 LINEAR SMOKE — calling run_pipeline_perf.py --mode real")
    print("=" * 70)
    
    cmd = [
        sys.executable,
        str(_HARNESS_PATH),
        "--n", "3",
        "--mode", "real",
        "--fixture", str(_FIXTURE_PATH),
    ]
    
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())