import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['CUDA_VISIBLE_DEVICES'] = '0,1'
cmd = ['python3', '-m', 'pytest', '-k', 'TestMMRSModel', '-q', '--tb=long']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
print(r.stdout[-3000:])
if r.stderr:
    print('STDERR:', r.stderr[-1000:])
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/rerun2.py && python3 /tmp/rerun2.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '180',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('=== TEST RESULT ===')
print(r.stdout[-4000:])
if r.stderr:
    print('STDERR:', r.stderr[-500:])
