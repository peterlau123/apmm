#!/usr/bin/env python3
"""
update_test_load_two_phase.py - Batch完成后更新test_load和workflow_state

数据流架构:
  - test_load = 工作数据集（运行期间活跃读写）
  - manifest.json = 主记录（仅由 update_manifest_from_test_load.py 在全部完成后回写）
  - workflow_state.json = 运行状态

本脚本在每个batch完成后调用:
  1. 读取 batch_results.json + handled_tests.json
  2. 对 test_load 应用 v5 merge（retry_count, retriable_error->ignored, handled overrides）
  3. 更新 workflow_state.json 的 batch 状态为 completed

用法:
    python update_test_load_two_phase.py \
        --workflow-state runs/ut-20260708/workflow_state.json \
        --batch-id batch_20260708_130000 \
        --batch-results runs/ut-20260708/batches/batch_20260708_130000/batch_results.json
"""

import os
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# NOTE: This imports from manifest-updater (higher-level module) to reuse
# the v5 merge logic. This is an intentional upward dependency -- the
# alternative (duplicating merge_batch_results) would violate DRY.
# manifest-updater uses hyphen (not importable as Python module)
# Load update_test_load.py via importlib from file path
import importlib.util
_utl_path = Path(__file__).parent.parent / "manifest-updater" / "scripts" / "update_test_load.py"
_spec = importlib.util.spec_from_file_location("update_test_load", _utl_path)
_utl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utl)
merge_batch_results = _utl.merge_batch_results
calculate_statistics = _utl.calculate_statistics


def update_test_load(test_load_path: Path, batch_results: dict, handled_tests: dict) -> int:
    """对test_load应用v5 merge

    Args:
        test_load_path: test_load_xxx.json路径
        batch_results: batch_results.json内容
        handled_tests: handled_tests.json内容

    Returns:
        更新的test数量
    """
    test_load = json.loads(test_load_path.read_text(encoding='utf-8'))

    # v5 merge: batch_results first, then handled_tests overrides
    updated_count = merge_batch_results(test_load, batch_results, handled_tests)
    # Recompute statistics after merge
    test_load['statistics'] = calculate_statistics(test_load.get('tests', []))

    # 更新时间戳
    test_load['updated_at'] = datetime.now().isoformat()

    # 写回
    test_load_path.write_text(
        json.dumps(test_load, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )

    stats = test_load.get('statistics', {})
    print(f'[OK] test_load updated: {updated_count} tests')
    print(f'     statistics: {stats}')
    return updated_count


def update_workflow_state(workflow_state_path: Path, batch_id: str, batch_results: dict):
    """更新workflow_state.json的batch状态为completed"""
    state = json.loads(workflow_state_path.read_text(encoding='utf-8'))

    if batch_id in state.get('batches', {}):
        state['batches'][batch_id]['status'] = 'completed'
        state['batches'][batch_id]['completed_at'] = datetime.now().isoformat()
        state['batches'][batch_id]['stats'] = batch_results.get('stats', {})

    # 重新计算batch_stats
    batch_stats = {'generated': 0, 'running': 0, 'completed': 0, 'failed': 0}
    for bid, binfo in state.get('batches', {}).items():
        status = binfo.get('status', 'generated')
        batch_stats[status] = batch_stats.get(status, 0) + 1
    state['batch_stats'] = batch_stats

    state['last_update'] = datetime.now().isoformat()
    workflow_state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    print(f'[OK] workflow_state updated: batch {batch_id} -> completed')


def main():
    parser = argparse.ArgumentParser(description='Batch完成后更新test_load和workflow_state')
    parser.add_argument('--workflow-state', required=True, help='workflow_state.json路径')
    parser.add_argument('--batch-id', required=True, help='batch ID')
    parser.add_argument('--batch-results', required=True, help='batch_results.json路径')
    parser.add_argument('--handled-tests', help='handled_tests.json路径（可选）')

    args = parser.parse_args()

    workflow_state_path = Path(args.workflow_state)
    state = json.loads(workflow_state_path.read_text(encoding='utf-8'))
    paths = state.get('paths', {})

    # 读取batch_results
    batch_results = json.loads(Path(args.batch_results).read_text(encoding='utf-8'))

    # 读取handled_tests（如果存在）
    handled_tests = {'tests': []}
    if args.handled_tests:
        ht_path = Path(args.handled_tests)
    else:
        # 从batch_dir推断
        batch_dir = Path(args.batch_results).parent
        ht_path = batch_dir / 'handled_tests.json'
    if ht_path.exists():
        handled_tests = json.loads(ht_path.read_text(encoding='utf-8'))

    # 1. 更新test_load
    test_load_path = paths.get('test_load', '')
    if test_load_path and Path(test_load_path).exists():
        update_test_load(Path(test_load_path), batch_results, handled_tests)
    else:
        print('[WARN] test_load path not found in workflow_state, skipping test_load update')

    # 2. 更新workflow_state
    update_workflow_state(workflow_state_path, args.batch_id, batch_results)


if __name__ == '__main__':
    main()
