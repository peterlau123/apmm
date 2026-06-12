"""
远程测试执行脚本
职责：通过 agent.py 在远程 H20 服务器执行 pytest
"""

import subprocess
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

# 配置 - 从脚本目录推断路径
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
AGENT_PY = PROJECT_DIR / "tools" / "agent.py"
AGENTS_DIR = PROJECT_DIR / ".agents"
STATUS_FILE = AGENTS_DIR / "unit-test-executor" / "status.json"
MESSAGES_FILE = AGENTS_DIR / "unit-test-executor" / "messages.jsonl"

# 远程配置（从 config.json 读取）
REMOTE_CONTAINER = "v0.13.0_torch2.5.1_compile"  # 正确的容器名
REMOTE_VLLM_PATH = "/gpfs/gcsp/M2.7_verify/vllm"


def get_container_name():
    """从 config.json 读取容器名称"""
    config_file = AGENTS_DIR / "config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            return config.get("paths", {}).get("test_container", REMOTE_CONTAINER)
        except:
            pass
    return REMOTE_CONTAINER


def read_json(file_path):
    """读取JSON文件"""
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def write_json(file_path, data):
    """写入JSON文件"""
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def send_message(msg_type, priority, data):
    """发送消息到messages.jsonl"""
    msg = {
        "type": msg_type,
        "priority": priority,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "unit-test-executor",
        "source": "remote_test_runner",
        "data": data
    }
    with open(MESSAGES_FILE, 'a', encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + '\n')


