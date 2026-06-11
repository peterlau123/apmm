"""
Runner批次执行脚本

支持两种模式：
1. 从 workflow_state.json 读取路径（推荐）
2. 从命令行参数直接指定配置

调用现有batch_test_runner.py，输出JSON结果

新增功能：
- 远程日志提取：通过 bastion grep 提取 PASSED/FAILED/ERROR 行
- 本地解析：调用 parse_remote_log.py 生成 batch_results.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Bastion agent.py 路径
AGENT_PY = Path(__file__).parent.parent.parent.parent / "tools" / "agent.py"


def load_workflow_state(workflow_state_path: Path) -> dict:
    """从 workflow_state.json 加载配置"""
    if not workflow_state_path.exists():
        return {"error": f"workflow_state.json not found: {workflow_state_path}"}
    return json.loads(workflow_state_path.read_text(encoding="utf-8"))


def run_batch(
    worker: int, 
    tests: list, 
    phase: int, 
    round: int, 
    timeout: int = 120,
    workflow_state_path: Path = None
) -> dict:
    """
    启动pytest批次执行
    
    Args:
        worker: Worker编号 (1-3)
        tests: 测试列表
        phase: Phase编号
        round: Round编号
        timeout: 超时秒数
        workflow_state_path: workflow_state.json 路径（用于读取远程配置）
        
    Returns:
        dict: {"status": "started", "pids": [...], "log_file": "..."}
    """
    # GPU分配
    gpu_map = {1: "0,1", 2: "2,3", 3: "4,5"}
    cuda_devices = gpu_map.get(worker, "0,1")
    
    # 构造batch_id
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_id = f"batch_p{phase}_r{round}_w{worker}_{timestamp}"
    
    # 从 workflow_state.json 读取远程配置（如果提供）
    remote_server = "t_h20"
    docker_container = "v0.13.0_torch2.5.1_compile"
    vllm_dir = "/gpfs/gcsp/M2.7_verify/vllm"
    ut_logs_dir = f"{vllm_dir}/ut_logs"
    
    if workflow_state_path:
        state = load_workflow_state(workflow_state_path)
        if "error" not in state:
            # 从 workflow.yaml 配置读取远程服务器信息（如果有）
            # 这里暂时使用默认值，后续可以扩展从 workflow.yaml 读取
            pass
    
    log_file = f"{ut_logs_dir}/phase{phase}/{batch_id}.log"
    
    result = {
        "batch_id": batch_id,
        "worker": worker,
        "phase": phase,
        "round": round,
        "cuda_devices": cuda_devices,
        "tests": tests,
        "tests_count": len(tests),
        "timeout": timeout,
        "log_file": log_file,
        "remote_server": remote_server,
        "docker_container": docker_container,
        "started_at": datetime.now().isoformat()
    }
    
    # 查找 batch_test_runner.py
    script_dir = Path(__file__).parent
    batch_runner = script_dir / "batch_test_runner.py"
    
    if batch_runner.exists():
        # 构造命令
        test_str = " ".join(tests)
        cmd = [
            sys.executable, str(batch_runner),
            "--tests", test_str,
            "--worker", str(worker),
            "--cuda-devices", cuda_devices,
            "--timeout", str(timeout),
            "--log-file", log_file,
            "--background"
        ]
        
        try:
            proc_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc_result.returncode == 0:
                result["status"] = "started"
                result["output"] = proc_result.stdout[:500]
            else:
                result["status"] = "error"
                result["error"] = proc_result.stderr[:500]
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            result["error"] = "Command timeout after 30s"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
    else:
        # 脚本不存在，返回模拟结果
        result["status"] = "mock"
        result["message"] = "batch_test_runner.py not found, returning mock result"
    
    return result


def extract_remote_log(
    log_file: str,
    profile: str = "default",
    timeout: int = 60
) -> str:
    """
    通过 bastion 从远程容器提取日志摘要

    Args:
        log_file: 远程日志文件路径 (e.g., /gpfs/.../ut_logs/phase1/batch_001.log)
        profile: agent.py profile 名称
        timeout: 超时秒数

    Returns:
        grep 输出内容（PASSED/FAILED/ERROR 行）
    """
    # 构造 grep 命令
    grep_cmd = f"grep -E '(PASSED|FAILED|ERROR|SKIPPED)' {log_file}"

    # 调用 agent.py run
    cmd = [
        sys.executable, str(AGENT_PY),
        "--profile", profile,
        "run",
        "--timeout", str(timeout),
        grep_cmd
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        if result.returncode == 0:
            return result.stdout
        else:
            # grep 没找到匹配时返回 exit code 1，但 stderr 为空
            if result.returncode == 1 and not result.stderr:
                return ""  # 无匹配内容
            return f"ERROR: {result.stderr}"
    except subprocess.TimeoutExpired:
        return "ERROR: Timeout while extracting remote log"
    except Exception as e:
        return f"ERROR: {e}"


def parse_batch_results(
    grep_output: str,
    batch_id: str,
    log_file: str,
    output_path: Path
) -> dict:
    """
    解析 grep 输出，生成 batch_results.json

    Args:
        grep_output: grep 提取的内容
        batch_id: 批次 ID
        log_file: 远程日志文件路径
        output_path: 输出文件路径

    Returns:
        解析结果 dict
    """
    if grep_output.startswith("ERROR:"):
        return {
            "status": "error",
            "error": grep_output,
            "batch_id": batch_id
        }

    # 调用 parse_remote_log.py
    parse_script = Path(__file__).parent / "parse_remote_log.py"

    if not parse_script.exists():
        return {
            "status": "error",
            "error": "parse_remote_log.py not found",
            "batch_id": batch_id
        }

    cmd = [
        sys.executable, str(parse_script),
        "--stdin",
        "--batch-id", batch_id,
        "--output", str(output_path),
        "--remote-log", log_file
    ]

    try:
        result = subprocess.run(
            cmd,
            input=grep_output,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # 读取生成的 batch_results.json
            if output_path.exists():
                batch_results = json.loads(output_path.read_text(encoding="utf-8"))
                return {
                    "status": "success",
                    "batch_results": batch_results
                }
            else:
                return {
                    "status": "error",
                    "error": "batch_results.json not generated",
                    "batch_id": batch_id
                }
        else:
            return {
                "status": "error",
                "error": result.stderr,
                "batch_id": batch_id
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "batch_id": batch_id
        }


def run_batch_with_results(
    worker: int,
    tests: list,
    phase: int,
    round: int,
    timeout: int = 120,
    workflow_state_path: Path = None,
    output_dir: Path = None,
    profile: str = "default"
) -> dict:
    """
    启动 pytest 执行，并在完成后提取解析结果

    这是 run_batch() 的增强版本，在 pytest 完成后：
    1. 从远程日志 grep 提取 PASSED/FAILED/ERROR 行
    2. 调用 parse_remote_log.py 解析
    3. 生成 batch_results.json

    Args:
        worker: Worker编号 (1-3)
        tests: 测试列表
        phase: Phase编号
        round: Round编号
        timeout: pytest 超时秒数
        workflow_state_path: workflow_state.json 路径
        output_dir: batch_results.json 输出目录
        profile: agent.py profile 名称

    Returns:
        dict: {"status": "...", "batch_results": {...}, "log_file": "..."}
    """
    # 1. 启动 pytest（使用现有 run_batch 函数）
    start_result = run_batch(
        worker=worker,
        tests=tests,
        phase=phase,
        round=round,
        timeout=timeout,
        workflow_state_path=workflow_state_path
    )

    if start_result.get("status") not in ("started", "mock"):
        return start_result  # 启动失败，直接返回

    batch_id = start_result.get("batch_id")
    log_file = start_result.get("log_file")

    # 2. 等待 pytest 完成（简化版：直接等待 timeout 后提取）
    # 实际生产环境应该有监控机制检测完成状态
    import time
    time.sleep(min(timeout, 10))  # 等待一段时间让 pytest 开始

    # 3. 提取远程日志
    grep_output = extract_remote_log(log_file, profile=profile, timeout=60)

    # 4. 确定输出路径
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "results"

    output_path = output_dir / f"{batch_id}_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 5. 解析并生成 batch_results.json
    parse_result = parse_batch_results(
        grep_output=grep_output,
        batch_id=batch_id,
        log_file=log_file,
        output_path=output_path
    )

    return {
        **start_result,
        "parse_status": parse_result.get("status"),
        "batch_results_path": str(output_path) if parse_result.get("status") == "success" else None,
        "batch_results": parse_result.get("batch_results"),
        "parse_error": parse_result.get("error")
    }


def run_batch_from_config(
    config_path: Path,
    worker: int = 1,
    timeout: int = 120
) -> dict:
    """
    从 batch_config.json 运行批次
    
    Args:
        config_path: batch_config.json 文件路径
        worker: Worker编号
        timeout: 超时秒数
        
    Returns:
        执行结果 dict
    """
    if not config_path.exists():
        return {"error": f"batch_config.json not found: {config_path}"}
    
    config = json.loads(config_path.read_text(encoding="utf-8"))
    
    tests = [t.get("test_node") for t in config.get("tests", [])]
    batch_id = config.get("batch_id", "unknown")
    
    if not tests:
        return {"error": "No tests in batch_config.json"}
    
    return run_batch(
        worker=worker,
        tests=tests,
        phase=1,
        round=1,
        timeout=timeout
    )


def main():
    parser = argparse.ArgumentParser(description="Runner批次执行脚本")

    # 模式1：从 workflow_state.json 读取配置
    parser.add_argument("--workflow-state", type=str,
                        help="workflow_state.json 路径")

    # 模式2：从 batch_config.json 读取测试列表
    parser.add_argument("--config-path", type=str,
                        help="batch_config.json 文件路径")

    # 模式3：直接指定测试列表
    parser.add_argument("--worker", type=int, default=1, help="Worker编号 (1-3)")
    parser.add_argument("--tests", nargs="+", help="测试列表")
    parser.add_argument("--phase", type=int, default=1, help="Phase编号")
    parser.add_argument("--round", type=int, default=1, help="Round编号")
    parser.add_argument("--timeout", type=int, default=120, help="超时秒数")

    # 新增：结果提取选项
    parser.add_argument("--with-results", action="store_true",
                        help="执行后提取远程日志并生成 batch_results.json")
    parser.add_argument("--output-dir", type=str,
                        help="batch_results.json 输出目录")
    parser.add_argument("--profile", type=str, default="default",
                        help="Bastion agent.py profile 名称")

    # 新增：仅提取模式（不启动 pytest，只提取已有日志）
    parser.add_argument("--extract-only", type=str,
                        help="仅提取指定日志文件路径的结果")

    args = parser.parse_args()

    workflow_state_path = None
    if args.workflow_state:
        workflow_state_path = Path(args.workflow_state)

    output_dir = Path(args.output_dir) if args.output_dir else None

    # 仅提取模式
    if args.extract_only:
        log_file = args.extract_only
        batch_id = Path(log_file).stem  # 从文件名提取 batch_id
        default_output_dir = Path(__file__).parent.parent / "results"
        output_path = (output_dir or default_output_dir) / f"{batch_id}_results.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        grep_output = extract_remote_log(log_file, profile=args.profile, timeout=60)
        parse_result = parse_batch_results(
            grep_output=grep_output,
            batch_id=batch_id,
            log_file=log_file,
            output_path=output_path
        )
        print(json.dumps(parse_result, indent=2))
        return

    if args.config_path:
        # 从 batch_config.json 读取
        config_path = Path(args.config_path)
        if args.with_results:
            result = run_batch_with_results(
                worker=args.worker,
                tests=[],  # 从 config 读取
                phase=args.phase,
                round=args.round,
                timeout=args.timeout,
                workflow_state_path=workflow_state_path,
                output_dir=output_dir,
                profile=args.profile
            )
        else:
            result = run_batch_from_config(
                config_path=config_path,
                worker=args.worker,
                timeout=args.timeout
            )
        print(json.dumps(result, indent=2))

    elif args.tests:
        # 直接指定测试列表
        if args.with_results:
            result = run_batch_with_results(
                worker=args.worker,
                tests=args.tests,
                phase=args.phase,
                round=args.round,
                timeout=args.timeout,
                workflow_state_path=workflow_state_path,
                output_dir=output_dir,
                profile=args.profile
            )
        else:
            result = run_batch(
                worker=args.worker,
                tests=args.tests,
                phase=args.phase,
                round=args.round,
                timeout=args.timeout,
                workflow_state_path=workflow_state_path
            )
        print(json.dumps(result, indent=2))

    else:
        # 默认：尝试从默认 workflow_state.json 读取 batch_config_path
        # 使用相对路径（不硬编码）
        default_workflow_state = Path(__file__).parent.parent.parent.parent / ".agents" / "workflow_state.json"
        if default_workflow_state.exists():
            state = load_workflow_state(default_workflow_state)
            if "error" not in state:
                batch_config_path = Path(state.get("paths", {}).get("batch_config", ""))
                if batch_config_path.exists():
                    if args.with_results:
                        result = run_batch_with_results(
                            worker=args.worker,
                            tests=[],  # 从 config 读取
                            phase=args.phase,
                            round=args.round,
                            timeout=args.timeout,
                            workflow_state_path=workflow_state_path,
                            output_dir=output_dir,
                            profile=args.profile
                        )
                    else:
                        result = run_batch_from_config(
                            config_path=batch_config_path,
                            worker=args.worker,
                            timeout=args.timeout
                        )
                    print(json.dumps(result, indent=2))
                else:
                    print(json.dumps({"error": "batch_config.json not found in workflow_state paths"}, indent=2))
            else:
                print(json.dumps(state, indent=2))
        else:
            print(json.dumps({"error": "请指定 --config-path 或 --tests"}, indent=2))


if __name__ == "__main__":
    main()