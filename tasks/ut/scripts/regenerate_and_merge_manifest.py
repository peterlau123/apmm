#!/usr/bin/env python3
"""
regenerate_and_merge_manifest.py

功能:
  1. 从 test_list 文件解析测试节点, 生成 v2.0 manifest.json (新 collect)
  2. 按精确 test_node 匹配, 把旧 manifest 的执行状态合并进新 manifest
     - 精确匹配 (含 [] 内模型名完全一致) -> 拷贝旧状态
     - 不匹配 (例如 [] 内模型被替换, test_node 已变) -> 保留新 manifest 的 pending
  3. 重算 statistics 并写回
  4. 用 manifest_schema.json 校验

设计说明:
  - collect.py 生成的是 v1.0 旧格式 (无 id/statistics), 无法直接用, 这里手写 v2.0 生成
  - test_list 文件含 pytest collect 输出头尾 (如 "Running N items", "N tests collected"),
    需过滤只保留 "tests/...::..." 行
  - 匹配键: test_node 整串精确匹配. 模型名是 test_node 的一部分 (在 [] 内),
    模型被替换 -> test_node 不同 -> 不匹配 -> 保留 pending (符合用户要求)

用法:
  python tasks/ut/scripts/regenerate_and_merge_manifest.py \
      --test-list tasks/ut/dataset/ut_test_list_full_20260718_174239.txt \
      --old-manifest runs/ut-20260716-221134/manifest.json \
      --output <新manifest输出路径>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ponytail: 复用项目内 schema 校验, 不引入新依赖
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "skills" / "ut" / "ut_common"))
from validate_schema import validate_and_write  # noqa: E402


# ── 1. 解析 test_list ──────────────────────────────────────────────
# 合法测试节点: 以 tests/ 开头, 含 :: 分隔符. 排除 collect 输出的杂行.
_TEST_NODE_RE = re.compile(r"^tests/.+::.+$")


def parse_test_list(test_list_path: Path) -> list[str]:
    """从 test_list 文件解析测试节点列表 (过滤 pytest collect 头尾杂行)."""
    nodes: list[str] = []
    seen: set[str] = set()
    with open(test_list_path, encoding="utf-8") as f:
        for line in f:
            node = line.strip()
            if not node:
                continue
            if not _TEST_NODE_RE.match(node):
                continue
            # 去重 (保持顺序)
            if node in seen:
                continue
            seen.add(node)
            nodes.append(node)
    return nodes


# ── 2. 生成 v2.0 manifest ─────────────────────────────────────────
def split_node(node: str) -> tuple[str, str]:
    """tests/foo.py::TestBar::test_baz -> ('tests/foo.py', 'test_baz')"""
    parts = node.split("::")
    test_file = parts[0] if parts else ""
    test_name = parts[-1] if len(parts) > 1 else ""
    return test_file, test_name


def build_new_manifest(nodes: list[str]) -> dict:
    """构建 v2.0 manifest, 全部 pending."""
    tests = []
    for idx, node in enumerate(nodes, start=1):
        test_file, test_name = split_node(node)
        tests.append({
            "id": idx,
            "test_node": node,
            "test_file": test_file,
            "test_name": test_name,
            "status": "pending",
            "priority": "P2",
            "batch_id": None,
            "last_batch_id": None,
            "run_count": 0,
            "retry_count": 0,
            "max_retry": 3,
            "last_run_at": None,
            "last_duration_ms": None,
            "last_exit_code": None,
            "error_type": None,
            "error_message": None,
            "ignored_reason": None,
            "fix_applied": False,
            "fix_details": None,
            "log_file": None,
            "errors": [],
            "failures": [],
        })
    return {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "test_list_file",
        "tests": tests,
    }


# ── 3. 合并旧状态 ─────────────────────────────────────────────────
# 精确 test_node 匹配时拷贝的执行状态字段 (这些是"这个测试跑过"的痕迹).
# 注意: id/test_node/test_file/test_name 保持新 manifest 的值, 不覆盖.
_MERGE_FIELDS = [
    "status", "priority", "batch_id", "last_batch_id",
    "run_count", "retry_count", "max_retry",
    "last_run_at", "last_duration_ms", "last_exit_code",
    "error_type", "error_message", "ignored_reason",
    "fix_applied", "fix_details", "log_file",
    "errors", "failures",
]


def merge_old_status(new_manifest: dict, old_manifest: dict) -> dict:
    """按精确 test_node 匹配, 把旧 manifest 的执行状态合并进新 manifest.

    返回: {"matched": N, "unmatched_new": N, "unmatched_old": N}
    """
    old_by_node = {t["test_node"]: t for t in old_manifest.get("tests", [])}
    matched = 0
    for t in new_manifest["tests"]:
        old_t = old_by_node.get(t["test_node"])
        if old_t is None:
            continue  # 新测试或模型被替换 -> 保留 pending
        matched += 1
        for f in _MERGE_FIELDS:
            if f in old_t:
                t[f] = old_t[f]
    unmatched_old = len(old_by_node) - matched
    return {
        "matched": matched,
        "unmatched_new": len(new_manifest["tests"]) - matched,
        "unmatched_old": unmatched_old,
    }


# ── 4. 重算 statistics ────────────────────────────────────────────
def compute_statistics(tests: list[dict]) -> dict:
    """根据 tests 的 status 重算 statistics (对齐旧 manifest 字段集)."""
    c = Counter(t["status"] for t in tests)
    total = len(tests)
    passed = c.get("passed", 0)
    failed = c.get("failed", 0)
    error = c.get("error", 0)
    ignored = c.get("ignored", 0)
    retriable = c.get("retriable_error", 0)
    fixed_pv = c.get("fixed_pending_verify", 0)
    pending = c.get("pending", 0)
    running = c.get("running", 0)
    executed = passed + failed + error + ignored + retriable + fixed_pv
    return {
        "pending": pending,
        "passed": passed,
        "failed": failed,
        "error": error,
        "ignored": ignored,
        "retriable_error": retriable,
        "fixed_pending_verify": fixed_pv,
        "total": total,
        "executed": executed,
        "progress": round(executed / total * 100, 2) if total else 0.0,
    }


# ── 5. 主流程 ─────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="重新生成 manifest 并合并旧状态")
    ap.add_argument("--test-list", required=True, help="test_list 文件路径")
    ap.add_argument("--old-manifest", required=True, help="旧 manifest.json 路径")
    ap.add_argument("--output", required=True, help="输出 manifest.json 路径")
    args = ap.parse_args()

    test_list_path = Path(args.test_list)
    old_manifest_path = Path(args.old_manifest)
    output_path = Path(args.output)

    # 1. 解析 test_list
    nodes = parse_test_list(test_list_path)
    print(f"[1/5] 解析 test_list: {len(nodes)} 个测试节点 ({test_list_path})")
    if not nodes:
        print("[ERROR] 未解析到任何测试节点")
        return 1

    # 2. 生成新 manifest (全 pending, v2.0)
    new_manifest = build_new_manifest(nodes)

    # 3. 合并旧状态
    old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
    stats = merge_old_status(new_manifest, old_manifest)
    print(f"[2/5] 合并旧状态: 精确匹配 {stats['matched']}, "
          f"新manifest未匹配 {stats['unmatched_new']}, "
          f"旧manifest未匹配 {stats['unmatched_old']}")

    # 4. 重算 statistics
    new_manifest["statistics"] = compute_statistics(new_manifest["tests"])
    new_manifest["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_manifest["merged_from_run"] = str(old_manifest_path.parent.name)
    new_manifest["merge_strategy"] = "exact_test_node_match_keep_new_on_model_change"
    print(f"[3/5] statistics: {json.dumps(new_manifest['statistics'], ensure_ascii=False)}")

    # 5. schema 校验后写入
    ok, errors = validate_and_write(new_manifest, "manifest", output_path)
    if not ok:
        print(f"[ERROR] schema 校验失败:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[4/5] schema 校验通过, 已写入: {output_path}")

    # 摘要
    c = Counter(t["status"] for t in new_manifest["tests"])
    print(f"[5/5] 完成. {len(new_manifest['tests'])} 测试, 状态分布: {dict(c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
