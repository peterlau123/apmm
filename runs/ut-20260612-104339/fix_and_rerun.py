import subprocess, base64

cwd = r'D:\workspace\apmm'

# Fix: replace localhost with 127.0.0.1
script1 = """import subprocess
path = '/gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py'
with open(path) as f:
    content = f.read()
content = content.replace('"MASTER_ADDR": "localhost"', '"MASTER_ADDR": "127.0.0.1"')
with open(path, 'w') as f:
    f.write(content)
print('Fixed MASTER_ADDR')
"""

encoded1 = base64.b64encode(script1.encode()).decode()
cmd1 = f'echo {encoded1} | base64 -d > /tmp/fix_master.py && python3 /tmp/fix_master.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd1 + '"'],
    capture_output=True, text=True, cwd=cwd)
print('Fix:', r.stdout)
if r.stderr:
    print('ERR:', r.stderr[-300:])

# Run test again
script2 = """import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['CUDA_VISIBLE_DEVICES'] = '0,1'
cmd = ['python3', '-m', 'pytest', '-k', 'TestMMRSModel', '-q', '--tb=long']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
print(r.stdout[-2000:])
if r.stderr:
    print('STDERR:', r.stderr[-1000:])
"""

encoded2 = base64.b64encode(script2.encode()).decode()
cmd2 = f'echo {encoded2} | base64 -d > /tmp/rerun_test.py && python3 /tmp/rerun_test.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '120',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd2 + '"'],
    capture_output=True, text=True, cwd=cwd)
print('=== TEST RESULT ===')
print(r.stdout[-3000:])
if r.stderr:
    print('STDERR:', r.stderr[-500:])
