import subprocess

cwd = r'D:\workspace\apmm'

# Use python to write the file, then run it
cmd = r"""python3 -c "
import os
script = '''grep -n TestMMRSModel /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py
grep -n num_processes /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py
grep -n world_size /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py
grep -n nprocs /gpfs/gcsp/M2.7_verify/vllm/tests/compile/distributed/test_async_tp.py
'''
with open('/tmp/grep_test.sh', 'w') as f:
    f.write(script)
os.chmod('/tmp/grep_test.sh', 0o755)
print('Script written')
""" && bash /tmp/grep_test.sh"""

r = subprocess.run(['python', 'tools/agent.py', '-p', 't_h20', 'run', '--timeout', '60',
    'sudo docker exec v0.13.0_torch2.5.1_compile bash -c "' + cmd + '"'],
    capture_output=True, text=True, cwd=cwd)
print('STDOUT:', r.stdout)
if r.stderr:
    print('STDERR:', r.stderr[-500:])
