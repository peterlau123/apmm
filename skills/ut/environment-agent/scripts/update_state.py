"""
Environment 状态更新脚本
更新.agents/environment/status.json和心跳
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
AGENTS_DIR = SCRIPT_DIR.parent.parent.parent.parent.parent / ".agents"
STATUS_FILE = AGENTS_DIR / "environment" / "status.json"
HEARTBEAT_FILE = AGENTS_DIR / "environment" / "heartbeat.json"

def read_json(file_path):
    try:
        return json.loads(Path(file_path).read_text())
    except:
        return {}

def write_json(file_path, data):
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(json.dumps(data, indent=2))

def update_status(gpu_status: dict = None, container_status: dict = None, 
                  disk_status: dict = None, download_status: dict = None, 
                  agent_status: str = None):
    """更新Environment状态"""
    
    status = read_json(STATUS_FILE)
    
    if not status:
        status = {
            "agent_id": "environment",
            "agent_type": "claude-code",
            "status": "running",
            "started_at": datetime.now().isoformat()
        }
    
    if gpu_status:
        status["gpu_status"] = gpu_status
    
    if container_status:
        status["container_status"] = container_status
    
    if disk_status:
        status["disk_status"] = disk_status
    
    if download_status:
        status["download_status"] = download_status
    
    if agent_status:
        status["status"] = agent_status
    
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
    parser.add_argument("--gpu-status", type=str, help="GPU状态JSON")
    parser.add_argument("--container-status", type=str, help="容器状态JSON")
    parser.add_argument("--disk-status", type=str, help="磁盘状态JSON")
    parser.add_argument("--download-status", type=str, help="下载状态JSON")
    parser.add_argument("--status", type=str, help="Agent状态")
    parser.add_argument("--heartbeat", action="store_true", help="仅更新心跳")
    
    args = parser.parse_args()
    
    if args.heartbeat:
        result = update_heartbeat()
    else:
        gpu_status = json.loads(args.gpu_status) if args.gpu_status else None
        container_status = json.loads(args.container_status) if args.container_status else None
        disk_status = json.loads(args.disk_status) if args.disk_status else None
        download_status = json.loads(args.download_status) if args.download_status else None
        
        result = update_status(gpu_status, container_status, disk_status, 
                               download_status, args.status)
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()