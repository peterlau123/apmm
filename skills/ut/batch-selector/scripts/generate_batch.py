#!/usr/bin/env python3
"""生成下一批次测试清单

支持两种模式：
1. 从 workflow_state.json 读取路径（推荐）
2. 从命令行参数直接指定路径

输出到批次子目录：{run_dir}/batches/{batch_id}/batch_config.json

用法：
    python generate_batch.py --workflow-state PATH --batch-dir PATH
    python generate_batch.py --manifest-path PATH --batch-dir PATH
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import sys
import os

# Clear PYTHONPATH to avoid Hermes venv leaking into apmm subprocesses
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

# 先设置路径（确保 skills 包可被导入）
# scripts/ -> batch-selector/ -> ut/ -> skills/ -> apmm/ (项目根)
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 然后导入 shared 模块
from skills.ut.ut_common import validate_and_write, is_distributed
from skills.ut.ut_common.workflow_state_manager import (
    update_batch_generated,
    load_workflow_state as load_state_for_check
)


# v5 selection rules ------------------------------------------------------
STATUS_PRIORITY = {
    "pending": 1,
    "fixed_pending_verify": 2,
    "retriable_error": 3,
    "failed": 4,
}


def _is_selectable(test: dict) -> bool:
    """v5 selection rule: pending/fixed_pending_verify always selectable;
    retriable_error/failed selectable only while retry_count < max_retry.
    error / running / passed / ignored are NEVER selectable.
    """
    status = test.get("status", "pending")
    if status in ("pending", "fixed_pending_verify"):
        return True
    if status in ("retriable_error", "failed"):
        retry_count = test.get("retry_count", 0)
        max_retry = test.get("max_retry", 3)
        return retry_count < max_retry
    return False


def _selected_reason(test: dict) -> str:
    status = test.get("status", "pending")
    if status in ("retriable_error", "failed"):
        retry_count = test.get("retry_count", 0)
        max_retry = test.get("max_retry", 3)
        return f"{status} retry {retry_count}/{max_retry}"
    return status


def select_batch(manifest: dict, batch_size: int) -> list:
    """v5 batch selection: filter by selectability, sort by status priority,
    then take the first batch_size; each test gets a `selected_reason` field.
    """
    tests = manifest.get("tests", [])
    selectable = [t for t in tests if _is_selectable(t)]
    selectable.sort(key=lambda t: STATUS_PRIORITY.get(t.get("status", "pending"), 99))
    chosen = selectable[:batch_size]
    out = []
    for t in chosen:
        nt = dict(t)
        nt["selected_reason"] = _selected_reason(t)
        out.append(nt)
    return out


def write_batch_config(
    *,
    path: Path,
    batch_id: str,
    iteration: int,
    run_id: str,
    selected: list,
) -> dict:
    """Write batch_config.json with v5 fields: batch_id, iteration, run_id,
    selected_count, tests[{test_id, selected_reason, ...}].
    """
    path = Path(path)
    cfg = {
        "batch_id": batch_id,
        "iteration": iteration,
        "run_id": run_id,
        "selected_count": len(selected),
        "tests": selected,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


def load_workflow_state(workflow_state_path: Path) -> dict:
    """从 workflow_state.json 加载配置"""
    if not workflow_state_path.exists():
        print(json.dumps({"error": "workflow_state.json not found"}, indent=2))
        sys.exit(1)
    return json.loads(workflow_state_path.read_text(encoding="utf-8"))


def load_manifest(manifest_path: Path) -> dict:
    """加载 manifest.json"""
    if not manifest_path.exists():
        print(json.dumps({"error": f"manifest.json not found: {manifest_path}"}, indent=2))
        sys.exit(1)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def group_by_file(tests):
    """按 test_file 分组，减少 pytest 启动开销"""
    groups = defaultdict(list)
    for t in tests:
        groups[t["test_file"]].append(t)
    return dict(groups)


def generate_batch(
    manifest_path: Path,
    batch_dir: Path,
    batch_size: int = 50,
    skip_distributed: bool = False,
    test_file_filter: str = None,
    batch_id: str = None,
    workflow_state_path: Path = None
) -> dict:
    """生成下一批次测试清单

    Args:
        manifest_path: manifest.json 文件路径
        batch_dir: 批次目录路径（{run_dir}/batches/{batch_id}/）
        batch_size: 每批次测试数量
        skip_distributed: 是否跳过 distributed 测试
        test_file_filter: 文件过滤器
        batch_id: 批次ID（可选，默认自动生成）
        workflow_state_path: workflow_state.json 文件路径（可选，用于状态更新）

    Returns:
        批次配置 dict
    """
    manifest = load_manifest(manifest_path)

    # v5 selection: use select_batch() for proper retriable_error/failed handling
    candidates = select_batch(manifest, batch_size * 3)

    # Apply file filter
    if test_file_filter:
        candidates = [t for t in candidates if test_file_filter in t.get("test_file", "")]

    # Separate distributed and normal tests
    distributed = [t for t in candidates if is_distributed(t["test_node"])]
    normal = [t for t in candidates if not is_distributed(t["test_node"])]

    if batch_id is None:
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Strategy: normal batch first, distributed batch when no normal tests left
    if normal:
        # Normal batch: group by file, select up to batch_size
        grouped = group_by_file(normal)
        batch = []
        for file, tests in sorted(grouped.items()):
            batch.extend(tests)
            if len(batch) >= batch_size:
                break
        batch = batch[:batch_size]

        batch_config = {
            "batch_id": batch_id,
            "batch_type": "normal",
            "tests": batch,
            "distributed_count": 0,
            "requires_multi_gpu": False,
            "gpu_per_test": 1,
            "generated_at": datetime.now().isoformat(),
        }
    elif distributed and not skip_distributed:
        # Distributed batch: each test needs multiple GPUs (torchrun)
        batch = distributed[:batch_size]

        batch_config = {
            "batch_id": batch_id,
            "batch_type": "distributed",
            "tests": batch,
            "distributed_count": len(batch),
            "requires_multi_gpu": True,
            "gpu_per_test": 2,  # default: 2 GPUs per distributed test
            "generated_at": datetime.now().isoformat(),
        }
        print(f"[INFO] Distributed batch: {len(batch)} tests, 2 GPUs each")
    else:
        # No selectable tests
        if skip_distributed and distributed:
            raise ValueError(
                f"All {len(candidates)} candidates are distributed tests and "
                f"skip_distributed=True. Cannot form batch."
            )
        raise ValueError(
            f"Empty batch: no selectable tests from {len(candidates)} candidates"
        )

    if batch_dir:
        # 在batch_dir下创建batch_id子目录
        batch_dir = batch_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        output_path = batch_dir / "batch_config.json"
        # 校验后写入
        is_valid, errors = validate_and_write(batch_config, "batch_config", output_path)
        if not is_valid:
            return {"error": "schema_validation_failed", "details": errors}
        print(f"[OK] 批次清单已保存到: {output_path}")

    # Worker 返回给 Supervisor 的结果（统一格式）
    result = {
        "batch_id": batch_id,
        "batch_config_path": str(output_path) if batch_dir else None,
        "batch_dir": str(batch_dir) if batch_dir else None,
        # 标准统计格式
        "stats": {
            "passed": 0,
            "failed": 0,
            "error": 0,
            "ignored": 0,
            "pending": len(candidates) - len(batch[:batch_size])
        },
        "next_action": "continue",
        "error": None,
        "blocked_reason": None
    }

    # ── 更新 workflow_state.json（方案A + 三重保障）────────────
    if workflow_state_path and batch_dir:
        try:
            # 更新 batch 为 'generated' 状态
            update_batch_generated(
                workflow_state_path=workflow_state_path,
                batch_id=batch_id,
                batch_size=len(batch[:batch_size]),
                config_path=str(output_path),
                created_at=datetime.now().isoformat()
            )

            # ── 强制输出状态检查（防止Agent批量自动化）────────────
            print("=" * 60)
            print("STAGE COMPLETED: generate_batch")
            print(f"Batch ID: {batch_id}")
            print(f"Batch Size: {len(batch[:batch_size])}")
            print(f"Config Path: {output_path}")

            # 检查 workflow_state.json 是否成功更新
            state = load_state_for_check(workflow_state_path)
            if batch_id in state.get("batches", {}):
                batch_state = state["batches"][batch_id]
                print(f"Workflow State Updated: {batch_state['status']}")
                print(f"Batch Stats: generated={state['batch_stats']['generated']}")
            else:
                print("[WARN] Workflow State NOT UPDATED!")

            print("NEXT ACTION: execute_batch")
            print("=" * 60)
        except Exception as e:
            print(f"[ERROR] Failed to update workflow_state.json: {e}")
            # 不影响返回结果，继续返回

    return result


def generate_batch_from_workflow_state(
    workflow_state_path: Path,
    batch_dir: Path = None,
    batch_size: int = 50,
    skip_distributed: bool = False
) -> dict:
    """从 workflow_state.json 读取路径并生成批次

    自动更新 workflow_state.json 为 'generated' 状态
    """

    state = load_workflow_state(workflow_state_path)
    paths = state.get("paths", {})

    # test_load is the working dataset -- must exist, no fallback to manifest
    test_load_path = paths.get("test_load", "")
    if not test_load_path or not Path(test_load_path).exists():
        print(json.dumps({"error": "test_load path not found in workflow_state.json. Run generate_test_load.py first."}, indent=2))
        sys.exit(1)
    data_source_path = Path(test_load_path)
    print(f"[INFO] Reading from test_load: {data_source_path}")

    # 如果未指定 batch_dir，从 batches_dir 构建
    if batch_dir is None:
        batches_dir = paths.get("batches_dir", "")
        if batches_dir:
            batch_dir = Path(batches_dir)

    return generate_batch(
        manifest_path=data_source_path,
        batch_dir=batch_dir,
        batch_size=batch_size,
        skip_distributed=skip_distributed,
        workflow_state_path=workflow_state_path
    )


def main():
    parser = argparse.ArgumentParser(description="生成单元测试批次清单")

    parser.add_argument("--workflow-state", type=str, help="workflow_state.json 路径")
    parser.add_argument("--batch-dir", type=str, help="批次目录路径")
    parser.add_argument("--manifest-path", type=str, help="manifest.json 文件路径")
    parser.add_argument("--batch-size", type=int, default=50, help="每批次测试数量")
    parser.add_argument("--skip-distributed", action="store_true", help="跳过 distributed 测试")
    parser.add_argument("--test-file-filter", type=str, help="只选择特定文件路径的测试")
    parser.add_argument("--batch-id", type=str, help="指定批次ID")

    args = parser.parse_args()

    if args.workflow_state:
        workflow_state_path = Path(args.workflow_state)
        batch_dir = Path(args.batch_dir) if args.batch_dir else None
        result = generate_batch_from_workflow_state(
            workflow_state_path=workflow_state_path,
            batch_dir=batch_dir,
            batch_size=args.batch_size,
            skip_distributed=args.skip_distributed
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.manifest_path:
        manifest_path = Path(args.manifest_path)
        batch_dir = Path(args.batch_dir) if args.batch_dir else None
        result = generate_batch(
            manifest_path=manifest_path,
            batch_dir=batch_dir,
            batch_size=args.batch_size,
            skip_distributed=args.skip_distributed,
            test_file_filter=args.test_file_filter,
            batch_id=args.batch_id
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print(json.dumps({"error": "请指定 --workflow-state 或 --manifest-path"}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()