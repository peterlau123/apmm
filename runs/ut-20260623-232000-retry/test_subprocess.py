import subprocess
import sys

agent_py = "D:/workspace/apmm/tools/agent.py"
cmd = "sudo -n docker exec v0.13.0_torch2.5.1_compile bash -c 'echo test_from_subprocess'"
args = [sys.executable, agent_py, "-p", "t_h20", "run", "--timeout", "60", cmd]

r = subprocess.run(args, capture_output=True, text=True, timeout=120, cwd="D:/workspace/apmm")
print(f"exit_code: {r.returncode}")
print(f"stdout: {r.stdout}")
print(f"stderr: {r.stderr}")