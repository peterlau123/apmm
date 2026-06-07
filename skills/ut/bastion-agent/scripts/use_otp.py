"""
Bastion OTP使用脚本
使用OTP验证码执行SSH重启
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENT_PY = SCRIPT_DIR.parent.parent.parent.parent / "agent.py"

def use_otp(otp_code: str, target: str = "all"):
    """
    使用OTP执行SSH重启
    
    Args:
        otp_code: OTP验证码（6位数字）
        target: 目标机器
    
    Returns:
        dict: {"status": "success/error/expired", ...}
    
    注意：实际SSH重启命令需要根据堡垒机配置实现
    当前为示意性实现，等待实际SSH配置后完善
    """
    # OTP有效期约30秒
    # 实际SSH重启逻辑需要根据堡垒机类型实现
    
    # 部分隐藏OTP显示
    otp_hidden = otp_code[:2] + "****"
    
    # 当前为示意性实现
    # TODO: 根据实际堡垒机（齐治Shterm）配置实现SSH重启
    
    return {
        "status": "pending_implementation",
        "otp_used": otp_hidden,
        "target": target,
        "note": "SSH restart command needs to be implemented based on bastion configuration",
        "timestamp": datetime.now().isoformat()
    }

def check_ssh_status():
    """
    检查SSH连接状态
    
    Returns:
        dict: {"ssh_active": bool, ...}
    """
    if not AGENT_PY.exists():
        return {
            "ssh_active": False,
            "error": "agent.py not found",
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        result = subprocess.run(
            [sys.executable, str(AGENT_PY), "-p", "t_h20", "ping"],
            capture_output=True, text=True, timeout=10
        )
        
        return {
            "ssh_active": result.returncode == 0,
            "output": result.stdout[:100],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "ssh_active": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def main():
    parser = argparse.ArgumentParser(description="OTP使用")
    parser.add_argument("--otp", required=True, help="OTP验证码")
    parser.add_argument("--target", default="all", help="目标机器")
    parser.add_argument("--check-status", action="store_true", help="仅检查SSH状态")
    
    args = parser.parse_args()
    
    if args.check_status:
        result = check_ssh_status()
    else:
        result = use_otp(args.otp, args.target)
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()