import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess
cmd = ['grep', '-n', 'MASTER_ADDR', '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py']
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/grep_master.py && python3 /tmp/grep_master.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('STDOUT:', r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-500:])
