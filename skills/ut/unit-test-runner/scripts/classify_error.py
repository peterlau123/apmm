"""
Runner错误分类脚本
输出JSON结果，可选记录到issues.json
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
VLLM_UT_DIR = SCRIPT_DIR.parent.parent.parent / "vllm" / "2.5.1" / "ut"
ISSUES_FILE = VLLM_UT_DIR / "issues.json"

# 错误分类规则
ERROR_PATTERNS = {
    "C": {  # 代码Bug
        "name": "代码Bug",
        "patterns": [
            r"AssertionError",
            r"RuntimeError:.*vllm",
            r"ValueError:.*invalid",
        ]
    },
    "E": {  # 环境问题
        "name": "环境问题",
        "patterns": [
            r"OutOfMemoryError",
            r"CUDA out of memory",
            r"Resource temporarily unavailable",
            r"OOM",
        ]
    },
    "D": {  # 依赖缺失
        "name": "依赖缺失",
        "patterns": [
            r"ImportError:",
            r"ModuleNotFoundError:",
            r"No module named",
        ]
    },
    "P": {  # 平台兼容
        "name": "平台兼容",
        "patterns": [
            r"NotImplementedError",
            r"AttributeError:.*torch",
            r"Torch not compiled with",
        ]
    },
    "M": {  # 模型缺失
        "name": "模型缺失",
        "patterns": [
            r"Model not found",
            r"HF model download failed",
            r"hf_hub_download",
            r"Repository not found",
        ]
    },
    "S": {  # 跳过问题
        "name": "跳过问题",
        "patterns": [
            r"Skipped:",
            r"skip reason:",
            r"SKIP",
        ]
    },
}

def classify_error(error_message: str):
    """
    分类错误
    
    Returns:
        dict: {"category": "C/E/D/P/M/S", "name": "...", "matched_pattern": "..."}
    """
    for category, info in ERROR_PATTERNS.items():
        for pattern in info["patterns"]:
            if re.search(pattern, error_message, re.IGNORECASE):
                return {
                    "category": category,
                    "category_name": info["name"],
                    "matched_pattern": pattern,
                    "error_preview": error_message[:200],
                    "timestamp": datetime.now().isoformat()
                }
    
    return {
        "category": "U",
        "category_name": "未知类型",
        "error_preview": error_message[:200],
        "timestamp": datetime.now().isoformat()
    }

def record_issue(error_data: dict):
    """记录问题到issues.json"""
    try:
        issues = json.loads(ISSUES_FILE.read_text())
    except:
        issues = {"issues": [], "created_at": datetime.now().isoformat()}
    
    # 添加新问题
    issue_id = f"{error_data['category']}-{len(issues['issues']) + 1}"
    issues["issues"].append({
        "id": issue_id,
        "category": error_data["category"],
        "category_name": error_data["category_name"],
        "description": error_data["error_preview"],
        "matched_pattern": error_data.get("matched_pattern"),
        "status": "open",
        "first_seen": datetime.now().isoformat()
    })
    
    issues["last_updated"] = datetime.now().isoformat()
    ISSUES_FILE.parent.mkdir(parents=True, exist_ok=True)
    ISSUES_FILE.write_text(json.dumps(issues, indent=2))
    
    return issue_id

def main():
    parser = argparse.ArgumentParser(description="Runner错误分类脚本")
    parser.add_argument("--error", type=str, required=True, help="错误消息")
    parser.add_argument("--record", action="store_true", help="记录到issues.json")
    parser.add_argument("--test-file", type=str, default=None, help="测试文件")
    
    args = parser.parse_args()
    
    result = classify_error(args.error)
    
    if args.test_file:
        result["test_file"] = args.test_file
    
    if args.record:
        result["issue_id"] = record_issue(result)
        result["recorded"] = True
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()