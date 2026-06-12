import json, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r'D:\workspace\apmm\skills\ut')
from shared.config_loader import get_paths

state_path = r'D:\workspace\apmm\runs\ut-20260612-101857\workflow_state.json'
paths = get_paths(Path(state_path))

manifest = json.loads(Path(paths['manifest']).read_text(encoding='utf-8'))
pending = [t for t in manifest['tests'] if t.get('status') == 'pending']
print(f'Pending tests: {len(pending)}')

batch_id = 'batch_' + datetime.now().strftime('%Y%m%d_%H%M%S')
batch_dir = Path(paths['run_dir']) / 'batches' / batch_id
batch_dir.mkdir(parents=True, exist_ok=True)
(batch_dir / 'logs').mkdir(exist_ok=True)

batch_config = {
    'batch_id': batch_id,
    'tests': pending[:1],
    'distributed_count': 0,
    'requires_multi_gpu': False,
    'generated_at': datetime.now().isoformat()
}

batch_config_path = batch_dir / 'batch_config.json'
Path(batch_config_path).write_text(json.dumps(batch_config, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Batch config written: {batch_config_path}')
print(f'Batch ID: {batch_id}')
print(f'Tests in batch: {len(batch_config["tests"])}')
