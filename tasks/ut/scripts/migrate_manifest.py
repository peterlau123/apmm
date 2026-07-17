#!/usr/bin/env python3
"""
UT Manifest Migration Script

Merge new test_list with old manifest, preserving passed tests' status and fields.

Usage:
    python migrate_manifest.py \
        --test-list tasks/ut/dataset/ut_test_list_full_20260624_173600.txt \
        --old-manifest tasks/ut/dataset/manifest.json \
        --schema skills/ut/ut_common/manifest_schema.json \
        --output tasks/ut/dataset/manifest.json

Algorithm (Incremental Merge):
    1. Parse new test_list (33,286 test nodes)
    2. Extract old manifest passed tests (6,411 passed)
    3. Generate new manifest skeleton with all test nodes (status=pending)
    4. Merge passed status and preserve fields (log_file, last_run_at, error_type, etc.)
    5. Update statistics
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_test_list(test_list_path: Path) -> list[str]:
    """Parse test_list file and extract test nodes.

    Skip header lines (e.g., "Running N items in this shard") and empty lines.
    Skip warning source lines (format: tests/path/file.py:lineno without ::).
    Only return lines that match pytest test node format: tests/path/test_file.py::test_name

    Args:
        test_list_path: Path to test_list.txt file

    Returns:
        List of test node strings
    """
    test_nodes = []

    with open(test_list_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip header lines (don't start with tests/)
            # Skip empty lines
            # Skip warning source lines (no :: separator - not a real pytest test node)
            if not line or not line.startswith('tests/') or '::' not in line:
                continue
            test_nodes.append(line)

    return test_nodes


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load manifest schema for reference.

    Args:
        schema_path: Path to manifest_schema.json

    Returns:
        Schema dictionary
    """
    with open(schema_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_test_node(test_node: str) -> tuple[str, str]:
    """Parse test_node into test_file and test_name.

    Format: tests/path/test_file.py::test_name or tests/path/test_file.py::TestClass::test_name

    Args:
        test_node: Full test node string

    Returns:
        Tuple of (test_file, test_name)
    """
    parts = test_node.split('::')
    test_file = parts[0]

    # test_name: last component (test method name)
    # If format is tests/file.py::TestClass::test_method, use test_method
    # If format is tests/file.py::test_method[parametrize], use full test_method[parametrize]
    if len(parts) >= 2:
        test_name = parts[-1]  # Last component
    else:
        test_name = test_node  # Fallback

    return test_file, test_name


def generate_empty_entry(test_node: str, idx: int) -> dict[str, Any]:
    """Generate empty test entry with default values.

    All tests start with status='pending', fields filled per schema defaults.

    Args:
        test_node: Test node string
        idx: Test ID (1-based index)

    Returns:
        Test entry dictionary with default values
    """
    test_file, test_name = parse_test_node(test_node)

    return {
        'id': idx,
        'test_node': test_node,
        'test_file': test_file,
        'test_name': test_name,
        'status': 'pending',
        'priority': 'P2',
        'batch_id': None,
        'last_batch_id': None,
        'run_count': 0,
        'retry_count': 0,
        'max_retry': 3,
        'last_run_at': None,
        'last_duration_ms': None,
        'last_exit_code': None,
        'error_type': None,
        'error_message': None,
        'ignored_reason': None,
        'fix_applied': False,
        'fix_details': None,
        'log_file': None,
        'errors': [],
        'failures': []
    }


def merge_manifests(
    test_list_path: Path,
    old_manifest_path: Path,
    schema_path: Path
) -> dict[str, Any]:
    """Merge new test_list with old manifest, preserving passed tests.

    Core algorithm:
    1. Parse new test_list to get all test nodes
    2. Extract old manifest passed tests into a map
    3. For each new test node:
       - Generate empty entry (status=pending)
       - If test_node in old passed_map, preserve status and fields
    4. Update statistics

    Args:
        test_list_path: Path to new test_list file
        old_manifest_path: Path to old manifest.json
        schema_path: Path to manifest_schema.json

    Returns:
        New manifest dictionary with merged data
    """
    # Step 1: Parse new test_list
    new_test_nodes = parse_test_list(test_list_path)
    print(f"Parsed {len(new_test_nodes)} test nodes from new test_list")

    # Step 2: Load old manifest and extract passed tests
    with open(old_manifest_path, 'r', encoding='utf-8') as f:
        old_manifest = json.load(f)

    old_tests = old_manifest.get('tests', [])
    passed_map: dict[str, dict[str, Any]] = {
        t['test_node']: t
        for t in old_tests
        if t.get('status') == 'passed'
    }
    print(f"Old manifest: {len(old_tests)} tests, {len(passed_map)} passed")

    # Step 3: Load schema (for validation reference)
    schema = load_schema(schema_path)

    # Step 4: Generate new manifest skeleton
    new_manifest: dict[str, Any] = {
        'version': '2.0',
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': test_list_path.name,
        'tests': [],
        'statistics': {}
    }

    # Preserve config from old manifest if exists
    if 'config' in old_manifest:
        new_manifest['config'] = old_manifest['config']

    # Preserve metadata from old manifest if exists
    if 'metadata' in old_manifest:
        new_manifest['metadata'] = old_manifest['metadata']

    # Step 5: Merge test entries
    preserved_count = 0

    for idx, test_node in enumerate(new_test_nodes):
        entry = generate_empty_entry(test_node, idx + 1)

        # If test_node exists in old passed_map, preserve status and fields
        if test_node in passed_map:
            old_entry = passed_map[test_node]
            entry['status'] = 'passed'

            # Preserve execution fields
            entry['log_file'] = old_entry.get('log_file')
            entry['last_run_at'] = old_entry.get('last_run_at')
            entry['last_batch_id'] = old_entry.get('last_batch_id')
            entry['last_duration_ms'] = old_entry.get('last_duration_ms')
            entry['last_exit_code'] = old_entry.get('last_exit_code')

            # Preserve error fields (KEY: error_type must be preserved)
            entry['error_type'] = old_entry.get('error_type')
            entry['error_message'] = old_entry.get('error_message')

            # Preserve retry configuration
            entry['max_retry'] = old_entry.get('max_retry', 3)
            entry['run_count'] = old_entry.get('run_count', 1)

            # Preserve errors/failures history if exists
            if 'errors' in old_entry:
                entry['errors'] = old_entry['errors']
            if 'failures' in old_entry:
                entry['failures'] = old_entry['failures']

            preserved_count += 1

        new_manifest['tests'].append(entry)

    print(f"Preserved {preserved_count} passed tests from old manifest")

    # Step 6: Update statistics
    total = len(new_manifest['tests'])
    passed_count = sum(1 for t in new_manifest['tests'] if t['status'] == 'passed')
    pending_count = total - passed_count
    progress = round(passed_count / total * 100, 2) if total > 0 else 0
    pass_rate = progress  # Same as progress since all executed tests passed

    new_manifest['statistics'] = {
        'total': total,
        'executed': passed_count,  # Only passed tests are "executed"
        'progress': progress,
        'passed': passed_count,
        'failed': 0,
        'error': 0,
        'ignored': 0,
        'pending': pending_count,
        'pass_rate': pass_rate
    }

    print(f"New manifest statistics: Total={total}, Passed={passed_count}, Pending={pending_count}, Progress={progress}%")

    # Preserve resolved_errors and resolved_failures from old manifest
    if 'resolved_errors' in old_manifest:
        new_manifest['resolved_errors'] = old_manifest['resolved_errors']
    if 'resolved_failures' in old_manifest:
        new_manifest['resolved_failures'] = old_manifest['resolved_failures']

    return new_manifest


def main():
    """Main entry point for manifest migration."""
    parser = argparse.ArgumentParser(
        description='Merge new test_list with old manifest, preserving passed tests'
    )
    parser.add_argument(
        '--test-list',
        type=Path,
        required=True,
        help='Path to new test_list file'
    )
    parser.add_argument(
        '--old-manifest',
        type=Path,
        required=True,
        help='Path to old manifest.json'
    )
    parser.add_argument(
        '--schema',
        type=Path,
        required=True,
        help='Path to manifest_schema.json'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Path to output manifest.json (will overwrite)'
    )

    args = parser.parse_args()

    # Validate input files exist
    if not args.test_list.exists():
        print(f"ERROR: Test list file not found: {args.test_list}")
        return 1

    if not args.old_manifest.exists():
        print(f"ERROR: Old manifest file not found: {args.old_manifest}")
        return 1

    if not args.schema.exists():
        print(f"ERROR: Schema file not found: {args.schema}")
        return 1

    print(f"Merging manifests...")
    print(f"  Test list: {args.test_list}")
    print(f"  Old manifest: {args.old_manifest}")
    print(f"  Schema: {args.schema}")
    print(f"  Output: {args.output}")
    print()

    # Merge manifests
    new_manifest = merge_manifests(args.test_list, args.old_manifest, args.schema)

    # Write output
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(new_manifest, f, indent=2, ensure_ascii=False)

    print(f"\nSUCCESS: Merged manifest written to {args.output}")
    print(f"  Total tests: {new_manifest['statistics']['total']}")
    print(f"  Passed tests preserved: {new_manifest['statistics']['passed']}")
    print(f"  Progress: {new_manifest['statistics']['progress']}%")

    return 0


if __name__ == '__main__':
    exit(main())