import subprocess, base64

cwd = r'D:\workspace\apmm'

script = """import subprocess, os
os.chdir('/gpfs/gcsp/M2.7_verify/vllm')
env = os.environ.copy()
env['CUDA_VISIBLE_DEVICES'] = '0,1'
env['NCCL_DEBUG'] = 'INFO'
env['TORCH_DISTRIBUTED_DEBUG'] = 'DETAIL'
env['CUDA_LAUNCH_BLOCKING'] = '1'
cmd = ['python3', '-m', 'pytest', '-k', 'TestMMRSModel', '-q', '--tb=long', '-s']
r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
# Print last 4000 chars
out = r.stdout
if len(out) > 4000:
    out = out[-4000:]
print(out)
if r.stderr:
    err = r.stderr
    if len(err) > 2000:
        err = err[-2000:]
    print('STDERR:', err)
"""

encoded = base64.b64encode(script.encode()).decode()
cmd = f'echo {encoded} | base64 -d > /tmp/debug_test.py && python3 /tmp/debug_test.py'

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '180',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print(r.stdout[-5000:])
if r.stderr:
    print('ERR:', r.stderr[-500:])
