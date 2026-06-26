"""
check_resolved_cache.py - 检查已解决缓存脚本（L4 脚本统计）

职责：
- 从 manifest 读取 resolved_errors / resolved_failures
- 检查 error_key / failure_key 是否已解决
- 跳过重复处理，提高效率

用法：
    python check_resolved_cache.py --manifest PATH --error-key transformers
    python check_resolved_cache.py --manifest PATH --failure-key test_load:shape_mismatch
"""

import argparse
import json
from pathlib import Path


def load_manifest(manifest_path: Path) -> dict:
    """加载 manifest.json"""
    if not manifest_path.exists():
        return {"error": f"manifest.json not found: {manifest_path}"}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def check_error_resolved(manifest: dict, error_key: str) -> dict:
    """检查 error_key 是否已解决"""
    resolved_errors = manifest.get("resolved_errors", {})
    if error_key in resolved_errors:
        info = resolved_errors[error_key]
        return {"resolved": True, "resolved_at": info.get("resolved_at"), "type": info.get("type")}
    return {"resolved": False}


def check_failure_resolved(manifest: dict, failure_key: str) -> dict:
    """检查 failure_key 是否已解决"""
    resolved_failures = manifest.get("resolved_failures", {})
    if failure_key in resolved_failures:
        info = resolved_failures[failure_key]
        return {"resolved": True, "resolved_at": info.get("resolved_at"), "commit": info.get("commit")}
    return {"resolved": False}


def count_affected_tests(manifest: dict, error_key: str = None, failure_key: str = None) -> int:
    """统计受影响的测试数量"""
    count = 0
    for test in manifest.get("tests", []):
        if error_key:
            for error in test.get("errors", []):
                if error.get("error_key") == error_key:
                    count += 1
                    break
        if failure_key:
            for failure in test.get("failures", []):
                if failure.get("failure_key") == failure_key:
                    count += 1
                    break
    return count


def main():
    parser = argparse.ArgumentParser(description="check_resolved_cache")
    parser.add_argument("--manifest", type=str, required=True)
    parser.add_argument("--error-key", type=str)
    parser.add_argument("--failure-key", type=str)
    parser.add_argument("--count-affected", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(Path(args.manifest))
    if "error" in manifest:
        print(f"[ERROR] {manifest['error']}")
        return

    if args.error_key:
        result = check_error_resolved(manifest, args.error_key)
        if args.count_affected:
            result["affected_tests"] = count_affected_tests(manifest, error_key=args.error_key)
        print(json.dumps(result, indent=2))
    elif args.failure_key:
        result = check_failure_resolved(manifest, args.failure_key)
        if args.count_affected:
            result["affected_tests"] = count_affected_tests(manifest, failure_key=args.failure_key)
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({
            "resolved_errors_count": len(manifest.get("resolved_errors", {})),
            "resolved_failures_count": len(manifest.get("resolved_failures", {}))
        }, indent=2))


if __name__ == "__main__":
    main()