import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['NCCL_DEBUG'] = 'INFO'
env['CUDA_VISIBLE_DEVICES'] = '0,1'
cmd = ['python3', '-m', 'pytest', '-k', 'TestMMRSModel', '-q', '--tb=short', '--timeout=60']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=env)
print(r.stdout[-3000:])
if r.stderr:
    print('STDERR:', r.stderr[-1500:])
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/run_test2.py && python3 /tmp/run_test2.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '120',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('STDOUT:', r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-500:])
