import subprocess, base64

cwd = r'D:\workspace\apmm'

# Write test script to remote
script = """import subprocess, os, sys
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['CUDA_VISIBLE_DEVICES'] = '0,1'
with open('/tmp/test_output.log', 'w') as f:
    p = subprocess.run(
        ['python3', '-m', 'pytest', '-k', 'TestMMRSModel', '-q', '--tb=long', '-s'],
        stdout=f, stderr=subprocess.STDOUT, timeout=120, env=env
    )
print(f'Exit code: {p.returncode}')
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/run_debug.py && python3 /tmp/run_debug.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '180',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('RUN:', r.stdout[-500:])
if r.stderr:
    print('ERR:', r.stderr[-300:])

# Read output
r2 = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '30',
    'sudo docker exec v0.13.0_torch2.5.1_compile tail -100 /tmp/test_output.log'],
    capture_output=True, text=True, cwd=cwd)
print('=== OUTPUT ===')
print(r2.stdout[-4000:])
if r2.stderr:
    print('ERR:', r2.stderr[-300:])
