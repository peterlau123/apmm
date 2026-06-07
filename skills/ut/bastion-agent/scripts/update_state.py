"""
Bastion 状态更新脚本
更新.agents/bastion/status.json和心跳
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
STATUS_FILE = AGENTS_DIR / "bastion" / "status.json"
HEARTBEAT_FILE = AGENTS_DIR / "bastion" / "heartbeat.json"

def read_json(file_path):
    try:
        return json.loads(Path(file_path).read_text())
    except:
        return {}

def write_json(file_path, data):
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(json.dumps(data, indent=2))

def update_status(connection_status: dict = None, daemon_status: dict = None,
                  otp_status: dict = None, agent_status: str = None,
                  waiting_for_otp: bool = None):
    """更新Bastion状态"""
    
    status = read_json(STATUS_FILE)
    
    if not status:
        status = {
            "agent_id": "bastion",
            "agent_type": "claude-code",
            "status": "running",
            "started_at": datetime.now().isoformat()
        }
    
    if connection_status:
        status["bastion_status"] = connection_status
    
    if daemon_status:
        status["daemon_status"] = daemon_status
    
    if otp_status:
        status["otp_status"] = otp_status
    
    if agent_status:
        status["status"] = agent_status
    
    if waiting_for_otp is not None:
        status["waiting_for_otp"] = waiting_for_otp
    
    status["last_update"] = datetime.now().isoformat()
    
    write_json(STATUS_FILE, status)
    
    return {"updated": True, "file": str(STATUS_FILE)}

def update_heartbeat():
    """更新心跳"""
    heartbeat = {"timestamp": datetime.now().isoformat()}
    write_json(HEARTBEAT_FILE, heartbeat)
    return heartbeat

def main():
    parser = argparse.ArgumentParser(description="状态更新")
    parser.add_argument("--connection-status", type=str, help="连接状态JSON")
    parser.add_argument("--daemon-status", type=str, help="daemon状态JSON")
    parser.add_argument("--otp-status", type=str, help="OTP状态JSON")
    parser.add_argument("--status", type=str, help="Agent状态")
    parser.add_argument("--waiting-for-otp", type=str, help="等待OTP")
    parser.add_argument("--heartbeat", action="store_true", help="仅更新心跳")
    
    args = parser.parse_args()
    
    if args.heartbeat:
        result = update_heartbeat()
    else:
        connection_status = json.loads(args.connection_status) if args.connection_status else None
        daemon_status = json.loads(args.daemon_status) if args.daemon_status else None
        otp_status = json.loads(args.otp_status) if args.otp_status else None
        waiting_for_otp = args.waiting_for_otp == "true" if args.waiting_for_otp else None
        
        result = update_status(connection_status, daemon_status, otp_status,
                               args.status, waiting_for_otp)
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()