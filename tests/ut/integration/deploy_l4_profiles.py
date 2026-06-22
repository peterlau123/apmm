#!/usr/bin/env python3
"""deploy_l4_profiles.py — alias for `deploy_tier.py --tier L4`.

This file exists for backward compatibility. New callers should use
`python tests/ut/integration/deploy_tier.py --tier L4` directly.

Usage (same as before):
    python tests/ut/integration/deploy_l4_profiles.py --check
    python tests/ut/integration/deploy_l4_profiles.py
"""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "deploy_tier.py"
    cmd = [sys.executable, str(script), "--tier", "L4"] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))
