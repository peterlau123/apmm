import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess
path = '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py'
with open(path) as f:
    lines = f.readlines()

# Print parametrize decorators and test function
for i in range(225, 295):
    print(f'{i+1}: {lines[i]}', end='')
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/check_params.py && python3 /tmp/check_params.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print(r.stdout)
if r.stderr:
    print('ERR:', r.stderr[-300:])
