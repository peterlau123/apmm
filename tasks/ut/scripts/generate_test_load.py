#!/usr/bin/env python3
"""generate_test_load.py - 从manifest中抽取指定数量的test生成test_load清单

用途：
- 从manifest.json（collect产生）或manifest_source（用户指定）中抽取test
- 生成test_load_{count}_{timestamp}.json清单文件
- 供后续resume/retry使用

用法：
    python tasks/ut/scripts/generate_test_load.py \\
        --manifest-path runs/ut-20260708-123456/manifest.json \\
        --count 1000 \\
        --output-dir runs/ut-20260708-123456
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def generate_test_load(manifest_path: Path, count: int, output_dir: Path) -> Path:
    """从manifest中抽取指定数量的test生成test_load清单

    Args:
        manifest_path: manifest.json路径（collect产生或用户指定）
        count: 要抽取的test数量
        output_dir: 输出目录

    Returns:
        生成的test_load文件路径

    Raises:
        FileNotFoundError: manifest文件不存在
        ValueError: JSON解析失败
    """
    # 读取manifest（添加JSON错误处理）
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in manifest: {manifest_path}\n{e}")

    all_tests = manifest.get("tests", [])

    print(f"[INFO] Manifest包含 {len(all_tests)} 个test")

    # 优先级选择策略：pending → failed → error → passed/ignored
    def get_priority(test: dict) -> int:
        """返回test选择优先级（数字越小优先级越高）"""
        status = test.get("status", "pending")
        priority_map = {
            "pending": 0,   # 最高优先级
            "failed": 1,
            "error": 2,
            "passed": 3,
            "ignored": 4    # 最低优先级
        }
        return priority_map.get(status, 5)

    # 按优先级排序所有tests
    sorted_tests = sorted(all_tests, key=get_priority)

    # 选择指定数量
    selected_tests = sorted_tests[:count]

    # 计算实际选中的tests的statistics（而非硬编码）
    status_counts = {}
    for test in selected_tests:
        status = test.get("status", "pending")
        status_counts[status] = status_counts.get(status, 0) + 1

    # 确保statistics包含所有状态字段
    statistics = {
        "pending": status_counts.get("pending", 0),
        "passed": status_counts.get("passed", 0),
        "failed": status_counts.get("failed", 0),
        "error": status_counts.get("error", 0),
        "ignored": status_counts.get("ignored", 0)
    }

    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 生成文件名
    filename = f"test_load_{count}_{timestamp}.json"
    output_path = output_dir / filename

    # 构建test_load结构
    test_load = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "source": str(manifest_path),
        "total_tests": len(selected_tests),
        "tests": selected_tests,
        "statistics": statistics  # 使用实际计算的statistics
    }

    # 写入文件
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(test_load, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[OK] test_load清单已生成: {output_path}")
    print(f"     总数: {len(selected_tests)} test")
    print(f"     Statistics: {statistics}")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="生成test_load清单")
    parser.add_argument(
        "--manifest-path",
        required=True,
        help="manifest.json路径（collect产生或用户指定）"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="要抽取的test数量（默认1000）"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="输出目录"
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest_path)
    output_dir = Path(args.output_dir)

    test_load_path = generate_test_load(manifest_path, args.count, output_dir)

    # 输出路径供后续脚本使用
    print(f"\nTEST_LOAD_PATH={test_load_path}")


if __name__ == "__main__":
    main()