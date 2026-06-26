"""
retry_test.py - 重试测试脚本（L2）

职责：在远程容器运行单个测试 → 返回结果

用法：
    python retry_test.py --test-node "tests/test_load.py::test_llama"
    python retry_test.py --test-node PATH --delay 5 --max-retries 3
"""

import argparse
import subprocess
import json
import re
import base64
import time
from pathlib import Path
from datetime import datetime


def run_remote_test(test_node: str, remote_server: str, container: str, pytest_args: str, timeout: int) -> dict:
    """在远程容器运行测试"""
    script = f"""
import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['HF_HOME'] = '/gpfs/gcsp/M2.7_verify/pytorch_verify/2.5.1/ut/hf_hub'
env['CUDA_VISIBLE_DEVICES'] = '0,1,2,3,4,5,6,7'
cmd = ['python3', '-m', 'pytest', '{test_node}', '{pytest_args}']
r = subprocess.run(cmd, capture_output=True, text=True, timeout={timeout}, env=env)
print(r.stdout)
if r.stderr: print('STDERR:', r.stderr[-2000:])
"""
    encoded = base64.b64encode(script.encode()).decode()
    remote_cmd = f'echo {encoded} | base64 -d > /tmp/ut_retry.py && python3 /tmp/ut_retry.py'

    try:
        result = subprocess.run(
            ['python', 'tools/agent.py', '-p', remote_server, 'run', '--timeout', str(timeout + 60),
             f'sudo docker exec {container} bash -c "{remote_cmd}"'],
            capture_output=True, text=True, timeout=timeout + 90,
            cwd=Path(__file__).parent.parent.parent.parent.parent
        )
        output = result.stdout
        status = "passed" if re.search(rf"{test_node}.*PASSED", output, re.IGNORECASE) else \
                 "failed" if "FAILED" in output else "error" if "ERROR" in output else "unknown"
        match = re.search(r"(\d+\.\d+)s", output)
        duration = int(float(match.group(1)) * 1000) if match else 0
        return {"status": status, "duration_ms": duration, "output": output[-500:]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "duration_ms": timeout * 1000, "output": "Timeout"}


def retry_with_delay(test_node: str, remote_server: str, container: str, pytest_args: str, delays: list) -> dict:
    """延时重试"""
    for delay in delays:
        time.sleep(delay)
        result = run_remote_test(test_node, remote_server, container, pytest_args, 600)
        if result["status"] == "passed":
            return {**result, "retry_count": delays.index(delay) + 1}
    return {"status": "failed", "retry_count": len(delays)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-node", required=True)
    parser.add_argument("--remote-server", default="t_h20")
    parser.add_argument("--container", default="v0.13.0_torch2.5.1_compile")
    parser.add_argument("--pytest-args", default="-q --tb=long")
    parser.add_argument("--delay", type=int)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    if args.delay:
        delays = [args.delay * (i + 1) for i in range(args.max_retries)]
        result = retry_with_delay(args.test_node, args.remote_server, args.container, args.pytest_args, delays)
    else:
        result = run_remote_test(args.test_node, args.remote_server, args.container, args.pytest_args, args.timeout)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()