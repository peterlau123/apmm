import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess
path = '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py'
with open(path) as f:
    lines = f.readlines()

# Print test_async_tp_pass_correctness function
in_func = False
for i, line in enumerate(lines, 1):
    if 'def test_async_tp_pass_correctness' in line:
        in_func = True
    if in_func:
        print(f'{i}: {line}', end='')
    if in_func and line.strip() == '' and i > 430:
        break
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/check_correctness.py && python3 /tmp/check_correctness.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print(r.stdout)
if r.stderr:
    print('ERR:', r.stderr[-300:])
