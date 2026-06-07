"""
Agent状态检查脚本
用于快速检查所有Agent的运行状态
"""

import json
from pathlib import Path
from datetime import datetime, timezone
import subprocess

AGENTS_DIR = Path("D:/workspace/apmm/.agents")

def parse_time(time_str):
    """解析时间字符串"""
    try:
        if '+' in time_str or time_str.endswith('Z'):
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            # 无时区的时间，可能是本地时间或UTC
            dt = datetime.fromisoformat(time_str)
            # 检查是否为未来时间（说明是本地时间而非UTC）
            now_utc = datetime.now(timezone.utc)
            if dt > now_utc.replace(tzinfo=None):
                # 是本地时间，转换为UTC（假设UTC+8）
                from datetime import timedelta
                dt = dt - timedelta(hours=8)
            return dt.replace(tzinfo=timezone.utc)
    except:
        return None

def get_elapsed_seconds(time_str):
    """计算距离现在多少秒"""
    dt = parse_time(time_str)
    if dt:
        return (datetime.now(timezone.utc) - dt).total_seconds()
    return None

def read_json(file_path):
    """读取JSON文件"""
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except:
        return {}

def check_agent_status(agent_name):
    """检查单个Agent状态"""
    agent_dir = AGENTS_DIR / agent_name
    status_file = agent_dir / "status.json"
    heartbeat_file = agent_dir / "heartbeat.json"
    
    status = read_json(status_file)
    heartbeat = read_json(heartbeat_file)
    
    # 计算心跳延迟
    elapsed = get_elapsed_seconds(heartbeat.get("timestamp"))
    
    return {
        "agent_name": agent_name,
        "status": status.get("status", "unknown"),
        "heartbeat_elapsed": elapsed,
        "heartbeat_source": heartbeat.get("source", "unknown"),
        "pid": heartbeat.get("pid"),
        "details": status
    }

def check_runner_progress():
    """检查Runner进度"""
    status = read_json(AGENTS_DIR / "unit-test-runner" / "status.json")
    progress = status.get("progress", {})
    
    return {
        "total_tests": progress.get("total_tests", 0),
        "completed_tests": progress.get("completed_tests", 0),
        "passed_tests": progress.get("passed_tests", 0),
        "failed_tests": progress.get("failed_tests", 0),
        "test_status": status.get("test_status", "unknown"),
        "phase": status.get("current_phase", 0),
        "batch": status.get("current_batch", None)
    }

def check_bastion_status():
    """检查Bastion连接状态"""
    status = read_json(AGENTS_DIR / "bastion" / "status.json")
    bastion_status = status.get("bastion_status", {})
    
    return {
        "t_h20": bastion_status.get("t_h20", {}).get("status", "unknown"),
        "t_ascend": bastion_status.get("t_ascend", {}).get("status", "unknown"),
        "daemon_running": status.get("daemon_status", {}).get("running", False)
    }

def check_environment_status():
    """检查Environment状态"""
    status = read_json(AGENTS_DIR / "environment" / "status.json")
    
    return {
        "gpu_healthy": status.get("gpu_status", {}).get("healthy", False),
        "container_healthy": status.get("container_status", {}).get("healthy", False),
        "disk_usage": status.get("disk_status", {}).get("used_percent", 0)
    }

