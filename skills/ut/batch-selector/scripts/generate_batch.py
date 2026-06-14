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

# 先设置路径（确保 skills 包可被导入）
# scripts/ -> batch-selector/ -> ut/ -> skills/ -> apmm/ (项目根)
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 然后导入 shared 模块
from skills.ut.shared import validate_and_write, is_distributed


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
    batch_id: str = None
) -> dict:
    """生成下一批次测试清单

    Args:
        manifest_path: manifest.json 文件路径
        batch_dir: 批次目录路径（{run_dir}/batches/{batch_id}/）
        batch_size: 每批次测试数量
        skip_distributed: 是否跳过 distributed 测试
        test_file_filter: 文件过滤器
        batch_id: 批次ID（可选，默认自动生成）

    Returns:
        批次配置 dict
    """
    manifest = load_manifest(manifest_path)

    # 过滤 pending + fixed_pending_verify 测试（验证批次优先）
    # 优先级：fixed_pending_verify > pending（确保修复后验证闭环）
    fixed_pending_verify = [t for t in manifest['tests'] if t.get('status') == 'fixed_pending_verify']
    pending_tests = [t for t in manifest['tests'] if t.get('status') == 'pending']

    # 合并候选测试，验证批次在前
    candidates = fixed_pending_verify + pending_tests

    # 应用文件过滤器
    if test_file_filter:
        candidates = [t for t in candidates if test_file_filter in t.get('test_file', '')]

    # 分离 distributed 和 normal
    if skip_distributed:
        candidates = [t for t in candidates if not is_distributed(t['test_node'])]

    distributed = [t for t in candidates if is_distributed(t['test_node'])]
    normal = [t for t in candidates if not is_distributed(t['test_node'])]

    # 按文件分组
    grouped = group_by_file(normal)

    # 选择测试
    batch = []
    if batch_id is None:
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    for file, tests in sorted(grouped.items()):
        batch.extend(tests)
        if len(batch) >= batch_size:
            break

    # batch_config.json 内容（写入文件）
    batch_config = {
        "batch_id": batch_id,
        "tests": batch[:batch_size],
        "distributed_count": len(distributed),
        "requires_multi_gpu": len(distributed) > 0,
        "generated_at": datetime.now().isoformat()
    }

    # 如果有 distributed 测试，输出提示
    if distributed:
        batch_config["distributed_tests"] = [
            {"test_node": t["test_node"], "id": t["id"]}
            for t in distributed[:10]
        ]
        batch_config["note"] = "distributed tests require GPU >= 2"

    # 创建批次目录并写入输出文件（校验后写入）
    if batch_dir:
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

    return result


def generate_batch_from_workflow_state(
    workflow_state_path: Path,
    batch_dir: Path = None,
    batch_size: int = 50,
    skip_distributed: bool = False
) -> dict:
    """从 workflow_state.json 读取路径并生成批次"""

    state = load_workflow_state(workflow_state_path)
    paths = state.get("paths", {})

    manifest_path = Path(paths.get("manifest", ""))

    if not manifest_path:
        print(json.dumps({"error": "manifest path not found in workflow_state.json"}, indent=2))
        sys.exit(1)

    # 如果未指定 batch_dir，从 batches_dir 构建
    if batch_dir is None:
        batches_dir = paths.get("batches_dir", "")
        if batches_dir:
            batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            batch_dir = Path(batches_dir) / batch_id

    return generate_batch(
        manifest_path=manifest_path,
        batch_dir=batch_dir,
        batch_size=batch_size,
        skip_distributed=skip_distributed
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