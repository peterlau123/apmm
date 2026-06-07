"""
Environment Python包下载脚本
在t_ascend下载Python包到/gpfs共享存储
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent.parent / "agent.py"

# Python包下载路径
DEPS_PATH = "/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/dependencies"

def download_package(package_name: str, timeout: int = 600):
    """
    下载Python包
    
    Args:
        package_name: 包名称，如 "torch" 或 "transformers==4.40.0"
        timeout: 下载超时（秒）
    
    Returns:
        dict: {"status": "success/error", ...}
    """
    if not AGENT_PY.exists():
        return {
            "status": "error",
            "error": "agent.py not found",
            "package": package_name,
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        # 构造下载命令
        download_cmd = f"""
mkdir -p {DEPS_PATH}
pip download {package_name} -d {DEPS_PATH}
"""
        
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_ascend", "run",
             "--timeout", str(timeout),
             download_cmd],
            capture_output=True, text=True, timeout=timeout + 60
        )
        
        if result.returncode == 0:
            return {
                "status": "success",
                "package": package_name,
                "path": DEPS_PATH,
                "output": result.stdout[:500],
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "error",
                "package": package_name,
                "error": result.stderr[:500] if result.stderr else result.stdout[:500],
                "timestamp": datetime.now().isoformat()
            }
            
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "package": package_name,
            "error": f"Download timeout after {timeout}s",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "error",
            "package": package_name,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def list_downloaded_packages():
    """
    列出已下载的包
    
    Returns:
        dict: {"packages": [...], "path": "..."}
    """
    result = subprocess.run(
        [sys.executable, str(AGENT_PY), "-p", "t_ascend", "run",
         "--timeout", "30",
         f"ls {DEPS_PATH}/ 2>/dev/null | head -20"],
        capture_output=True, text=True, timeout=60
    )
    
    packages = []
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if line:
                packages.append(line)
    
    return {
        "packages": packages,
        "count": len(packages),
        "path": DEPS_PATH,
        "timestamp": datetime.now().isoformat()
    }

def main():
    parser = argparse.ArgumentParser(description="Python包下载")
    parser.add_argument("--package", type=str, default=None, help="包名称")
    parser.add_argument("--timeout", type=int, default=600, help="超时秒数")
    parser.add_argument("--list", action="store_true", help="列出已下载包")
    
    args = parser.parse_args()
    
    if args.list:
        result = list_downloaded_packages()
    elif args.package:
        result = download_package(args.package, args.timeout)
    else:
        result = {"error": "Please specify --package or --list"}
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()