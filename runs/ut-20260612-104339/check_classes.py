import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess
path = '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py'
with open(path) as f:
    lines = f.readlines()

# Print TestMMRSModel class (lines 48-79)
for i in range(47, 80):
    print(f'{i+1}: {lines[i]}', end='')
print('---')
# Print TestScaledMMRSModel class (lines 123-148)
for i in range(123, 149):
    print(f'{i+1}: {lines[i]}', end='')
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/check_classes.py && python3 /tmp/check_classes.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print(r.stdout)
if r.stderr:
    print('ERR:', r.stderr[-300:])
