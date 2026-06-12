import subprocess, json, sys

cmd = [
    "python", "tools/agent.py", "-p", "t_h20", "run", "--timeout", "60",
    "sudo docker exec v0.13.0_torch2.5.1_compile bash -c 'cd /gpfs/gcsp/M2.7_verify/vllm && grep -n -E \"TestMMRSModel|TestScaledMMRSModel|num_processes|world_size\" tests/compile/distributed/test_async_tp.py'"
]
result = subprocess.run(cmd, capture_output=True, text=True, cwd=r"D:\workspace\apmm")
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:500])
