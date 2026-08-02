#!/usr/bin/env python3
"""
Update manifest.json from batch execution results
Uses test IDs from batch configs to update manifest
"""
import json
from pathlib import Path
from datetime import datetime

RUN_DIR = Path(__file__).parent
BATCHES_DIR = RUN_DIR / "batches"

def get_test_ids_from_batch(batch_id):
    """Get test IDs from batch config"""
    config_path = BATCHES_DIR / batch_id / "batch_config.json"
    if not config_path.exists():
        return set()
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    return {t['id'] for t in config.get('tests', [])}

def update_manifest_from_batches():
    """Update manifest with batch execution results"""
    
    # Load batch execution list
    print("Loading batch execution list...")
    with open(RUN_DIR / 'batch_execution_list.json', 'r') as f:
        batch_data = json.load(f)
    
    # Get passed batches with their execution info
    passed_batches = [b for b in batch_data['batches'] 
                     if b.get('status') == 'passed']
    print(f"Passed batches: {len(passed_batches)}")
    
    # Build test_id -> execution_info mapping
    print("Loading test IDs from batch configs...")
    test_id_to_info = {}
    for batch in passed_batches:
        batch_id = batch['batch_id']
        test_ids = get_test_ids_from_batch(batch_id)
        for tid in test_ids:
            test_id_to_info[tid] = {
                'batch_id': batch_id,
                'executed_at': batch.get('executed_at'),
                'exit_code': batch.get('exit_code', 0)
            }
    print(f"Total test IDs from passed batches: {len(test_id_to_info)}")
    
    # Load manifest
    print("\nLoading manifest.json...")
    with open(RUN_DIR / 'manifest.json', 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    print(f"Total tests in manifest: {len(manifest['tests'])}")
    
    # Update tests
    updated_count = 0
    already_passed = 0
    not_found = 0
    
    for test in manifest['tests']:
        test_id = test.get('id')
        
        # Skip if already passed
        if test.get('status') == 'passed':
            already_passed += 1
            continue
        
        # Check if this test ID was executed in passed batches
        if test_id in test_id_to_info:
            info = test_id_to_info[test_id]
            test['status'] = 'passed'
            test['batch_id'] = info['batch_id']
            test['last_batch_id'] = info['batch_id']
            test['last_run_at'] = info['executed_at']
            test['run_count'] = test.get('run_count', 0) + 1
            test['last_exit_code'] = info['exit_code']
            updated_count += 1
    
    print(f"\nUpdate summary:")
    print(f"  Already passed: {already_passed}")
    print(f"  Newly updated to passed: {updated_count}")
    print(f"  Not in passed batches: {not_found}")
    
    # Recalculate statistics
    print("\nRecalculating statistics...")
    status_counts = {'pending': 0, 'passed': 0, 'failed': 0, 
                     'error': 0, 'ignored': 0}
    for test in manifest['tests']:
        status = test.get('status', 'pending')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    total = len(manifest['tests'])
    executed = status_counts['passed'] + status_counts['failed'] + \
               status_counts['error'] + status_counts['ignored']
    progress_pct = round(executed / total * 100, 2) if total > 0 else 0
    
    manifest['statistics'] = {
        'total': total,
        **status_counts,
        'executed': executed,
        'progress': progress_pct
    }
    manifest['generated_at'] = datetime.now().isoformat()
    
    print(f"\nNew statistics:")
    print(f"  Total: {total}")
    print(f"  Passed: {status_counts['passed']} (+{updated_count})")
    print(f"  Failed: {status_counts['failed']}")
    print(f"  Error: {status_counts['error']}")
    print(f"  Ignored: {status_counts['ignored']}")
    print(f"  Pending: {status_counts['pending']}")
    print(f"  Progress: {progress_pct}%")
    
    # Save updated manifest
    print("\nSaving updated manifest...")
    with open(RUN_DIR / 'manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    print("✅ Manifest updated successfully!")
    
    # Save summary
    summary = {
        'updated_at': datetime.now().isoformat(),
        'tests_updated': updated_count,
        'new_passed_count': status_counts['passed'],
        'progress_pct': progress_pct
    }
    with open(RUN_DIR / 'manifest_update_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    return summary

if __name__ == '__main__':
    update_manifest_from_batches()
