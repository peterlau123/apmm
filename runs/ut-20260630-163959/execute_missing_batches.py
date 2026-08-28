#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import time

RUN_DIR = Path(__file__).parent
BATCH_DIR = RUN_DIR / 'batches'

def load_batch_list():
    list_path = RUN_DIR / 'batch_execution_list.json'
    with open(list_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def update_batch_status(batch_id, result):
    list_path = RUN_DIR / 'batch_execution_list.json'
    with open(list_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for batch in data['batches']:
        if batch['batch_id'] == batch_id:
            batch['status'] = result['status']
            batch['executed_at'] = datetime.now().isoformat()
            if 'exit_code' in result:
                batch['exit_code'] = result['exit_code']
            break
    
    with open(list_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def execute_batch(batch_id, batch_config_path):
    """Execute a single batch using agent.py"""
    # Read batch config to get test nodes
    with open(batch_config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    distributed_tests = config.get('distributed_tests', [])
    test_nodes = [t['test_node'] for t in distributed_tests]
    
    if not test_nodes:
        print(f"  [WARN] No distributed tests found in {batch_id}")
        return {'status': 'skipped', 'reason': 'no_tests'}
    
    # Build pytest command for remote execution
    test_pattern = ' '.join([f"'{tn}'" for tn in test_nodes])
    pytest_cmd = (
        f"cd /gpfs/gcsp/M2.7_verify/vllm && "
        f"RAY_ADDRESS=auto pytest -n 2 {test_pattern} "
        f"--tb=short -v "
        f"--json-report --json-report-file=/tmp/{batch_id}_results.json"
    )
    
    # Execute via agent.py
    cmd = [
        "python", "tools/agent.py",
        "-p", "t_h20",
        "run",
        f"sudo docker exec v0.13.0_torch2.5.1_compile bash -c '{pytest_cmd}'"
    ]
    
    print(f"  [EXEC] Running {len(test_nodes)} distributed tests...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=RUN_DIR.parent.parent  # Run from apmm root
        )
        
        # Check results
        if result.returncode == 0:
            print(f"  [PASS] Batch {batch_id} completed successfully")
            return {'status': 'passed', 'exit_code': 0}
        else:
            print(f"  [FAIL] Batch {batch_id} failed with exit code {result.returncode}")
            print(f"  [STDERR] {result.stderr[:200]}")
            return {'status': 'failed', 'exit_code': result.returncode, 'error': result.stderr[:500]}
            
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] Batch {batch_id} timed out after 600s")
        return {'status': 'timeout', 'exit_code': -1}
    except Exception as e:
        print(f"  [ERROR] Batch {batch_id} execution error: {e}")
        return {'status': 'error', 'exit_code': -1, 'error': str(e)}

def main():
    print("=" * 70)
    print("Execute 76 Missing Batches with NCCL Fix")
    print("=" * 70)
    print(f"NCCL: nvidia-nccl-cu12 2.21.5 (CUDA 12.4 compatible)")
    print(f"Container: v0.13.0_torch2.5.1_compile")
    print("=" * 70)
    
    batch_data = load_batch_list()
    batches = [b for b in batch_data['batches'] if b['status'] == 'pending']
    
    print(f"\nTotal batches to execute: {len(batches)}")
    print(f"Already completed: {batch_data['total'] - len(batches)}")
    print()
    
    # Execution stats
    stats = {'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0, 'timeout': 0}
    
    for i, batch in enumerate(batches, 1):
        batch_id = batch['batch_id']
        batch_config_path = BATCH_DIR / batch_id / "batch_config.json"
        
        print(f"\n[{i}/{len(batches)}] Executing {batch_id}...")
        print(f"  Tests: {batch['test_count']}, Distributed: {batch['distributed_tests']}")
        
        # Check if batch config exists
        if not batch_config_path.exists():
            print(f"  [SKIP] Config not found: {batch_config_path}")
            stats['skipped'] += 1
            update_batch_status(batch_id, {'status': 'skipped', 'reason': 'config_not_found'})
            continue
        
        # Execute batch
        result = execute_batch(batch_id, batch_config_path)
        
        # Update status
        update_batch_status(batch_id, result)
        
        # Update stats
        if result['status'] == 'passed':
            stats['passed'] += 1
        elif result['status'] == 'failed':
            stats['failed'] += 1
        elif result['status'] == 'timeout':
            stats['timeout'] += 1
        elif result['status'] == 'error':
            stats['error'] += 1
        else:
            stats['skipped'] += 1
        
        # Progress
        completed = sum(stats.values())
        print(f"  Progress: {completed}/{len(batches)} batches ({completed/len(batches)*100:.1f}%)")
        print(f"  Stats: passed={stats['passed']}, failed={stats['failed']}, error={stats['error']}, timeout={stats['timeout']}, skipped={stats['skipped']}")
        
        # Small delay between batches
        time.sleep(2)
    
    # Summary
    print("\n" + "=" * 70)
    print("Execution Summary")
    print("=" * 70)
    print(f"Total batches: {len(batches)}")
    print(f"Passed: {stats['passed']}")
    print(f"Failed: {stats['failed']}")
    print(f"Error: {stats['error']}")
    print(f"Timeout: {stats['timeout']}")
    print(f"Skipped: {stats['skipped']}")
    print("=" * 70)
    
    # Save summary
    summary = {
        'executed_at': datetime.now().isoformat(),
        'total': len(batches),
        'stats': stats,
        'success_rate': stats['passed'] / len(batches) * 100 if batches else 0
    }
    
    summary_path = RUN_DIR / "batch_execution_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nSummary saved to: {summary_path}")

if __name__ == '__main__':
    main()
