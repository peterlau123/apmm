import subprocess, json

cwd = r'D:\workspace\apmm'

# Write python script to remote
script = """import subprocess
r = subprocess.run(['grep', '-n', '-E', 'TestMMRSModel|num_processes|world_size|nprocs', '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py'], capture_output=True, text=True)
print(r.stdout)
"""
# Encode as base64 to avoid quoting issues
import base64
encoded = base64.b64encode(script.encode()).decode()

cmd = f'echo {encoded} | base64 -d > /tmp/grep_test.py && python3 /tmp/grep_test.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '60',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('STDOUT:', r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-500:])
