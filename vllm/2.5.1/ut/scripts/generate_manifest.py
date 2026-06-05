#!/usr/bin/env python3
"""
generate_manifest.py - Generate JSON manifest from test list file

Usage:
    # Generate manifest from test list
    python generate_manifest.py --input test_list.txt --output test_manifest.json

    # Generate Phase 2 manifest from diff of two test lists
    python generate_manifest.py --phase2 --input ut_test_list_full.txt --diff ut_test_list.txt --output test_manifest_phase2.json

    # Alternative: use base manifest for diff
    python generate_manifest.py --phase2 --input ut_test_list_full.txt --diff-base test_manifest.json --output test_manifest_phase2.json
"""

import argparse
import json
import os
from datetime import datetime
from typing import List, Set, Optional


def load_test_list(file_path: str) -> List[str]:
    """Load test nodes from a test list file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Test list file not found: {file_path}")

    tests = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            test_node = line.strip()
            if not test_node or not test_node.startswith("tests/"):
                continue
            tests.append(test_node)

    return tests


def load_tests_from_manifest(manifest_path: str) -> List[str]:
    """Load test nodes from a manifest JSON file."""
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    return [test["test_node"] for test in manifest.get("tests", [])]


def compute_remaining_tests(full_list: List[str], phase1_list: List[str]) -> List[str]:
    """
    Find tests in full_list that are NOT in phase1_list.

    Args:
        full_list: List of all test nodes (Phase 2 complete list)
        phase1_list: List of Phase 1 test nodes (already executed)

    Returns:
        List of test nodes to execute in Phase 2, sorted by test file
    """
    phase1_set = set(phase1_list)
    full_set = set(full_list)

    remaining = full_set - phase1_set

    # Sort by test file for organized execution
    return sorted(remaining, key=lambda x: x.split("::")[0])


def generate_manifest(
    input_file: str,
    output_file: str,
    diff_file: Optional[str] = None,
    diff_base_manifest: Optional[str] = None,
    is_phase2: bool = False,
):
    """Generate JSON manifest from test list file.

    Args:
        input_file: Path to test list file
        output_file: Path to output JSON manifest
        diff_file: Path to base test list file for diff (Phase 1 list)
        diff_base_manifest: Path to base manifest file for diff (alternative to diff_file)
        is_phase2: If True, treat this as Phase 2 manifest generation
    """
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    # Determine which tests to include
    if diff_file or diff_base_manifest:
        # Diff mode: compute remaining tests
        full_list = load_test_list(input_file)

        if diff_base_manifest:
            phase1_list = load_tests_from_manifest(diff_base_manifest)
            print(f"Loaded {len(phase1_list)} tests from base manifest: {diff_base_manifest}")
        else:
            phase1_list = load_test_list(diff_file)
            print(f"Loaded {len(phase1_list)} tests from base test list: {diff_file}")

        tests_to_run = compute_remaining_tests(full_list, phase1_list)
        print(f"Full test list: {len(full_list)} tests")
        print(f"Phase 1 tests: {len(phase1_list)} tests")
        print(f"Remaining tests for Phase 2: {len(tests_to_run)} tests")
    else:
        # Normal mode: use all tests from input file
        tests_to_run = load_test_list(input_file)
        print(f"Loaded {len(tests_to_run)} tests from: {input_file}")

    # Build manifest entries
    tests = []
    for idx, test_node in enumerate(tests_to_run, 1):
        # Extract file path and test function
        parts = test_node.split("::")
        test_file = parts[0] if len(parts) >= 1 else ""
        test_func = parts[1] if len(parts) >= 2 else ""

        tests.append({
            "id": idx,
            "test_node": test_node,
            "test_file": test_file,
            "test_func": test_func,
            "status": "pending",
            "run_at": None,
            "duration_ms": None,
            "exit_code": None,
            "error_type": None,
            "error_message": None,
        })

    # Build manifest structure
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "source_file": os.path.basename(input_file),
        "total_tests": len(tests),
        "is_phase2": is_phase2,
        "statistics": {
            "pending": len(tests),
            "passed": 0,
            "failed": 0,
            "error": 0,
            "timeout": 0,
            "skipped": 0,
        },
        "tests": tests,
    }

    # Add diff info if applicable
    if diff_file:
        manifest["diff_source"] = os.path.basename(diff_file)
    if diff_base_manifest:
        manifest["diff_source"] = os.path.basename(diff_base_manifest)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Generated manifest with {len(tests)} tests")
    print(f"Output: {output_file}")
    print(f"Size: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Generate JSON test manifest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate manifest from test list
  python generate_manifest.py -i test_list.txt -o test_manifest.json

  # Generate Phase 2 manifest (diff mode)
  python generate_manifest.py --phase2 -i ut_test_list_full.txt --diff ut_test_list.txt -o test_manifest_phase2.json

  # Use existing manifest as base for diff
  python generate_manifest.py --phase2 -i ut_test_list_full.txt --diff-base test_manifest.json -o test_manifest_phase2.json
""",
    )
    parser.add_argument("--input", "-i", required=True, help="Input test list file")
    parser.add_argument("--output", "-o", required=True, help="Output JSON manifest file")
    parser.add_argument(
        "--diff",
        "-d",
        dest="diff_file",
        help="Base test list file to diff against (Phase 1 list)",
    )
    parser.add_argument(
        "--diff-base",
        dest="diff_base_manifest",
        help="Base manifest file to diff against (alternative to --diff)",
    )
    parser.add_argument(
        "--phase2",
        action="store_true",
        help="Mark this as Phase 2 manifest (computed from diff)",
    )
    args = parser.parse_args()

    if args.diff_file and args.diff_base_manifest:
        parser.error("Cannot use both --diff and --diff-base; choose one")

    generate_manifest(
        input_file=args.input,
        output_file=args.output,
        diff_file=args.diff_file,
        diff_base_manifest=args.diff_base_manifest,
        is_phase2=args.phase2,
    )


if __name__ == "__main__":
    main()