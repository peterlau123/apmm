import subprocess, base64

cwd = r'D:\workspace\apmm'

# Step 1: Revert the MASTER_ADDR fix
script = """path = '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py'
with open(path) as f:
    content = f.read()
content = content.replace('"MASTER_ADDR": "127.0.0.1"', '"MASTER_ADDR": "localhost"')
with open(path, 'w') as f:
    f.write(content)
print('Reverted MASTER_ADDR fix')
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/revert_fix.py && python3 /tmp/revert_fix.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('Revert:', r.stdout)
