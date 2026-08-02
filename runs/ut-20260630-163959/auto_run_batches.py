#!/usr/bin/env python3
"""
auto_run_batches.py - Automated batch execution loop
Target: 1200 batches total (current ~1007, need ~193 more)
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import random

RUN_DIR = Path(__file__).parent
BATCH_SIZE = 8
TARGET_BATCHES = 1200

def get_current_stats():
    """Read manifest statistics"""
    manifest_path = RUN_DIR / "manifest.json"
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    stats = manifest.get('statistics', {})
    processed = stats.get('passed', 0) + stats.get('failed', 0) + stats.get('error', 0) + stats.get('ignored', 0)
    batches_run = processed // BATCH_SIZE
    return batches_run, stats

def update_manifest(batch_results):
    """Update manifest with batch results"""
    manifest_path = RUN_DIR / "manifest.json"
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    batch_id = batch_results['batch_id']
    for test_result in batch_results['tests']:
        test_id = test_result['id']
        for test in manifest['tests']:
            if test['id'] == test_id:
                test['status'] = test_result['status']
                test['batch_id'] = batch_id
                test['last_batch_id'] = batch_id
                test['run_count'] = test.get('run_count', 0) + 1
                test['last_run_at'] = batch_results['finished_at']
                test['last_duration_ms'] = test_result['duration_ms']
                test['last_exit_code'] = test_result['exit_code']
                test['error_type'] = test_result['error_type']
                test['error_message'] = test_result['error_message'][:500] if test_result['error_message'] else None
                test['log_file'] = test_result['log_path']
                break
    
    # Recalculate statistics
    status_counts = {'pending': 0, 'passed': 0, 'failed': 0, 'error': 0, 'ignored': 0}
    for test in manifest['tests']:
        status = test.get('status', 'pending')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    manifest['statistics'] = {
        'total': len(manifest['tests']),
        **status_counts,
        'progress_pct': round((status_counts['passed'] + status_counts['failed'] + status_counts['error'] + status_counts['ignored']) / len(manifest['tests']) * 100, 2)
    }
    manifest['generated_at'] = datetime.now().isoformat()
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    return manifest['statistics']

def generate_batch():
    """Generate next batch from pending tests"""
    manifest_path = RUN_DIR / "manifest.json"
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    pending_tests = [t for t in manifest['tests'] if t.get('status') == 'pending']
    if not pending_tests:
        return None, 0
    
    selected = random.sample(pending_tests, min(BATCH_SIZE, len(pending_tests)))
    batch_id = 'batch_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    
    for test in selected:
        test['batch_id'] = batch_id
    
    batch_config = {
        'batch_id': batch_id,
        'tests': selected,
        'generated_at': datetime.now().isoformat()
    }
    
    batch_config_path = RUN_DIR / "batches" / "batch_config.json"
    with open(batch_config_path, 'w', encoding='utf-8') as f:
        json.dump(batch_config, f, indent=2, ensure_ascii=False)
    
    return batch_id, len(selected)

def execute_batch():
    """Execute batch using execute_batch.py"""
    skill_path = RUN_DIR.parent.parent / "skills/ut/unit-test-executor/scripts/execute_batch.py"
    batch_config_path = RUN_DIR / "batches/batch_config.json"
    workflow_state_path = RUN_DIR / "workflow_state.json"
    
    cmd = [
        sys.executable,
        str(skill_path),
        "--batch-config", str(batch_config_path),
        "--workflow-state", str(workflow_state_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"[ERROR] execute_batch failed: {result.stderr}")
        return None
    
    # Parse batch_results.json
    batch_results_path = RUN_DIR / "batches/batch_results.json"
    with open(batch_results_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    print("=" * 60)
    print("Auto Batch Runner - Target: 1200 batches")
    print("=" * 60)
    
    batches_run, stats = get_current_stats()
    print(f"Current: {batches_run} batches run")
    print(f"Stats: passed={stats['passed']}, failed={stats['failed']}, error={stats['error']}, ignored={stats['ignored']}, pending={stats['pending']}")
    print(f"Target: {TARGET_BATCHES} batches")
    print(f"Need: {TARGET_BATCHES - batches_run} more batches")
    print("=" * 60)
    
    batch_count = 0
    while batches_run + batch_count < TARGET_BATCHES:
        batch_count += 1
        print(f"\n[{batch_count}/{TARGET_BATCHES - batches_run}] Generating batch...")
        
        batch_id, test_count = generate_batch()
        if batch_id is None:
            print("[INFO] No pending tests remaining")
            break
        
        print(f"  Batch: {batch_id} ({test_count} tests)")
        
        # Execute batch
        print(f"  Executing...")
        batch_results = execute_batch()
        if batch_results is None:
            print("[WARN] Execution failed, skipping")
            continue
        
        # Update manifest
        print(f"  Updating manifest...")
        new_stats = update_manifest(batch_results)
        
        # Print results
        batch_stats = batch_results.get('statistics', {})
        print(f"  Results: passed={batch_stats['passed']}, failed={batch_stats['failed']}, error={batch_stats['error']}, ignored={batch_stats['ignored']}")
        print(f"  Progress: {new_stats['progress_pct']}%")
    
    print("\n" + "=" * 60)
    print(f"Completed {batch_count} batches")
    final_batches, final_stats = get_current_stats()
    print(f"Total batches: {final_batches}")
    print(f"Final stats: passed={final_stats['passed']}, failed={final_stats['failed']}, error={final_stats['error']}, pending={final_stats['pending']}")
    print("=" * 60)

if __name__ == "__main__":
    main()