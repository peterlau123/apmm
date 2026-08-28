#!/usr/bin/env python3
"""Orchestrator round 1 for UT workflow."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path("D:/workspace/apmm/skills/ut/workflow/scripts").resolve()))

from skills.ut.hermes_workflow.scripts.orchestrator_round import orchestrator_round

result = orchestrator_round(
    run_dir=Path("D:/workspace/apmm/runs/ut-20260623-105441"),
    manifest_path=Path("D:/workspace/apmm/runs/ut-20260623-105441/manifest.json"),
    prev_batch_dir=None,
    batch_size=3,
)

print(json.dumps(result, indent=2, ensure_ascii=False, default=str))