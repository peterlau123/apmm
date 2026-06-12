import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['NCCL_DEBUG'] = 'INFO'
cmd = ['python3', '-m', 'pytest', '-k', 'TestMMRSModel', '-q', '--tb=short']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
print(r.stdout[-2000:])
if r.stderr:
    print('STDERR:', r.stderr[-1000:])
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/run_test.py && python3 /tmp/run_test.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '180',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('STDOUT:', r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-500:])
