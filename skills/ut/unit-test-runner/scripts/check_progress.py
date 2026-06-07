"""
Runner进度检查脚本
调用现有progress_tracker.py，输出JSON结果
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent / ".agents"
VLLM_UT_DIR = SCRIPT_DIR.parent.parent.parent / "vllm" / "2.5.1" / "ut"
MANIFEST_FILE = VLLM_UT_DIR / "test_manifest.json"

def check_progress():
    """
    检查测试进度
    
    Returns:
        dict: {"passed": N, "failed": N, "errors": [...], "completed": N, "total": N}
    """
    # 读取manifest
    if MANIFEST_FILE.exists():
        manifest = json.loads(MANIFEST_FILE.read_text())
        stats = manifest.get("statistics", {})
        tests = manifest.get("tests", [])
        
        completed = stats.get("passed", 0) + stats.get("failed", 0) + stats.get("error", 0)
        total = len(tests)
        
        # 获取最近失败
        recent_errors = []
        for t in tests[-100:]:
            if t.get("status") in ["failed", "error"]:
                recent_errors.append({
                    "test_id": t.get("id"),
                    "test_file": t.get("file"),
                    "status": t.get("status"),
                    "error_type": t.get("error_type", "unknown")
                })
        
        return {
            "completed": completed,
            "total": total,
            "passed": stats.get("passed", 0),
            "failed": stats.get("failed", 0),
            "error": stats.get("error", 0),
            "skipped": stats.get("skipped", 0),
            "progress_percent": round(completed / total * 100, 1) if total > 0 else 0,
            "recent_errors": recent_errors[:10],
            "timestamp": datetime.now().isoformat(),
            "source": "test_manifest.json"
        }
    else:
        return {
            "completed": 0,
            "total": 0,
            "error": "Manifest file not found",
            "timestamp": datetime.now().isoformat()
        }

def check_batch_progress(batch_id: str):
    """检查特定批次的进度"""
    log_dir = VLLM_UT_DIR / "ut_logs"
    
    # 查找日志文件
    log_file = None
    for phase_dir in log_dir.iterdir():
        if phase_dir.is_dir():
            for f in phase_dir.iterdir():
                if batch_id in f.name and f.suffix == ".log":
                    log_file = f
                    break
    
    if not log_file or not log_file.exists():
        return {"status": "not_found", "batch_id": batch_id}
    
    # 解析日志
    content = log_file.read_text(errors="ignore")
    passed = content.count("PASSED")
    failed = content.count("FAILED")
    error = content.count("ERROR")
    
    # 判断是否完成
    status = "running"
    if "===" in content and "passed" in content.lower():
        status = "completed"
    
    return {
        "batch_id": batch_id,
        "passed": passed,
        "failed": failed,
        "error": error,
        "status": status,
        "log_file": str(log_file),
        "log_size": len(content),
        "timestamp": datetime.now().isoformat()
    }

def main():
    parser = argparse.ArgumentParser(description="Runner进度检查脚本")
    parser.add_argument("--batch-id", type=str, default=None, help="批次ID")
    
    args = parser.parse_args()
    
    if args.batch_id:
        result = check_batch_progress(args.batch_id)
    else:
        result = check_progress()
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()