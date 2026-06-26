"""
Dependency Resolver - 安装包脚本
在远程 t_ascend 上安装 Python 包
"""

import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
TOOLS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / "tools"

# 远程执行配置
AGENT_PY = TOOLS_DIR / "agent.py"
TARGET_SERVER = "t_ascend"  # 联网机器，用于下载依赖

def install_package_on_remote(
    package_name: str,
    version: str = None,
    use_mirror: bool = False
) -> dict:
    """
    在远程 t_ascend 上安装 Python 包
    
    Args:
        package_name: 包名
        version: 版本（可选）
        use_mirror: 是否使用镜像源
        
    Returns:
        dict: 安装结果
    """
    # 构建 pip install 命令
    if version:
        pkg_spec = f"{package_name}=={version}"
    else:
        pkg_spec = package_name
    
    pip_cmd = f"pip install {pkg_spec}"
    
    # 使用镜像源
    if use_mirror:
        pip_cmd = f"pip install {pkg_spec} -i https://pypi.tuna.tsinghua.edu.cn/simple"
    
    # 通过 agent.py 在远程执行
    full_cmd = f"python {AGENT_PY} -p {TARGET_SERVER} run --timeout 120 \"{pip_cmd}\""
    
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(TOOLS_DIR)
        )
        
        # 检查安装结果
        if result.returncode == 0 and "Successfully installed" in result.stdout:
            return {
                "success": True,
                "package": package_name,
                "version": version,
                "output": result.stdout,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "success": False,
                "package": package_name,
                "version": version,
                "error": result.stderr or result.stdout,
                "timestamp": datetime.now().isoformat()
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "package": package_name,
            "error": "Installation timed out",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "package": package_name,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def send_download_result(package_name: str, success: bool, error: str = None) -> dict:
    """
    发送下载结果到 supervisor inbox
    
    Args:
        package_name: 包名
        success: 是否成功
        error: 错误信息（可选）
        
    Returns:
        dict: 发送结果
    """
    supervisor_inbox = AGENTS_DIR / "supervisor" / "inbox.jsonl"
    
    msg_type = "download_success" if success else "download_failed"
    
    message = {
        "type": msg_type,
        "from": "dependency-resolver",
        "priority": "P1",
        "data": {
            "package": package_name,
            "success": success,
            "error": error,
            "action": "dependency_resolved" if success else "retry_needed"
        },
        "timestamp": datetime.now().isoformat()
    }
    
    supervisor_inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(supervisor_inbox, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
    
    return {
        "success": True,
        "inbox_path": str(supervisor_inbox)
    }

def main():
    parser = argparse.ArgumentParser(description="Dependency Resolver - 安装包")
    parser.add_argument("--package", type=str, required=True, help="包名")
    parser.add_argument("--version", type=str, default=None, help="版本")
    parser.add_argument("--mirror", action="store_true", help="使用镜像源")
    parser.add_argument("--notify", action="store_true", help="发送通知到 supervisor")
    
    args = parser.parse_args()
    
    # 安装包
    result = install_package_on_remote(args.package, args.version, args.mirror)
    
    if result["success"]:
        print(f"[OK] Installed: {args.package}")
    else:
        print(f"[ERROR] Failed to install: {args.package}")
        print(f"  - Error: {result.get('error', 'Unknown')}")
    
    # 发送通知
    if args.notify:
        send_download_result(
            args.package,
            result["success"],
            result.get("error")
        )
        print(f"[OK] Notification sent to supervisor")
    
    # 输出结果
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()