def print_status_report():
    """打印状态报告"""
    print("=" * 60)
    print("Agent Status Report")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")
    print()
    
    # 1. Supervisor状态
    sup = check_agent_status("supervisor")
    print(f"[Supervisor]")
    print(f"  Status: {sup['status']}")
    print(f"  Heartbeat: {sup['heartbeat_elapsed']:.1f}s ago" if sup['heartbeat_elapsed'] else "  Heartbeat: N/A")
    print()
    
    # 2. Bastion状态
    bastion = check_agent_status("bastion")
    bastion_conn = check_bastion_status()
    print(f"[Bastion Agent]")
    print(f"  Status: {bastion['status']}")
    print(f"  t_h20: {bastion_conn['t_h20']}")
    print(f"  t_ascend: {bastion_conn['t_ascend']}")
    print(f"  Daemon: {'running' if bastion_conn['daemon_running'] else 'stopped'}")
    print(f"  Heartbeat: {bastion['heartbeat_elapsed']:.1f}s ago" if bastion['heartbeat_elapsed'] else "  Heartbeat: N/A")
    print()
    
    # 3. Environment状态
    env = check_agent_status("environment")
    env_status = check_environment_status()
    print(f"[Environment Agent]")
    print(f"  Status: {env['status']}")
    print(f"  GPU: {'healthy' if env_status['gpu_healthy'] else 'unhealthy'}")
    print(f"  Container: {'healthy' if env_status['container_healthy'] else 'unhealthy'}")
    print(f"  Disk: {env_status['disk_usage']}% used")
    print(f"  Heartbeat: {env['heartbeat_elapsed']:.1f}s ago" if env['heartbeat_elapsed'] else "  Heartbeat: N/A")
    print()
    
    # 4. Runner状态
    runner = check_agent_status("unit-test-runner")
    progress = check_runner_progress()
    print(f"[Unit Test Runner Agent]")
    print(f"  Status: {runner['status']}")
    print(f"  Test Status: {progress['test_status']}")
    print(f"  Progress: {progress['completed_tests']}/{progress['total_tests']}")
    print(f"  Passed: {progress['passed_tests']}, Failed: {progress['failed_tests']}")
    print(f"  Phase: {progress['phase']}, Batch: {progress['batch'] or 'N/A'}")
    print(f"  Loop PID: {runner['pid']}" if runner['pid'] else "  Loop PID: N/A")
    print(f"  Heartbeat: {runner['heartbeat_elapsed']:.1f}s ago" if runner['heartbeat_elapsed'] else "  Heartbeat: N/A")
    print()
    
    # 5. Runner Loop进程检查
    print(f"[Runner Loop Process]")
    loop_running = runner['heartbeat_source'] == 'runner_loop' and runner['heartbeat_elapsed'] and runner['heartbeat_elapsed'] < 30
    print(f"  Running: {'YES' if loop_running else 'NO'}")
    if runner['pid']:
        print(f"  PID: {runner['pid']}")
    print()
    
    # 6. 问题检测
    print("=" * 60)
    print("Issues Detected:")
    print("=" * 60)
    
    issues = []
    
    # 检查心跳超时
    for agent in ["supervisor", "bastion", "unit-test-runner", "environment"]:
        agent_status = check_agent_status(agent)
        elapsed = agent_status['heartbeat_elapsed']
        if elapsed and elapsed > 30:
            issues.append(f"⚠️ {agent}: heartbeat timeout ({elapsed:.1f}s)")
    
    # 检查Bastion连接
    if bastion_conn['t_h20'] != 'connected':
        issues.append(f"⚠️ t_h20: {bastion_conn['t_h20']}")
    if bastion_conn['t_ascend'] != 'connected':
        issues.append(f"⚠️ t_ascend: {bastion_conn['t_ascend']}")
    
    # 检查Environment健康
    if not env_status['gpu_healthy']:
        issues.append("⚠️ GPU: unhealthy")
    if not env_status['container_healthy']:
        issues.append("⚠️ Container: unhealthy")
    
    # 检查Runner Loop
    if not loop_running:
        issues.append("⚠️ runner_loop.py: not running")
    
    if issues:
        for issue in issues:
            print(issue)
    else:
        print("✓ No issues detected")
    
    print("=" * 60)

def get_status_json():
    """返回JSON格式的状态"""
    return {
        "timestamp": datetime.now().isoformat(),
        "supervisor": check_agent_status("supervisor"),
        "bastion": {**check_agent_status("bastion"), "connections": check_bastion_status()},
        "environment": {**check_agent_status("environment"), "health": check_environment_status()},
        "unit_test_runner": {
            **check_agent_status("unit-test-runner"),
            "progress": check_runner_progress()
        }
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.json:
        print(json.dumps(get_status_json(), indent=2))
    else:
        print_status_report()