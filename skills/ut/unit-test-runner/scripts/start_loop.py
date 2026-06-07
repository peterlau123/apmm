#!/usr/bin/env python3
"""
Start Loop - 启动Runner后台进程
功能：
1. 检查runner_loop是否已运行
2. 启动runner_loop.py后台进程
3. 创建lock文件防止重复启动

使用：
  python start_loop.py              # 启动后台进程
  python start_loop.py --check      # 仅检查状态
"""

import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path("D:/workspace/apmm")
RUNNER_DIR = PROJECT_DIR / ".agents" / "unit-test-runner"
LOOP_SCRIPT = PROJECT_DIR / "skills/ut/unit-test-runner" / "runner_loop.py"
LOCK_FILE = RUNNER_DIR / "loop.lock"

def is_loop_running():
    """检查runner_loop是否已运行"""
    if LOCK_FILE.exists():
        # 读取PID并检查进程是否存活
        try:
            pid = int(LOCK_FILE.read_text().strip())
            import psutil
            proc = psutil.Process(pid)
            if proc.is_running():
                return True
        except:
            pass
    
    return False

def start_runner_loop():
    """启动后台进程"""
    if is_loop_running():
        print("[INFO] runner_loop already running")
        return True
    
    # 启动进程
    proc = subprocess.Popen(
        [sys.executable, str(LOOP_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    
    # 写入lock文件
    LOCK_FILE.write_text(str(proc.pid))
    
    print(f"[INFO] runner_loop started (PID: {proc.pid})")
    return True

def check_status():
    """检查状态"""
    if is_loop_running():
        print("✓ runner_loop is running")
    else:
        print("✗ runner_loop is not running")

def main():
    if "--check" in sys.argv:
        check_status()
    else:
        start_runner_loop()

if __name__ == "__main__":
    main()