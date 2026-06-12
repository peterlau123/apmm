import json
from pathlib import Path
from datetime import datetime

run_dir = Path(r'D:\workspace\apmm\runs\ut-20260612-104339')
batch_id = 'batch_20260612_104339'
batch_dir = run_dir / 'batches' / batch_id
batch_dir.mkdir(parents=True, exist_ok=True)
(batch_dir / 'logs').mkdir(exist_ok=True)

# batch_config
batch_config = {
    'batch_id': batch_id,
    'tests': [{
        'id': 1,
        'test_node': 'tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestMMRSModel]',
        'test_file': 'tests/compile/distributed/test_async_tp.py',
        'test_name': 'test_async_tp_pass_replace[True-dtype0-16-16-8-TestMMRSModel]',
        'status': 'pending'
    }],
    'distributed_count': 1,
    'requires_multi_gpu': True,
    'generated_at': datetime.now().isoformat()
}
(batch_dir / 'batch_config.json').write_text(json.dumps(batch_config, indent=2), encoding='utf-8')

# batch_results - failed
results = {
    'batch_id': batch_id,
    'results': [{
        'id': 1,
        'test_node': 'tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestMMRSModel]',
        'status': 'failed',
        'duration_ms': 12550,
        'exit_code': 1,
        'error_type': 'network',
        'error_message': 'NCCL error: unhandled cuda error; also tries to download facebook/opt-125m from HF (no internet)'
    }],
    'stats': {'passed': 0, 'failed': 1, 'error': 0, 'ignored': 0, 'pending': 0},
    'executed_at': datetime.now().isoformat()
}
(batch_dir / 'batch_results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')

# Stage 4: failure-handler -> mark as ignored
handled = {
    'batch_id': batch_id,
    'tests': [{
        'id': 1,
        'test_node': 'tests/compile/distributed/test_async_tp.py::test_async_tp_pass_replace[True-dtype0-16-16-8-TestMMRSModel]',
        'status': 'ignored',
        'ignored_reason': 'requires internet (HF download facebook/opt-125m) + multi-GPU NCCL; container offline',
        'fix_attempted': True,
        'fix_details': 'Tried MASTER_ADDR=127.0.0.1 (fixed IPv6 issue), but NCCL still fails + model download needed'
    }],
    'stats': {'passed': 0, 'failed': 0, 'error': 0, 'ignored': 1, 'pending': 0},
    'handled_at': datetime.now().isoformat()
}
(batch_dir / 'handled_tests.json').write_text(json.dumps(handled, indent=2, ensure_ascii=False), encoding='utf-8')

# Stage 5: update manifest
manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
for t in manifest['tests']:
    if t['id'] == 1:
        t['status'] = 'ignored'
        t['last_run_at'] = datetime.now().isoformat()
        t['last_duration_ms'] = 12550
        t['last_exit_code'] = 1
        t['error_type'] = 'network'
        t['error_message'] = 'NCCL error + HF model download failed (no internet)'
        t['ignored_reason'] = 'requires internet (HF download) + multi-GPU NCCL; container offline'

stats = {'total': 1, 'passed': 0, 'failed': 0, 'error': 0, 'ignored': 1, 'pending': 0}
stats['executed'] = 1
stats['progress'] = 100.0
stats['pass_rate'] = 0.0
manifest['statistics'] = stats
manifest['generated_at'] = datetime.now().isoformat()
(run_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

# Update workflow state
state = json.loads((run_dir / 'workflow_state.json').read_text(encoding='utf-8'))
state['current_stage'] = 'completed'
state['workflow']['status'] = 'completed'
state['stats']['ignored'] = 1
state['stats']['pending'] = 0
state['stats']['total_tests'] = 1
state['iteration'] = 1
(run_dir / 'workflow_state.json').write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')

print('Done: test marked as ignored')
print(json.dumps(stats, indent=2))