def run_remote_pytest(test_list, pytest_args="-q --tb=long", timeout=300):
    """
    通过 agent.py 在远程 H20 容器执行 pytest
    
    Args:
        test_list: 测试文件列表（相对路径）
        pytest_args: pytest 参数
        timeout: 执行超时（秒）
    
    Returns:
        dict: 执行结果
    """
    # 获取正确的容器名称
    container = get_container_name()
    
    # 构造测试路径（列表已含 tests/ 前缀，不再重复添加）
    test_paths = " ".join([t if t.startswith("tests/") else f"tests/{t}" for t in test_list])
    
    # pytest 命令（包含过滤规则）
    pytest_cmd = f"""cd {REMOTE_VLLM_PATH} && pytest {test_paths} \
        --ignore-glob="tests/**/rocm*" \
        --ignore-glob="tests/**/tpu*" \
        --ignore-glob="tests/**/multimodal*" \
        --ignore-glob="tests/**/nixl*" \
        --ignore-glob="tests/**/ec_connector*" \
        --ignore-glob="tests/**/*image*.py" \
        --ignore-glob="tests/**/*video*.py" \
        --ignore-glob="tests/**/*audio*" \
        --ignore-glob="tests/**/encoder*" \
        --ignore-glob="tests/**/prithvi*" \
        --ignore-glob="tests/distributed/*" \
        --ignore-glob="tests/v1/distributed/*" \
        --ignore-glob="tests/compile/distributed/*" \
        {pytest_args} 2>&1 | tee ut_logs/batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"""
    
    # Docker 内执行
    docker_cmd = f"sudo docker exec {container} bash -c '{pytest_cmd}'"
    
    # agent.py 命令
    agent_cmd = [
        sys.executable, str(AGENT_PY),
        "-p", "t_h20",
        "run",
        "--timeout", str(timeout),
        docker_cmd
    ]
    
    print(f"[INFO] Executing: {docker_cmd[:100]}...")
    
    result = {
        "command": docker_cmd[:200],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "timeout": timeout,
        "tests_count": len(test_list)
    }
    
    try:
        proc = subprocess.run(
            agent_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            cwd=str(PROJECT_DIR)
        )
        
        result["exit_code"] = proc.returncode
        result["stdout"] = proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout
        result["stderr"] = proc.stderr[-1000:] if len(proc.stderr) > 1000 else proc.stderr
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        
        # 解析 pytest 输出统计
        stdout = proc.stdout
        if "passed" in stdout:
            # 尝试提取统计
            import re
            summary_match = re.search(r'(\d+) passed', stdout)
            if summary_match:
                result["passed"] = int(summary_match.group(1))
            fail_match = re.search(r'(\d+) failed', stdout)
            if fail_match:
                result["failed"] = int(fail_match.group(1))
            skip_match = re.search(r'(\d+) skipped', stdout)
            if skip_match:
                result["skipped"] = int(skip_match.group(1))
        
        if proc.returncode == 0:
            result["status"] = "success"
        else:
            result["status"] = "completed_with_failures"
        
        return result
        
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = f"Command timeout after {timeout}s"
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def continue_tests(phase=1, pytest_args="-q --tb=long"):
    """
    继续执行测试（从上次中断处继续）
    
    Args:
        phase: Phase 编号
        pytest_args: pytest 参数
    """
    # 读取当前状态
    status = read_json(STATUS_FILE)
    progress = status.get("progress", {})
    completed = progress.get("completed_tests", 0)
    total = progress.get("total_tests", 6872)
    
    print(f"[INFO] Continuing Phase {phase}: {completed}/{total} tests done")
    
    # 更新状态
    status["test_status"] = "running"
    status["current_batch"] = f"continue_phase{phase}"
    write_json(STATUS_FILE, status)
    
    # 发送开始消息
    send_message("test_batch_started", "P2", {
        "phase": phase,
        "completed_before": completed,
        "total": total
    })
    
    # 获取待执行测试列表
    # 优先从远程获取测试列表文件
    test_list_path = PROJECT_DIR / "tasks" / "ut" / "ut_test_list.txt"
    remote_test_list_path = "/gpfs/gcsp/M2.7_verify/vllm/tests/ut_test_list.txt"
    
    batch_tests = []
    
    # 尝试读取本地测试列表
    if test_list_path.exists():
        all_tests = test_list_path.read_text(encoding="utf-8").strip().split('\n')
        remaining_tests = [t for t in all_tests if t.strip()][completed:]
        batch_tests = remaining_tests[:50]  # 每批次50个测试
        print(f"[INFO] Loaded {len(batch_tests)} tests from local list")
    else:
        # 尝试从远程获取测试列表
        try:
            # 通过 agent.py 获取远程测试列表
            list_cmd = f"sudo docker exec {get_container_name()} bash -c 'cat {remote_test_list_path} | head -n {completed + 50} | tail -n 50'"
            agent_cmd = [
                sys.executable, str(AGENT_PY),
                "-p", "t_h20",
                "run",
                list_cmd
            ]
            proc = subprocess.run(agent_cmd, capture_output=True, text=True, timeout=30, cwd=str(PROJECT_DIR))
            if proc.returncode == 0 and proc.stdout:
                batch_tests = [t.strip() for t in proc.stdout.strip().split('\n') if t.strip()]
                print(f"[INFO] Loaded {len(batch_tests)} tests from remote list")
        except Exception as e:
            print(f"[WARN] Failed to get remote test list: {e}")
    
    # 如果还是没有测试，使用默认测试文件列表
    if not batch_tests:
        # 从 vllm/tests 目录获取测试文件列表
        default_tests = [
            "test_config.py",
            "test_entrypoints.py", 
            "test_sampling.py",
            "test_seed_behavior.py",
            "test_llm_engine.py"
        ]
        batch_tests = default_tests[:5]
        print(f"[INFO] Using default test list: {batch_tests}")
    
    # 执行测试
    result = run_remote_pytest(batch_tests, pytest_args, timeout=600)
    
    # 更新进度
    if result.get("passed"):
        progress["passed_tests"] = progress.get("passed_tests", 0) + result.get("passed", 0)
    if result.get("failed"):
        progress["failed_tests"] = progress.get("failed_tests", 0) + result.get("failed", 0)
    if result.get("skipped"):
        progress["skipped_tests"] = progress.get("skipped_tests", 0) + result.get("skipped", 0)
    
    # 计算已完成
    batch_completed = (result.get("passed", 0) + result.get("failed", 0) + result.get("skipped", 0))
    progress["completed_tests"] = completed + batch_completed
    
    # 更新状态
    status["progress"] = progress
    status["test_status"] = "idle"
    status["current_batch"] = None
    status["last_batch_result"] = result
    write_json(STATUS_FILE, status)
    
    # 发送完成消息
    send_message("test_batch_completed", "P2", {
        "phase": phase,
        "batch_size": len(batch_tests),
        "passed": result.get("passed", 0),
        "failed": result.get("failed", 0),
        "skipped": result.get("skipped", 0),
        "total_completed": progress["completed_tests"],
        "status": result.get("status")
    })
    
    return result


def main():
    """主入口"""
    if len(sys.argv) < 2:
        print("Usage: python remote_test_runner.py [continue|batch] [--phase N] [--tests list]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "continue":
        phase = 1
        pytest_args = "-q --tb=long"
        
        # 解析参数
        for i, arg in enumerate(sys.argv[2:], 2):
            if arg == "--phase" and i + 1 < len(sys.argv):
                phase = int(sys.argv[i + 1])
            elif arg == "--pytest-args" and i + 1 < len(sys.argv):
                pytest_args = sys.argv[i + 1]
        
        result = continue_tests(phase, pytest_args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif command == "batch":
        # 执行指定批次
        tests = []
        pytest_args = "-q --tb=long"
        timeout = 300
        
        for i, arg in enumerate(sys.argv[2:], 2):
            if arg == "--tests" and i + 1 < len(sys.argv):
                tests = sys.argv[i + 1].split(',')
            elif arg == "--pytest-args" and i + 1 < len(sys.argv):
                pytest_args = sys.argv[i + 1]
            elif arg == "--timeout" and i + 1 < len(sys.argv):
                timeout = int(sys.argv[i + 1])
        
        if not tests:
            print("Error: --tests required for batch command")
            sys.exit(1)
        
        result = run_remote_pytest(tests, pytest_args, timeout)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()